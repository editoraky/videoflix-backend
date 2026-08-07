"""Serializers for the video endpoints."""

from rest_framework import serializers

from video_app.models import Video


class VideoSerializer(serializers.ModelSerializer):
    """The payload of GET /api/video/.

    Every field is listed by name. The upload path and the conversion state stay
    out: the source file is the complete film, and a direct link to it would
    hand out what the guarded HLS endpoints exist to protect.
    """

    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Video
        fields = (
            "id",
            "created_at",
            "title",
            "description",
            "thumbnail_url",
            "category",
        )

    def get_thumbnail_url(self, video):
        """Return an absolute URL, or None while no image has been extracted.

        The frontend assigns the value to an <img src> without touching it, so a
        relative path would be resolved against the frontend's own origin.
        """
        if not video.thumbnail:
            return None
        return self.context["request"].build_absolute_uri(video.thumbnail.url)
