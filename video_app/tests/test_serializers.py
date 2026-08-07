"""Tests for the video serializer.

The response shape is fixed by the frontend, which reads every value straight
off the parsed JSON. What the serializer omits is just as binding as what it
includes: the path to the uploaded source file must never leave the backend,
because that file is the whole film in original quality.
"""

from django.test import RequestFactory, TestCase
from django.utils.dateparse import parse_datetime

from video_app.api.serializers import VideoSerializer
from video_app.models import Video

CONTRACT_FIELDS = {
    "id",
    "created_at",
    "title",
    "description",
    "thumbnail_url",
    "category",
}


def serialize(video):
    """Serialize with a request in the context, the way a view would.

    build_absolute_uri needs the request to know scheme and host; without it
    there is no way to produce the absolute URL the frontend requires.
    """
    request = RequestFactory().get("/api/video/")
    return VideoSerializer(video, context={"request": request}).data


class VideoSerializerFieldTests(TestCase):
    """The payload carries the contract fields — and nothing else."""

    def setUp(self):
        self.video = Video.objects.create(
            title="Heavy Rain",
            description="Water falls.",
            category="drama",
            video_file="uploads/videos/film.mp4",
            thumbnail="thumbnails/film.jpg",
        )

    def test_payload_carries_exactly_the_contract_fields(self):
        """A field set declared one by one is the point of the rule against __all__."""
        self.assertEqual(set(serialize(self.video)), CONTRACT_FIELDS)

    def test_payload_hides_the_source_file(self):
        """Handing out this path would serve the original film without a login.

        The HLS endpoints are guarded, but a direct media link would bypass all
        of them, so the field never appears in a response.
        """
        self.assertNotIn("video_file", serialize(self.video))

    def test_payload_hides_the_conversion_state(self):
        """hls_status and hls_error are operational data, not part of the contract."""
        payload = serialize(self.video)
        self.assertNotIn("hls_status", payload)
        self.assertNotIn("hls_error", payload)


class ThumbnailUrlTests(TestCase):
    """The frontend uses the value as an <img src> (video_list.js:199)."""

    def test_thumbnail_url_is_absolute(self):
        """A relative path would resolve against the frontend's origin, not ours."""
        video = Video.objects.create(
            title="Heavy Rain",
            description="Water falls.",
            category="drama",
            video_file="uploads/videos/film.mp4",
            thumbnail="thumbnails/film.jpg",
        )
        self.assertEqual(
            serialize(video)["thumbnail_url"],
            "http://testserver/media/thumbnails/film.jpg",
        )

    def test_thumbnail_url_is_null_while_none_exists(self):
        """The pipeline extracts the image later, so the field has to survive its absence.

        Reading obj.thumbnail.url on an empty field raises ValueError, which
        would turn the whole list endpoint into a 500.
        """
        video = Video.objects.create(
            title="No Image Yet",
            description="Water falls.",
            category="drama",
            video_file="uploads/videos/film.mp4",
        )
        self.assertIsNone(serialize(video)["thumbnail_url"])


class CreatedAtTests(TestCase):
    """video_list.js:94 feeds the value into new Date() to build the newest section."""

    def test_created_at_survives_a_round_trip(self):
        video = Video.objects.create(
            title="Heavy Rain",
            description="Water falls.",
            category="drama",
            video_file="uploads/videos/film.mp4",
        )
        self.assertEqual(
            parse_datetime(serialize(video)["created_at"]), video.created_at
        )
