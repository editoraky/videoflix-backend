"""Tests for removing files when a video is deleted.

Django stopped deleting files behind FileFields in 1.3, so nothing goes away on
its own. A 30 MB source plus three renditions per video adds up quickly, and the
media volume is the same one the database lives next to.

The test that matters most is the last one: deleting video 1 must not touch
video 12. A path built by string concatenation makes that mistake easy and the
consequence unrecoverable.
"""

import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from video_app.models import Video
from video_app.signals import remove_rendition_folder

TEMPORARY_MEDIA_ROOT = tempfile.mkdtemp()


def place_file(relative_path, content=b'data'):
    """Create a file below the temporary media root."""
    target = Path(TEMPORARY_MEDIA_ROOT) / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


@override_settings(MEDIA_ROOT=TEMPORARY_MEDIA_ROOT)
class DeletionCleanupTests(TestCase):
    """Everything a video owns disappears with it — and nothing else does."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMPORARY_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def make_video(self, title="Heavy Rain"):
        video = Video.objects.create(
            title=title,
            description="Water falls.",
            category="drama",
            video_file='uploads/videos/film.mp4',
        )
        place_file(f'uploads/videos/film_{video.pk}.mp4')
        video.video_file.name = f'uploads/videos/film_{video.pk}.mp4'
        place_file(f'thumbnails/still_{video.pk}.jpg')
        video.thumbnail.name = f'thumbnails/still_{video.pk}.jpg'
        video.save()
        place_file(f'videos/{video.pk}/480p/index.m3u8')
        place_file(f'videos/{video.pk}/480p/000.ts')
        return video

    def test_the_rendition_folder_is_removed(self):
        video = self.make_video()
        folder = Path(TEMPORARY_MEDIA_ROOT) / 'videos' / str(video.pk)
        video.delete()
        self.assertFalse(folder.exists())

    def test_the_source_file_is_removed(self):
        video = self.make_video()
        source = Path(TEMPORARY_MEDIA_ROOT) / video.video_file.name
        video.delete()
        self.assertFalse(source.exists())

    def test_the_thumbnail_is_removed(self):
        video = self.make_video()
        thumbnail = Path(TEMPORARY_MEDIA_ROOT) / video.thumbnail.name
        video.delete()
        self.assertFalse(thumbnail.exists())

    def test_deleting_a_video_without_files_does_not_raise(self):
        """A video may be removed before the conversion ever ran."""
        video = Video.objects.create(
            title="Never Converted",
            description="Water falls.",
            category="drama",
            video_file='uploads/videos/absent.mp4',
        )
        video.delete()

    def test_another_video_keeps_its_files(self):
        """videos/1 and videos/12 share a prefix; only one of them may go."""
        first = self.make_video("First")
        second = self.make_video("Second")
        survivor = Path(TEMPORARY_MEDIA_ROOT) / 'videos' / str(second.pk) / '480p'
        first.delete()
        self.assertTrue((survivor / 'index.m3u8').is_file())
        self.assertTrue(Path(TEMPORARY_MEDIA_ROOT, second.video_file.name).is_file())

    def test_an_empty_identifier_deletes_nothing(self):
        """Without the guard the path would collapse onto the folder of all videos.

        The identifier comes from the database and is never empty in practice,
        which is precisely why the safeguard needs a test of its own — nothing
        else would ever exercise it.
        """
        self.make_video("Bystander")
        all_videos = Path(TEMPORARY_MEDIA_ROOT) / 'videos'
        for empty in (None, '', 0):
            with self.subTest(video_id=empty):
                remove_rendition_folder(empty)
                self.assertTrue(all_videos.is_dir())
