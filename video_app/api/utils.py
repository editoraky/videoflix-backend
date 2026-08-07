"""Helpers for the HLS endpoints."""

from pathlib import Path

from django.conf import settings

from video_app.models import VideoVariant


def build_hls_path(video_id, resolution, filename):
    """Return the path of an HLS file, or None if the request tries to escape.

    Two of the three parts come from the URL, so the result is never trusted on
    the strength of the URL pattern alone. MEDIA_ROOT lives inside /app, one
    directory below .env — a path that leaves the video folder reaches
    SECRET_KEY, the database password and the SMTP login.

    Two independent barriers: the resolution has to be one the player actually
    offers, and the resolved path has to stay inside its own directory. The
    second one also covers symlinks and encodings the first cannot foresee.
    """
    if resolution not in VideoVariant.Resolution.values:
        return None
    base = Path(settings.MEDIA_ROOT) / "videos" / str(video_id) / resolution
    base = base.resolve()
    target = (base / filename).resolve()
    if not target.is_relative_to(base):
        return None
    return target
