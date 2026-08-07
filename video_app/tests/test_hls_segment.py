"""Tests for the segment endpoint.

The documented path ends with a slash. A player does not use it that way: the
manifest lists "000.ts" as a relative URI, and RFC 8216 resolves that against
the manifest URL, which produces .../480p/000.ts without a trailing slash.

APPEND_SLASH would answer such a request with a 301. That works in a browser
but costs a redirect per segment, so both spellings are routed directly.
"""

import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from video_app.models import Video

User = get_user_model()

TEMPORARY_MEDIA_ROOT = tempfile.mkdtemp()

SEGMENT_BYTES = b"\x47\x40\x00\x10not really transport stream"


def write_segment(video_id, resolution, name="000.ts"):
    """Place a segment where the endpoint is expected to look for it."""
    directory = Path(TEMPORARY_MEDIA_ROOT) / "videos" / str(video_id) / resolution
    directory.mkdir(parents=True, exist_ok=True)
    segment = directory / name
    segment.write_bytes(SEGMENT_BYTES)
    return segment


@override_settings(MEDIA_ROOT=TEMPORARY_MEDIA_ROOT)
class HlsSegmentTestCase(APITestCase):
    """Shared setup: one video, one member, one segment on disk."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMPORARY_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.video = Video.objects.create(
            title="Heavy Rain",
            description="Water falls.",
            category="drama",
            video_file="uploads/videos/film.mp4",
        )
        write_segment(self.video.pk, "480p")
        self.url = f"/api/video/{self.video.pk}/480p/000.ts"

    def authenticate(self):
        user = User.objects.create_user(
            username="viewer@example.com",
            email="viewer@example.com",
            password="secret123",
        )
        access = RefreshToken.for_user(user).access_token
        self.client.cookies[settings.AUTH_COOKIE_ACCESS] = str(access)


class HlsSegmentAccessTests(HlsSegmentTestCase):
    """A segment is a piece of the film and needs the same guard as the manifest."""

    def test_without_a_cookie_the_segment_stays_closed(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_a_member_receives_the_segment(self):
        self.authenticate()
        self.assertEqual(self.client.get(self.url).status_code, 200)


class HlsSegmentDeliveryTests(HlsSegmentTestCase):
    """Shape of the answer the player consumes."""

    def setUp(self):
        super().setUp()
        self.authenticate()

    def test_content_type_is_the_transport_stream_type(self):
        self.assertEqual(self.client.get(self.url)["Content-Type"], "video/MP2T")

    def test_body_is_the_segment_on_disk(self):
        response = self.client.get(self.url)
        self.assertEqual(b"".join(response.streaming_content), SEGMENT_BYTES)

    def test_the_path_without_a_slash_is_answered_directly(self):
        """No 301 in front of every segment — that is what the player requests."""
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_the_documented_path_with_a_slash_also_works(self):
        """The API documentation spells it with a trailing slash."""
        self.assertEqual(self.client.get(f"{self.url}/").status_code, 200)


class HlsSegmentNotFoundTests(HlsSegmentTestCase):
    """Nothing missing turns into a 500, and nothing escapes the folder."""

    def setUp(self):
        super().setUp()
        self.authenticate()
        self.secret = Path(TEMPORARY_MEDIA_ROOT) / "secret.txt"
        self.secret.write_text("SECRET_KEY=do-not-serve-this")

    def tearDown(self):
        self.secret.unlink(missing_ok=True)

    def test_unknown_segment_is_not_found(self):
        response = self.client.get(f"/api/video/{self.video.pk}/480p/999.ts")
        self.assertEqual(response.status_code, 404)

    def test_only_transport_streams_are_served_here(self):
        """Anything else in the folder stays out of reach of this endpoint.

        The manifest has its own route with its own media type; serving it here
        would answer with video/MP2T, and any file a later pipeline step drops
        into the folder would become reachable.
        """
        (Path(TEMPORARY_MEDIA_ROOT) / "videos" / str(self.video.pk) / "480p"
         / "notes.txt").write_text("internal")
        response = self.client.get(f"/api/video/{self.video.pk}/480p/notes.txt")
        self.assertEqual(response.status_code, 404)

    def test_the_manifest_is_not_reachable_through_the_segment_route(self):
        response = self.client.get(f"/api/video/{self.video.pk}/480p/index.m3u8/")
        self.assertEqual(response.status_code, 404)

    def test_resolution_outside_the_whitelist_is_not_found(self):
        response = self.client.get(f"/api/video/{self.video.pk}/240p/000.ts")
        self.assertEqual(response.status_code, 404)

    def test_traversal_in_the_segment_name_is_refused(self):
        response = self.client.get(f"/api/video/{self.video.pk}/480p/../../secret.txt")
        self.assertNotEqual(response.status_code, 200)

    def test_encoded_traversal_in_the_segment_name_is_refused(self):
        response = self.client.get(
            f"/api/video/{self.video.pk}/480p/%2E%2E%2F%2E%2E%2Fsecret.txt"
        )
        self.assertNotEqual(response.status_code, 200)

    def test_no_answer_ever_contains_the_neighbouring_file(self):
        for path in ("../../secret.txt", "%2E%2E%2F%2E%2E%2Fsecret.txt"):
            response = self.client.get(f"/api/video/{self.video.pk}/480p/{path}")
            body = (
                b"".join(response.streaming_content)
                if response.streaming
                else response.content
            )
            self.assertNotIn(b"do-not-serve-this", body, msg=path)
