"""Tests for the overall conversion state of a video.

Video.hls_status answers one question for the admin: is this film finished?
It is derived from the variants rather than set by hand, because three
conversions finish at three different moments and whoever writes last would
otherwise decide the answer.

"ready" deliberately requires all three resolutions. Declaring a video ready
while 1080p is missing would hide the failure behind a working 480p, and the
player offers all three in its dropdown either way.
"""

from django.test import TestCase

from video_app.models import ConversionStatus, Video, VideoVariant
from video_app.tasks import refresh_video_status

ALL_RESOLUTIONS = ('480p', '720p', '1080p')


class VideoStatusTests(TestCase):
    """Derivation rules, one per test."""

    def setUp(self):
        self.video = Video.objects.create(
            title="Heavy Rain",
            description="Water falls.",
            category="drama",
            video_file='uploads/videos/film.mp4',
        )

    def add_variants(self, *states):
        for resolution, status in zip(ALL_RESOLUTIONS, states, strict=False):
            VideoVariant.objects.create(
                video=self.video, resolution=resolution, status=status
            )

    def status_after_refresh(self):
        refresh_video_status(self.video)
        self.video.refresh_from_db()
        return self.video.hls_status

    def test_a_video_without_variants_is_still_pending(self):
        """Nothing has been queued yet, which is not the same as failing."""
        self.assertEqual(self.status_after_refresh(), ConversionStatus.PENDING)

    def test_all_renditions_ready_makes_the_video_ready(self):
        self.add_variants(*[ConversionStatus.READY] * 3)
        self.assertEqual(self.status_after_refresh(), ConversionStatus.READY)

    def test_a_running_rendition_keeps_the_video_processing(self):
        self.add_variants(
            ConversionStatus.READY, ConversionStatus.PROCESSING, ConversionStatus.PENDING
        )
        self.assertEqual(self.status_after_refresh(), ConversionStatus.PROCESSING)

    def test_all_renditions_failed_makes_the_video_failed(self):
        self.add_variants(*[ConversionStatus.FAILED] * 3)
        self.assertEqual(self.status_after_refresh(), ConversionStatus.FAILED)

    def test_a_single_failure_is_enough_to_fail_the_video(self):
        """Two working resolutions do not make a film complete."""
        self.add_variants(
            ConversionStatus.READY, ConversionStatus.READY, ConversionStatus.FAILED
        )
        self.assertEqual(self.status_after_refresh(), ConversionStatus.FAILED)

    def test_two_ready_renditions_are_not_yet_ready(self):
        """The third one has not been queued, so the film is not finished."""
        self.add_variants(ConversionStatus.READY, ConversionStatus.READY)
        self.assertEqual(self.status_after_refresh(), ConversionStatus.PROCESSING)
