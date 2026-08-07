"""Tests for build_hls_path — the barrier between a URL and the file system.

The URL patterns already reject slashes, so most attacks never reach this
function through routing. These tests hit it directly, because the segment
endpoint passes a file name straight from the URL and the guarantee has to hold
on its own rather than by grace of a regex somewhere else.
"""

import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from video_app.api.utils import build_hls_path

TEMPORARY_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEMPORARY_MEDIA_ROOT)
class BuildHlsPathTests(SimpleTestCase):
    """Anything that could leave the resolution directory returns None."""

    def test_a_valid_request_yields_a_path_inside_the_video_folder(self):
        path = build_hls_path(1, "480p", "index.m3u8")
        expected = Path(TEMPORARY_MEDIA_ROOT) / "videos" / "1" / "480p" / "index.m3u8"
        self.assertEqual(path, expected.resolve())

    def test_segment_names_are_accepted(self):
        self.assertIsNotNone(build_hls_path(1, "720p", "000.ts"))

    def test_an_unknown_resolution_is_refused(self):
        """240p is not in the player's dropdown, so no folder is derived from it."""
        self.assertIsNone(build_hls_path(1, "240p", "index.m3u8"))

    def test_a_resolution_of_dots_is_refused(self):
        self.assertIsNone(build_hls_path(1, "..", "index.m3u8"))

    def test_a_file_name_climbing_out_is_refused(self):
        """This is the attack the endpoint exists to survive: reaching .env."""
        self.assertIsNone(build_hls_path(1, "480p", "../../../../.env"))

    def test_an_absolute_file_name_is_refused(self):
        """Path("/a/b") / "/etc/passwd" discards the base and returns /etc/passwd."""
        self.assertIsNone(build_hls_path(1, "480p", "/etc/passwd"))

    def test_a_detour_that_stays_inside_is_allowed(self):
        """Normalisation, not pattern matching: the result is what counts."""
        path = build_hls_path(1, "480p", "sub/../000.ts")
        expected = Path(TEMPORARY_MEDIA_ROOT) / "videos" / "1" / "480p" / "000.ts"
        self.assertEqual(path, expected.resolve())
