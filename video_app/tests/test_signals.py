"""Tests for enqueuing the conversion.

Two properties are load-bearing and both are invisible in a browser.

The job must not start before the transaction commits. RQ picks work up within
milliseconds, and a worker that queries a row the database has not written yet
finds nothing — the conversion silently never happens.

Enqueuing must be tied to creation. The jobs write back to the video, and a
signal that fired on every save would enqueue new work for every write, forever.
"""

from unittest.mock import patch

from django.test import TestCase

from video_app.models import Video, VideoVariant


def create_video(title="Heavy Rain"):
    return Video.objects.create(
        title=title,
        description="Water falls.",
        category="drama",
        video_file='uploads/videos/film.mp4',
    )


class EnqueueOnCreateTests(TestCase):
    """What lands in the queue when an admin saves a new video."""

    def test_nothing_is_enqueued_before_the_transaction_commits(self):
        """Without on_commit the worker would look for a row that is not there yet."""
        with patch('video_app.signals.get_queue') as get_queue:
            create_video()
            get_queue.return_value.enqueue.assert_not_called()

    def test_every_resolution_is_enqueued_after_the_commit(self):
        with patch('video_app.signals.get_queue') as get_queue:
            with self.captureOnCommitCallbacks(execute=True):
                video = create_video()
            enqueued = get_queue.return_value.enqueue.call_args_list
        resolutions = [call.args[2] for call in enqueued if len(call.args) > 2]
        self.assertEqual(resolutions, list(VideoVariant.Resolution.values))
        self.assertTrue(all(call.args[1] == video.pk for call in enqueued))

    def test_the_thumbnail_is_enqueued_as_well(self):
        with patch('video_app.signals.get_queue') as get_queue:
            with self.captureOnCommitCallbacks(execute=True):
                create_video()
            enqueued = get_queue.return_value.enqueue.call_args_list
        job_names = [call.args[0].__name__ for call in enqueued]
        self.assertIn('generate_video_thumbnail', job_names)

    def test_four_jobs_in_total(self):
        """Three renditions and one still — no duplicates, nothing missing."""
        with patch('video_app.signals.get_queue') as get_queue:
            with self.captureOnCommitCallbacks(execute=True):
                create_video()
            self.assertEqual(get_queue.return_value.enqueue.call_count, 4)


class NoEnqueueOnUpdateTests(TestCase):
    """Saving an existing video must stay quiet."""

    def test_updating_a_video_enqueues_nothing(self):
        """The jobs themselves save the video; re-enqueuing would never terminate."""
        with self.captureOnCommitCallbacks(execute=True):
            video = create_video()
        with patch('video_app.signals.get_queue') as get_queue:
            with self.captureOnCommitCallbacks(execute=True):
                video.title = "Renamed"
                video.save()
            get_queue.return_value.enqueue.assert_not_called()
