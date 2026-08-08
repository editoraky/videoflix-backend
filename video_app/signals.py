"""Signals that connect the admin to the conversion pipeline.

Videos arrive through the admin only, so saving one there is the single moment
at which work has to be scheduled.
"""

import shutil

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django_rq import get_queue

from .models import Video, VideoVariant
from .services import video_directory
from .tasks import convert_video_to_hls, generate_video_thumbnail


@receiver(post_save, sender=Video)
def enqueue_conversion(sender, instance, created, **kwargs):
    """Schedule the conversion of a newly uploaded video.

    Only on creation. The jobs write their results back to this very model, so
    reacting to every save would enqueue fresh work for every write and never
    come to rest.

    transaction.on_commit is not a nicety: RQ hands the job to a worker within
    milliseconds, and inside an open transaction that worker would query a row
    the database has not committed yet and find nothing at all.
    """
    if not created:
        return
    transaction.on_commit(lambda: schedule_jobs(instance.pk))


def schedule_jobs(video_id):
    """Put one job per resolution plus the thumbnail into the default queue."""
    queue = get_queue('default')
    for resolution in VideoVariant.Resolution.values:
        queue.enqueue(convert_video_to_hls, video_id, resolution)
    queue.enqueue(generate_video_thumbnail, video_id)


@receiver(post_delete, sender=Video)
def remove_video_files(sender, instance, **kwargs):
    """Delete everything the video owned on disk.

    Django has not removed files behind a FileField since 1.3, so a deleted
    video would otherwise leave a source file and three renditions behind — on
    the same volume that carries the database.

    The primary key is still set at this point; the collector clears it only
    after the signal has run.
    """
    remove_rendition_folder(instance.pk)
    remove_stored_file(instance.video_file)
    remove_stored_file(instance.thumbnail)


def remove_rendition_folder(video_id):
    """Drop the folder holding every rendition of one video.

    The identifier comes from the database and is an integer, so the path
    cannot be steered from outside. The guard covers the one case that would
    matter: an empty id turning the path into the folder that holds all videos.
    """
    if not video_id:
        return
    shutil.rmtree(video_directory(video_id), ignore_errors=True)


def remove_stored_file(field):
    """Delete the file behind a file field, keeping the row untouched."""
    if field:
        field.delete(save=False)
