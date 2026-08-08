"""Database models for the video library."""

from django.core.validators import FileExtensionValidator
from django.db import models


class ConversionStatus(models.TextChoices):
    """Lifecycle of an HLS conversion.

    The conversion runs in an RQ worker, so nothing that reads a video can
    assume its segments exist. Both the video as a whole and each single
    resolution carry this state.
    """

    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class Video(models.Model):
    """A film offered by the platform.

    The field names are dictated by GET /api/video/ and by the frontend, which
    reads id, title, description, category and created_at straight off the
    response (video_list.js:82, 94, 105, 106, 122, 201). There is deliberately
    no foreign key to a user: films are platform content, and the API knows no
    upload endpoint — videos arrive through the admin.

    The two file fields are stored apart on purpose. Thumbnails have to be
    reachable over plain HTTP, because the frontend uses thumbnail_url as an
    <img src> (video_list.js:199). The source file must not be: serving it
    would hand out the whole film in original quality without a login and make
    the authenticated HLS endpoints pointless. Keeping the two in separate
    subtrees means the public media route can cover thumbnails alone.

    hls_error holds an empty string rather than NULL, so "no error" has exactly
    one representation.

    The ordering is part of the contract. The checklist asks for creation date
    descending, and the frontend turns the first entry into its hero teaser.
    """

    title = models.CharField(max_length=100)
    description = models.TextField()
    category = models.CharField(max_length=50)

    video_file = models.FileField(
        upload_to="uploads/videos/",
        validators=[FileExtensionValidator(["mp4", "mov", "mkv"])],
    )
    thumbnail = models.ImageField(upload_to="thumbnails/", blank=True)

    hls_status = models.CharField(
        max_length=20,
        choices=ConversionStatus.choices,
        default=ConversionStatus.PENDING,
    )
    hls_error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="idx_videos_created_at"),
            models.Index(fields=["category"], name="idx_videos_category"),
        ]

    def __str__(self):
        return self.title


class VideoVariant(models.Model):
    """One converted resolution of a video.

    A single status on the video cannot express "720p is ready, 1080p is still
    running", but that is exactly what happens: the three conversions finish one
    after another, and each of them can fail on its own and be retried without
    discarding the others.

    The row also answers the question the streaming endpoints ask — does this
    manifest exist? — with a query instead of a look at the file system, which
    keeps those views testable without real segments on disk.

    One row per video and resolution is enforced in the database. A retried job
    has to update its row; a second one would leave the streaming view choosing
    between duplicates, one of them stale.
    """

    class Resolution(models.TextChoices):
        """The values the player's dropdown can request (index.html:76-78)."""

        SD = "480p", "480p"
        HD = "720p", "720p"
        FULL_HD = "1080p", "1080p"

    video = models.ForeignKey(
        Video, on_delete=models.CASCADE, related_name="variants"
    )
    resolution = models.CharField(max_length=10, choices=Resolution.choices)
    playlist_path = models.CharField(max_length=255, blank=True, default="")
    segment_count = models.PositiveIntegerField(default=0)

    status = models.CharField(
        max_length=20,
        choices=ConversionStatus.choices,
        default=ConversionStatus.PENDING,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["video", "resolution"],
                name="uq_variant_video_resolution",
            )
        ]

    def __str__(self):
        return f"{self.video.title} ({self.resolution})"
