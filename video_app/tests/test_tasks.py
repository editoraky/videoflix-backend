"""Tests for the conversion jobs.

These run the job function directly rather than through a queue. What matters
here is what the job does to the database and to the file system; that RQ can
call it is a separate question, answered where the job is enqueued.

The bridge test is the important one: it asks the streaming endpoint's own path
builder whether the file the job wrote is the file the endpoint would serve.
Two spellings of the same layout would otherwise pass every test on both sides
and still refuse to play.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from video_app.api.utils import build_hls_path
from video_app.models import Video, VideoVariant
from video_app.tasks import convert_video_to_hls, generate_video_thumbnail

TEMPORARY_MEDIA_ROOT = tempfile.mkdtemp()


def place_source_clip(media_root, relative_name='uploads/videos/clip.mp4'):
    """Generate a clip where an upload would have stored it."""
    target = Path(media_root) / relative_name
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            'ffmpeg', '-y', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'testsrc=duration=2:size=320x240:rate=10',
            '-pix_fmt', 'yuv420p', str(target),
        ],
        check=True,
        capture_output=True,
    )
    return relative_name


@override_settings(MEDIA_ROOT=TEMPORARY_MEDIA_ROOT)
class ConversionJobTests(TestCase):
    """A successful run of one resolution."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMPORARY_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.video = Video.objects.create(
            title="Heavy Rain",
            description="Water falls.",
            category="drama",
            video_file=place_source_clip(TEMPORARY_MEDIA_ROOT),
        )

    def test_the_variant_ends_up_ready(self):
        convert_video_to_hls(self.video.pk, '480p')
        variant = VideoVariant.objects.get(video=self.video, resolution='480p')
        self.assertEqual(variant.status, 'ready')

    def test_the_playlist_lands_where_the_endpoint_looks_for_it(self):
        """Writer and reader have to agree on the path, not just on the idea."""
        convert_video_to_hls(self.video.pk, '480p')
        expected = build_hls_path(self.video.pk, '480p', 'index.m3u8')
        self.assertTrue(expected.is_file())

    def test_segments_are_counted(self):
        convert_video_to_hls(self.video.pk, '480p')
        variant = VideoVariant.objects.get(video=self.video, resolution='480p')
        self.assertGreater(variant.segment_count, 0)

    def test_the_playlist_path_is_stored_relative_to_the_media_root(self):
        """An absolute path would break the moment the volume is mounted elsewhere."""
        convert_video_to_hls(self.video.pk, '480p')
        variant = VideoVariant.objects.get(video=self.video, resolution='480p')
        self.assertEqual(variant.playlist_path, f'videos/{self.video.pk}/480p/index.m3u8')

    def test_running_twice_keeps_a_single_variant(self):
        """A retry updates its row; the unique constraint would reject a second."""
        convert_video_to_hls(self.video.pk, '480p')
        convert_video_to_hls(self.video.pk, '480p')
        self.assertEqual(VideoVariant.objects.filter(video=self.video).count(), 1)

    def test_each_resolution_gets_its_own_row(self):
        convert_video_to_hls(self.video.pk, '480p')
        convert_video_to_hls(self.video.pk, '720p')
        self.assertEqual(VideoVariant.objects.filter(video=self.video).count(), 2)

    def test_the_video_is_still_processing_after_one_resolution(self):
        """Two renditions are missing, so the film is not finished."""
        convert_video_to_hls(self.video.pk, '480p')
        self.video.refresh_from_db()
        self.assertEqual(self.video.hls_status, 'processing')

    def test_the_video_turns_ready_once_every_resolution_is_done(self):
        for resolution in ('480p', '720p', '1080p'):
            convert_video_to_hls(self.video.pk, resolution)
        self.video.refresh_from_db()
        self.assertEqual(self.video.hls_status, 'ready')


@override_settings(MEDIA_ROOT=TEMPORARY_MEDIA_ROOT)
class ConversionJobFailureTests(TestCase):
    """Nothing here may end as an unhandled exception in the worker log."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMPORARY_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        broken = Path(TEMPORARY_MEDIA_ROOT) / 'uploads/videos/broken.mp4'
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_bytes(b'this is not a video')
        self.video = Video.objects.create(
            title="Broken",
            description="Not a movie.",
            category="drama",
            video_file='uploads/videos/broken.mp4',
        )

    def test_a_broken_source_marks_the_variant_failed(self):
        convert_video_to_hls(self.video.pk, '480p')
        variant = VideoVariant.objects.get(video=self.video, resolution='480p')
        self.assertEqual(variant.status, 'failed')

    def test_the_reason_is_recorded_on_the_video(self):
        """An admin has to see why a film stayed unplayable, not only that it did."""
        convert_video_to_hls(self.video.pk, '480p')
        self.video.refresh_from_db()
        self.assertTrue(self.video.hls_error.strip())

    def test_the_reason_names_the_resolution(self):
        """Three renditions share one error field, so the text has to say which failed."""
        convert_video_to_hls(self.video.pk, '480p')
        self.video.refresh_from_db()
        self.assertIn('480p', self.video.hls_error)

    def test_a_failed_rendition_marks_the_video_failed(self):
        """Whatever else happens, the film must not end up looking playable."""
        convert_video_to_hls(self.video.pk, '480p')
        self.video.refresh_from_db()
        self.assertNotEqual(self.video.hls_status, 'ready')

    def test_a_deleted_video_does_not_raise(self):
        """The job may reach the worker after the admin removed the video again."""
        video_id = self.video.pk
        self.video.delete()
        convert_video_to_hls(video_id, '480p')
        self.assertEqual(VideoVariant.objects.count(), 0)


@override_settings(MEDIA_ROOT=TEMPORARY_MEDIA_ROOT)
class ThumbnailJobTests(TestCase):
    """The still is generated, unless somebody already supplied one."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMPORARY_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.video = Video.objects.create(
            title="Heavy Rain",
            description="Water falls.",
            category="drama",
            video_file=place_source_clip(TEMPORARY_MEDIA_ROOT),
        )

    def test_a_thumbnail_is_generated(self):
        generate_video_thumbnail(self.video.pk)
        self.video.refresh_from_db()
        self.assertTrue(self.video.thumbnail)

    def test_the_generated_file_lands_in_the_public_subtree(self):
        """Only /media/thumbnails/ is routed, so anywhere else stays invisible."""
        generate_video_thumbnail(self.video.pk)
        self.video.refresh_from_db()
        self.assertTrue(self.video.thumbnail.name.startswith('thumbnails/'))

    def test_an_uploaded_thumbnail_is_kept(self):
        """Somebody chose that image on purpose; a frame grab is the fallback."""
        self.video.thumbnail = 'thumbnails/chosen.jpg'
        self.video.save()
        generate_video_thumbnail(self.video.pk)
        self.video.refresh_from_db()
        self.assertEqual(self.video.thumbnail.name, 'thumbnails/chosen.jpg')

    def test_a_broken_source_leaves_the_video_without_a_thumbnail(self):
        """A missing still is a cosmetic defect, not a reason to fail the job."""
        broken = Path(TEMPORARY_MEDIA_ROOT) / 'uploads/videos/no_frames.mp4'
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_bytes(b'this is not a video')
        video = Video.objects.create(
            title="Broken",
            description="Not a movie.",
            category="drama",
            video_file='uploads/videos/no_frames.mp4',
        )
        generate_video_thumbnail(video.pk)
        video.refresh_from_db()
        self.assertFalse(video.thumbnail)

    def test_a_deleted_video_does_not_raise(self):
        video_id = self.video.pk
        self.video.delete()
        generate_video_thumbnail(video_id)
