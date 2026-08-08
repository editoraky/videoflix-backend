"""Tests for the video models.

Field names are not a design choice here. The frontend reads them directly:
video.id, video.title, video.description, video.category and video.created_at
(video_list.js:82, 94, 105, 106, 122, 201). Renaming any of them breaks the
dashboard without a single error message, because loadAndSetupVideos swallows
the exception and only shows "Failed to load videos".
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from video_app.models import Video, VideoVariant
from video_app.tests.support import create_video


class VideoFieldTests(TestCase):
    """The contract fields exist, and they are wide enough for real content."""

    def test_the_contract_fields_exist(self):
        """Every name the frontend reads must be a field on the model."""
        field_names = {field.name for field in Video._meta.get_fields()}
        for name in ("id", "title", "description", "category", "created_at"):
            self.assertIn(name, field_names)

    def test_title_holds_one_hundred_characters(self):
        self.assertEqual(Video._meta.get_field("title").max_length, 100)

    def test_category_holds_fifty_characters(self):
        self.assertEqual(Video._meta.get_field("category").max_length, 50)

    def test_created_at_is_written_by_the_database_layer(self):
        """Sorting and the "newest" section depend on a value nobody can forget.

        video_list.js:90-99 filters the last five days by created_at, so the
        timestamp has to be set on insert rather than by whoever creates the row.
        """
        self.assertTrue(Video._meta.get_field("created_at").auto_now_add)

    def test_updated_at_follows_every_save(self):
        self.assertTrue(Video._meta.get_field("updated_at").auto_now)

    def test_thumbnail_is_optional(self):
        """A video may exist before its thumbnail has been extracted."""
        self.assertTrue(Video._meta.get_field("thumbnail").blank)

    def test_str_returns_the_title(self):
        """Admin lists show the title, not "Video object (1)"."""
        self.assertEqual(str(create_video(title="Heavy Rain")), "Heavy Rain")


class VideoConversionStateTests(TestCase):
    """The conversion runs in a worker, so its state has to be readable."""

    def test_a_new_video_waits_for_conversion(self):
        """Nothing is converted at upload time, so pending is the only honest start."""
        self.assertEqual(create_video().hls_status, "pending")

    def test_error_text_starts_empty_instead_of_null(self):
        """An empty string keeps "no error" a single value instead of two."""
        self.assertEqual(create_video().hls_error, "")


class VideoFileValidationTests(TestCase):
    """Uploads come through the admin only, but a slip there is silent."""

    def test_video_file_rejects_a_document(self):
        """FFMPEG cannot convert a PDF; the model should say so before the worker does."""
        video = Video(
            title="Wrong File",
            description="Some description.",
            category="drama",
            video_file="uploads/videos/report.pdf",
        )
        with self.assertRaises(ValidationError):
            video.full_clean()

    def test_video_file_accepts_mp4(self):
        video = Video(
            title="Right File",
            description="Some description.",
            category="drama",
            video_file="uploads/videos/film.mp4",
        )
        try:
            video.full_clean()
        except ValidationError as error:
            self.fail(f"A supported container was rejected: {error}")


class VideoOrderingTests(TestCase):
    """Checklist US 5 asks for creation date descending.

    The frontend relies on that order twice: VIDEOS[0] becomes the hero teaser
    (video_list.js:104-107), and every category row is rendered in list order.
    """

    def test_meta_declares_newest_first(self):
        self.assertEqual(Video._meta.ordering, ["-created_at"])

    def test_default_queryset_starts_with_the_newest_video(self):
        """A declared ordering is worthless if the query does not apply it.

        auto_now_add ignores assigned values, so the timestamps are rewritten
        afterwards with update(), which bypasses save() and therefore auto_now.
        """
        now = timezone.now()
        oldest = create_video(title="Oldest")
        middle = create_video(title="Middle")
        newest = create_video(title="Newest")
        for video, age_in_days in ((oldest, 3), (middle, 2), (newest, 1)):
            Video.objects.filter(pk=video.pk).update(
                created_at=now - timedelta(days=age_in_days)
            )
        self.assertEqual(
            [video.title for video in Video.objects.all()],
            ["Newest", "Middle", "Oldest"],
        )


class VideoVariantFieldTests(TestCase):
    """One row per converted resolution, so each one can fail on its own."""

    def setUp(self):
        self.video = create_video()

    def test_resolutions_match_the_player_dropdown(self):
        """The frontend offers exactly these three values (index.html:76-78).

        A fourth choice would never be requested; a missing one would leave the
        dropdown pointing at a resolution that does not exist.
        """
        codes = [code for code, _ in VideoVariant._meta.get_field("resolution").choices]
        self.assertEqual(codes, ["480p", "720p", "1080p"])

    def test_a_new_variant_waits_for_conversion(self):
        variant = VideoVariant.objects.create(video=self.video, resolution="480p")
        self.assertEqual(variant.status, "pending")

    def test_a_new_variant_has_no_segments_yet(self):
        variant = VideoVariant.objects.create(video=self.video, resolution="480p")
        self.assertEqual(variant.segment_count, 0)

    def test_playlist_path_starts_empty(self):
        """The path is unknown until FFMPEG has written the manifest."""
        variant = VideoVariant.objects.create(video=self.video, resolution="480p")
        self.assertEqual(variant.playlist_path, "")

    def test_str_names_video_and_resolution(self):
        variant = VideoVariant.objects.create(video=self.video, resolution="720p")
        self.assertEqual(str(variant), "A Film (720p)")


class VideoVariantRelationTests(TestCase):
    """The link to the video carries two guarantees the worker depends on."""

    def setUp(self):
        self.video = create_video()

    def test_variants_are_reachable_from_the_video(self):
        VideoVariant.objects.create(video=self.video, resolution="480p")
        self.assertEqual(self.video.variants.count(), 1)

    def test_deleting_a_video_removes_its_variants(self):
        """Rows for a film that no longer exists would be read as ready segments."""
        VideoVariant.objects.create(video=self.video, resolution="480p")
        self.video.delete()
        self.assertEqual(VideoVariant.objects.count(), 0)

    def test_a_resolution_exists_only_once_per_video(self):
        """A retried job must update its row instead of adding a second one.

        Without the constraint the streaming view would have to pick between
        duplicates, and one of them could be stale.
        """
        VideoVariant.objects.create(video=self.video, resolution="480p")
        with self.assertRaises(IntegrityError):
            VideoVariant.objects.create(video=self.video, resolution="480p")

    def test_the_same_resolution_may_exist_for_another_video(self):
        other = create_video(title="Another Film")
        VideoVariant.objects.create(video=self.video, resolution="480p")
        variant = VideoVariant.objects.create(video=other, resolution="480p")
        self.assertEqual(variant.video, other)
