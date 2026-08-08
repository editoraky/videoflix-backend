"""Conversion of an uploaded video into HLS renditions.

Everything here runs inside the RQ worker, never inside a request. FFMPEG needs
seconds to minutes per rendition, and a browser would time out long before it
finished.
"""

import subprocess
from pathlib import Path

from django.conf import settings

FFMPEG_TIMEOUT_SECONDS = 600
SEGMENT_DURATION_SECONDS = 4
ERROR_TEXT_LIMIT = 2000

PLAYLIST_NAME = 'index.m3u8'
SEGMENT_PATTERN = '%03d.ts'

THUMBNAIL_OFFSET_SECONDS = 1
THUMBNAIL_HEIGHT = 360


class ConversionError(Exception):
    """FFMPEG could not produce a rendition.

    Carries the message FFMPEG printed, so the admin sees why a video stayed
    unplayable instead of only that it did.
    """


def video_directory(video_id):
    """Where every rendition of one video lives."""
    return Path(settings.MEDIA_ROOT) / 'videos' / str(video_id)


def hls_directory(video_id, resolution):
    """Where the renditions of one resolution live.

    The single definition of that layout. The conversion writes here and the
    streaming endpoints read from here — two spellings of the same path would
    only surface when a video refuses to play.
    """
    return video_directory(video_id) / resolution


def resolution_height(resolution):
    """Turn "720p" into the pixel height FFMPEG scales to."""
    return int(resolution.removesuffix('p'))


def build_hls_command(source, destination, height):
    """Assemble the FFMPEG call for one resolution.

    A list, never a string: the source name is derived from an upload, and a
    shell would treat characters in it as syntax.

    force_key_frames is not in the reference command but has to be here. FFMPEG
    only cuts segments at key frames, so without it the segment length is a
    property of the uploaded file rather than of this setting.
    """
    interval = SEGMENT_DURATION_SECONDS
    return [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-i', str(source),
        '-vf', f'scale=-2:{height}',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k',
        '-force_key_frames', f'expr:gte(t,n_forced*{interval})',
        '-start_number', '0',
        '-hls_time', str(interval),
        '-hls_list_size', '0',
        '-f', 'hls',
        '-hls_segment_filename', str(Path(destination) / SEGMENT_PATTERN),
        str(Path(destination) / PLAYLIST_NAME),
    ]


def convert_to_hls(source, destination, height):
    """Produce the playlist and segments of one resolution below destination.

    Raises ConversionError for anything that went wrong, so the caller has a
    single failure type to record.
    """
    Path(destination).mkdir(parents=True, exist_ok=True)
    command = build_hls_command(source, destination, height)
    result = run_ffmpeg(command)
    if result.returncode != 0:
        raise ConversionError(shorten(result.stderr))


def extract_thumbnail(source, destination):
    """Write a single still frame to destination.

    Taken a second in rather than at zero: many films open on black, and a black
    tile in the dashboard looks like a broken image.

    FFMPEG can exit successfully without writing a frame, for instance when the
    offset lies past the end of a very short clip. The file is therefore checked
    instead of the return code alone.
    """
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    command = build_thumbnail_command(source, destination)
    result = run_ffmpeg(command)
    if result.returncode != 0:
        raise ConversionError(shorten(result.stderr))
    if not Path(destination).is_file():
        raise ConversionError('FFMPEG produced no thumbnail')


def build_thumbnail_command(source, destination):
    """Assemble the FFMPEG call for a single still frame."""
    return [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-ss', str(THUMBNAIL_OFFSET_SECONDS),
        '-i', str(source),
        '-frames:v', '1',
        '-vf', f'scale=-2:{THUMBNAIL_HEIGHT}',
        str(destination),
    ]


def run_ffmpeg(command):
    """Execute FFMPEG and return the completed process.

    A stalled process would hold the worker until RQ kills it, which loses the
    reason. The timeout turns that into an ordinary failure instead.
    """
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as expired:
        raise ConversionError(f'FFMPEG timed out after {expired.timeout} seconds')


def shorten(message):
    """Cut an FFMPEG message down to what a database column should hold."""
    return (message or '').strip()[:ERROR_TEXT_LIMIT]
