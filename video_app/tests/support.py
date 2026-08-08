"""Shared building blocks for the video tests.

CONTRACT_FIELDS is written out by hand rather than derived from the serializer.
Deriving it would make the test agree with whatever the code happens to do; the
point is to state independently what GET /api/video/ has to return, so that a
changed field list fails a test instead of quietly changing the API.
"""

from video_app.models import Video

CONTRACT_FIELDS = {
    "id",
    "created_at",
    "title",
    "description",
    "thumbnail_url",
    "category",
}


def create_video(title="A Film", category="drama", **extra):
    """Create a video without touching the file system.

    Assigning a plain string to a FileField stores the path only. Uploading a
    real file would write into the media volume and leave test residue behind;
    the tests that need actual files build them in their own temporary root.
    """
    return Video.objects.create(
        title=title,
        description="Some description.",
        category=category,
        video_file="uploads/videos/film.mp4",
        **extra,
    )
