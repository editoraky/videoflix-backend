"""Background jobs for the conversion pipeline.

One job per resolution, not one job for all three. FFMPEG needs minutes for a
1080p rendition and RQ_QUEUES.DEFAULT_TIMEOUT is 900 seconds, so three runs in
a row could be cut off halfway. Separate jobs also mean a single resolution can
fail and be retried without discarding the two that worked.
"""

import logging
import tempfile
from pathlib import Path

from django.core.files import File

from .models import ConversionStatus, Video, VideoVariant
from .services import extract_thumbnail

OPEN_STATES = (ConversionStatus.PENDING, ConversionStatus.PROCESSING)

logger = logging.getLogger(__name__)
from .services import (
    ConversionError,
    convert_to_hls,
    hls_directory,
    resolution_height,
)

THUMBNAIL_SUFFIX = '.jpg'


def convert_video_to_hls(video_id, resolution):
    """Produce one rendition and record how it went.

    Never raises. A traceback in the worker log would leave the variant stuck on
    "processing" with no reason attached, and the admin would see a video that
    is neither ready nor failed.
    """
    video = Video.objects.filter(pk=video_id).first()
    if video is None:
        return
    variant = start_variant(video, resolution)
    destination = hls_directory(video_id, resolution)
    try:
        convert_to_hls(
            video.video_file.path, destination, resolution_height(resolution)
        )
    except ConversionError as error:
        mark_variant_failed(video, variant, resolution, str(error))
    else:
        mark_variant_ready(variant, video_id, resolution, destination)
    refresh_video_status(video)


def generate_video_thumbnail(video_id):
    """Grab a still from the film, unless somebody already supplied one.

    An uploaded image is a deliberate choice and is never overwritten.

    A failure here is cosmetic: the dashboard shows a broken tile, the film
    still plays. The job therefore logs and returns instead of failing, which
    would otherwise take a whole conversion down with it.
    """
    video = Video.objects.filter(pk=video_id).first()
    if video is None or video.thumbnail:
        return
    with tempfile.TemporaryDirectory() as workspace:
        still = Path(workspace) / f'{video_id}{THUMBNAIL_SUFFIX}'
        try:
            extract_thumbnail(video.video_file.path, still)
        except ConversionError as error:
            logger.warning('No thumbnail for video %s: %s', video_id, error)
            return
        store_thumbnail(video, still)


def store_thumbnail(video, still):
    """Hand the file to Django so it lands under the configured upload path."""
    with still.open('rb') as handle:
        video.thumbnail.save(still.name, File(handle), save=True)


def start_variant(video, resolution):
    """Create or reset the row for this resolution and mark it as running."""
    variant, _ = VideoVariant.objects.update_or_create(
        video=video,
        resolution=resolution,
        defaults={'status': ConversionStatus.PROCESSING},
    )
    return variant


def mark_variant_ready(variant, video_id, resolution, destination):
    """Record the finished rendition, including where its playlist ended up."""
    variant.status = ConversionStatus.READY
    variant.segment_count = count_segments(destination)
    variant.playlist_path = f'videos/{video_id}/{resolution}/index.m3u8'
    variant.save()


def mark_variant_failed(video, variant, resolution, reason):
    """Record the failure on the variant and its reason on the video.

    The variant carries no error column, so the text goes to the video and names
    the resolution — otherwise three renditions would overwrite each other's
    reason without a hint which one is being described.
    """
    variant.status = ConversionStatus.FAILED
    variant.save()
    video.hls_error = f'{resolution}: {reason}'
    video.save(update_fields=['hls_error'])


def count_segments(destination):
    """How many transport stream files the conversion produced."""
    return len(list(Path(destination).glob('*.ts')))


def refresh_video_status(video):
    """Derive the overall state of a video from its renditions.

    Ready requires all of them. A film whose 1080p run failed is not finished,
    and reporting it as ready would hide that behind a working 480p while the
    player keeps offering the resolution that answers 404.
    """
    states = list(video.variants.values_list('status', flat=True))
    video.hls_status = derive_status(states)
    video.save(update_fields=['hls_status'])


def derive_status(states):
    """Fold the variant states into a single answer."""
    if not states:
        return ConversionStatus.PENDING
    if len(states) < len(VideoVariant.Resolution.values):
        return ConversionStatus.PROCESSING
    if any(state in OPEN_STATES for state in states):
        return ConversionStatus.PROCESSING
    if all(state == ConversionStatus.READY for state in states):
        return ConversionStatus.READY
    return ConversionStatus.FAILED
