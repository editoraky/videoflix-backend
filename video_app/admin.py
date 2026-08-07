"""Admin configuration for the video library."""

from django.contrib import admin

from .models import Video, VideoVariant


class VideoVariantInline(admin.TabularInline):
    """The conversions of a video, shown for reading only.

    Variants are written by the worker, never by hand. An entry typed here
    would claim that segments exist which FFMPEG has not produced, and the
    streaming endpoint has no way to notice the difference.
    """

    model = VideoVariant
    extra = 0
    can_delete = False
    fields = ("resolution", "status", "segment_count", "playlist_path")
    readonly_fields = fields

    def has_add_permission(self, request, obj):
        return False


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    """The only way a film enters the platform.

    The API documentation lists three GET endpoints for video and no upload, so
    everything this form cannot do is simply impossible.

    hls_status and hls_error belong to the conversion pipeline and are read-only
    here for the same reason the variants are: a value set by hand would be
    believed by the streaming endpoints.
    """

    list_display = ("title", "category", "hls_status", "created_at")
    list_filter = ("category", "hls_status")
    search_fields = ("title", "description")
    readonly_fields = ("hls_status", "hls_error", "created_at", "updated_at")
    inlines = (VideoVariantInline,)
