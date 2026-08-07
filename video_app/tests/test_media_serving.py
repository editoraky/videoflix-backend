"""Tests for serving media files.

The frontend needs the thumbnail over plain HTTP, because it assigns
thumbnail_url to an <img src> (video_list.js:199). The uploaded source file
must stay unreachable: it is the complete film in original quality, and a
direct link to it would render the guarded HLS endpoints pointless.

Routing MEDIA_ROOT as a whole would serve both. These tests exist to keep the
two apart.
"""

from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import Resolver404, resolve

# A name unlikely to collide with anything an admin uploaded by hand.
PROBE_IMAGE = "test_probe_thumbnail.txt"
PROBE_SOURCE = "test_probe_source.txt"


def write_probe(subdirectory, filename):
    """Place a file below MEDIA_ROOT and return its path."""
    directory = Path(settings.MEDIA_ROOT) / subdirectory
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / filename
    probe.write_bytes(b"probe")
    return probe


class MediaRoutingTests(TestCase):
    """Which paths resolve at all — provable without any file on disk."""

    def test_thumbnail_path_resolves(self):
        self.assertTrue(callable(resolve("/media/thumbnails/a.jpg").func))

    def test_source_file_path_does_not_resolve(self):
        """No route means no handler, whatever the file system contains."""
        with self.assertRaises(Resolver404):
            resolve("/media/uploads/videos/a.mp4")

    def test_media_root_itself_does_not_resolve(self):
        """Only the thumbnails subtree is public, never MEDIA_ROOT as a whole."""
        with self.assertRaises(Resolver404):
            resolve("/media/a.jpg")


class MediaDeliveryTests(TestCase):
    """What actually comes back, using real files below the real MEDIA_ROOT.

    MEDIA_ROOT cannot be overridden here: the document root is bound when the
    URLconf is imported, so a patched setting would not reach the view.
    """

    def setUp(self):
        self.image = write_probe("thumbnails", PROBE_IMAGE)
        self.source = write_probe("uploads/videos", PROBE_SOURCE)

    def tearDown(self):
        self.image.unlink(missing_ok=True)
        self.source.unlink(missing_ok=True)

    def test_thumbnail_is_delivered(self):
        response = self.client.get(f"/media/thumbnails/{PROBE_IMAGE}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"probe")

    def test_source_file_is_not_delivered(self):
        """The file exists — only the missing route keeps it private."""
        self.assertTrue(self.source.exists())
        response = self.client.get(f"/media/uploads/videos/{PROBE_SOURCE}")
        self.assertEqual(response.status_code, 404)

    def test_traversal_out_of_the_thumbnail_folder_fails(self):
        """A relative hop is the obvious way around a subtree restriction."""
        response = self.client.get(
            f"/media/thumbnails/../uploads/videos/{PROBE_SOURCE}"
        )
        self.assertNotEqual(response.status_code, 200)

    def test_encoded_traversal_fails_as_well(self):
        """Django decodes the path before routing, so %2E%2E%2F becomes ../."""
        response = self.client.get(
            f"/media/thumbnails/%2E%2E%2Fuploads%2Fvideos%2F{PROBE_SOURCE}"
        )
        self.assertNotEqual(response.status_code, 200)
