"""Tests for the conversion services.

Two of these tests run FFMPEG for real. That is deliberate: a mocked call
proves that some list was passed somewhere, but not that the flags are spelled
correctly or that the segments end up under the documented names. A typo in
"-hls_segment_filename" would pass every mock and fail in production.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from video_app.services import (
    ConversionError,
    build_hls_command,
    convert_to_hls,
    extract_thumbnail,
)


def make_test_clip(directory, name="source.mp4", seconds=2):
    """Generate a tiny clip with FFMPEG's own test pattern.

    Keeps a binary fixture out of the repository and stays independent of the
    sample videos, which live outside the project folder.
    """
    path = Path(directory) / name
    subprocess.run(
        [
            'ffmpeg', '-y', '-loglevel', 'error',
            '-f', 'lavfi', '-i', f'testsrc=duration={seconds}:size=320x240:rate=10',
            '-pix_fmt', 'yuv420p', str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


class HlsCommandTests(SimpleTestCase):
    """The command is assembled as data, never as a shell string."""

    def setUp(self):
        self.command = build_hls_command('/media/in.mp4', Path('/media/out'), 480)

    def test_command_is_a_list_of_arguments(self):
        """A string would be handed to a shell, and the file name comes from an upload."""
        self.assertIsInstance(self.command, list)

    def test_source_is_a_single_argument(self):
        """Splitting on spaces would break every path that contains one."""
        self.assertIn('/media/in.mp4', self.command)

    def test_segments_follow_the_documented_naming(self):
        """The API documentation addresses segments as 000.ts, 001.ts and so on."""
        index = self.command.index('-hls_segment_filename')
        self.assertTrue(self.command[index + 1].endswith('%03d.ts'))

    def test_output_is_named_index_m3u8(self):
        """The endpoint looks for exactly this name, not output.m3u8."""
        self.assertTrue(self.command[-1].endswith('index.m3u8'))

    def test_height_reaches_the_scale_filter(self):
        """scale=-2:<height> keeps the width even, which H.264 requires."""
        self.assertIn('scale=-2:480', self.command)

    def test_key_frames_are_forced(self):
        """Without this, FFMPEG cuts wherever the source happens to have a keyframe.

        Segment length would then be a property of the uploaded file rather than
        a setting, and EXT-X-TARGETDURATION would differ per video.
        """
        self.assertTrue(any('force_key_frames' in part for part in self.command))


class ShellSafetyTests(SimpleTestCase):
    """The single most dangerous mistake this module could make."""

    @patch('video_app.services.subprocess.run')
    def test_ffmpeg_never_runs_through_a_shell(self, run):
        """shell=True plus an upload-derived file name is remote code execution."""
        run.return_value = subprocess.CompletedProcess([], returncode=0, stderr='')
        convert_to_hls('/media/in.mp4', Path('/media/out'), 480)
        self.assertNotIn('shell', run.call_args.kwargs)

    @patch('video_app.services.subprocess.run')
    def test_ffmpeg_runs_with_a_timeout(self, run):
        """A stalled process would otherwise hold the worker until RQ kills it."""
        run.return_value = subprocess.CompletedProcess([], returncode=0, stderr='')
        convert_to_hls('/media/in.mp4', Path('/media/out'), 480)
        self.assertIn('timeout', run.call_args.kwargs)


class ConversionTests(SimpleTestCase):
    """Real runs against a generated clip."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workspace = tempfile.mkdtemp()
        cls.source = make_test_clip(cls.workspace)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.workspace, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.destination = Path(tempfile.mkdtemp(dir=self.workspace))

    def test_conversion_writes_a_playlist(self):
        convert_to_hls(self.source, self.destination, 240)
        self.assertTrue((self.destination / 'index.m3u8').is_file())

    def test_conversion_writes_segments_starting_at_zero(self):
        convert_to_hls(self.source, self.destination, 240)
        self.assertTrue((self.destination / '000.ts').is_file())

    def test_a_broken_source_raises_a_conversion_error(self):
        """The worker has to be able to record a reason, not just a crash."""
        broken = Path(self.workspace) / 'broken.mp4'
        broken.write_bytes(b'this is not a video')
        with self.assertRaises(ConversionError):
            convert_to_hls(broken, self.destination, 240)

    def test_the_error_carries_the_ffmpeg_message(self):
        broken = Path(self.workspace) / 'broken2.mp4'
        broken.write_bytes(b'this is not a video')
        with self.assertRaises(ConversionError) as caught:
            convert_to_hls(broken, self.destination, 240)
        self.assertTrue(str(caught.exception).strip())

    @patch('video_app.services.subprocess.run')
    def test_a_long_error_is_truncated(self, run):
        """FFMPEG can be verbose, and the text goes into a database column."""
        run.return_value = subprocess.CompletedProcess(
            [], returncode=1, stderr='x' * 10000
        )
        with self.assertRaises(ConversionError) as caught:
            convert_to_hls('/media/in.mp4', Path('/media/out'), 480)
        self.assertLess(len(str(caught.exception)), 3000)

    @patch('video_app.services.subprocess.run')
    def test_a_stalled_process_becomes_a_conversion_error(self, run):
        """Callers should handle one failure type, not two."""
        run.side_effect = subprocess.TimeoutExpired(cmd='ffmpeg', timeout=1)
        with self.assertRaises(ConversionError):
            convert_to_hls('/media/in.mp4', Path('/media/out'), 480)


class ThumbnailTests(SimpleTestCase):
    """The dashboard shows a still for every film (video_list.js:199)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.workspace = tempfile.mkdtemp()
        cls.source = make_test_clip(cls.workspace, name="thumb_source.mp4")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.workspace, ignore_errors=True)
        super().tearDownClass()

    def test_a_still_is_written(self):
        target = Path(self.workspace) / 'still.jpg'
        extract_thumbnail(self.source, target)
        self.assertTrue(target.is_file())

    def test_the_still_is_a_readable_image(self):
        """ImageField runs the file through Pillow, so a stray byte stream fails there."""
        from PIL import Image

        target = Path(self.workspace) / 'readable.jpg'
        extract_thumbnail(self.source, target)
        with Image.open(target) as image:
            image.verify()

    def test_a_broken_source_raises_a_conversion_error(self):
        broken = Path(self.workspace) / 'broken_thumb.mp4'
        broken.write_bytes(b'this is not a video')
        with self.assertRaises(ConversionError):
            extract_thumbnail(broken, Path(self.workspace) / 'never.jpg')

    @patch('video_app.services.subprocess.run')
    def test_a_silent_failure_is_reported(self, run):
        """FFMPEG can exit 0 without writing a frame; an empty file is not a still."""
        run.return_value = subprocess.CompletedProcess([], returncode=0, stderr='')
        with self.assertRaises(ConversionError):
            extract_thumbnail(self.source, Path(self.workspace) / 'missing.jpg')
