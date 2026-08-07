"""Tests for GET /api/video/<id>/<resolution>/index.m3u8.

Two segments of this URL are attacker-controlled and end up in a file path.
That makes this endpoint the most dangerous one in the project: MEDIA_ROOT sits
inside /app, and one directory above it lies .env with SECRET_KEY, the database
password and the SMTP credentials. Every test that pushes a path upwards is
there to keep that door shut.
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

PLAYLIST_BODY = "#EXTM3U\n#EXT-X-VERSION:3\n000.ts\n#EXT-X-ENDLIST\n"


def write_playlist(video_id, resolution, body=PLAYLIST_BODY):
    """Place a manifest where the endpoint is expected to look for it."""
    directory = Path(TEMPORARY_MEDIA_ROOT) / "videos" / str(video_id) / resolution
    directory.mkdir(parents=True, exist_ok=True)
    playlist = directory / "index.m3u8"
    playlist.write_text(body)
    return playlist


@override_settings(MEDIA_ROOT=TEMPORARY_MEDIA_ROOT)
class HlsPlaylistTestCase(APITestCase):
    """Shared setup: one video, one member, one manifest on disk."""

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
        write_playlist(self.video.pk, "480p")
        self.url = f"/api/video/{self.video.pk}/480p/index.m3u8"

    def authenticate(self):
        user = User.objects.create_user(
            username="viewer@example.com",
            email="viewer@example.com",
            password="secret123",
        )
        access = RefreshToken.for_user(user).access_token
        self.client.cookies[settings.AUTH_COOKIE_ACCESS] = str(access)


class HlsPlaylistAccessTests(HlsPlaylistTestCase):
    """The mentor asked for 401 without a valid access cookie (contract C-14)."""

    def test_without_a_cookie_the_manifest_stays_closed(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_a_member_receives_the_manifest(self):
        self.authenticate()
        self.assertEqual(self.client.get(self.url).status_code, 200)


class HlsPlaylistContentTests(HlsPlaylistTestCase):
    """What the player needs in order to parse the response at all."""

    def setUp(self):
        super().setUp()
        self.authenticate()

    def test_content_type_is_the_hls_media_type(self):
        response = self.client.get(self.url)
        self.assertEqual(response["Content-Type"], "application/vnd.apple.mpegurl")

    def test_body_is_the_manifest_on_disk(self):
        response = self.client.get(self.url)
        self.assertEqual(b"".join(response.streaming_content).decode(), PLAYLIST_BODY)

    def test_every_resolution_has_its_own_manifest(self):
        """Three media playlists, no master playlist (contract C-15)."""
        for resolution in ("480p", "720p", "1080p"):
            write_playlist(self.video.pk, resolution)
            response = self.client.get(
                f"/api/video/{self.video.pk}/{resolution}/index.m3u8"
            )
            self.assertEqual(response.status_code, 200, msg=resolution)


class HlsPlaylistNotFoundTests(HlsPlaylistTestCase):
    """Missing things answer 404 — never 500, and never a traceback."""

    def setUp(self):
        super().setUp()
        self.authenticate()

    def test_unknown_video_is_not_found(self):
        response = self.client.get("/api/video/9999/480p/index.m3u8")
        self.assertEqual(response.status_code, 404)

    def test_resolution_outside_the_whitelist_is_not_found(self):
        """240p is not offered by the player, so no directory may be derived from it."""
        response = self.client.get(f"/api/video/{self.video.pk}/240p/index.m3u8")
        self.assertEqual(response.status_code, 404)

    def test_missing_manifest_is_not_found(self):
        """The conversion may not have run yet; that is not a server error."""
        response = self.client.get(f"/api/video/{self.video.pk}/720p/index.m3u8")
        self.assertEqual(response.status_code, 404)


class HlsPlaylistTraversalTests(HlsPlaylistTestCase):
    """The resolution segment must never be able to leave its directory."""

    def setUp(self):
        super().setUp()
        self.authenticate()
        # A file one level above the video tree stands in for .env.
        self.secret = Path(TEMPORARY_MEDIA_ROOT) / "secret.txt"
        self.secret.write_text("SECRET_KEY=do-not-serve-this")

    def tearDown(self):
        self.secret.unlink(missing_ok=True)

    def test_dot_dot_as_resolution_is_refused(self):
        response = self.client.get(f"/api/video/{self.video.pk}/../index.m3u8")
        self.assertNotEqual(response.status_code, 200)

    def test_encoded_traversal_in_the_resolution_is_refused(self):
        """%2F decodes to a slash before routing, %2E%2E to a parent hop."""
        response = self.client.get(
            f"/api/video/{self.video.pk}/%2E%2E%2F%2E%2E/index.m3u8"
        )
        self.assertNotEqual(response.status_code, 200)

    def test_the_response_never_contains_the_neighbouring_file(self):
        """Whatever the status code is, the secret must not be in the body."""
        response = self.client.get(f"/api/video/{self.video.pk}/../../secret.txt")
        body = (
            b"".join(response.streaming_content)
            if response.streaming
            else response.content
        )
        self.assertNotIn(b"do-not-serve-this", body)
