"""Views for the video endpoints."""

from rest_framework.generics import ListAPIView

from video_app.models import Video

from .serializers import VideoSerializer


class VideoListView(ListAPIView):
    """The whole catalogue as a flat array.

    Authentication comes from the project defaults: the cookie class reads the
    access token, and IsAuthenticated turns a missing one into 401.

    Pagination is switched off explicitly rather than left unconfigured. The
    frontend treats the response as an array and iterates it directly, so a
    paginated object would raise inside a catch block and surface as nothing
    more than "Failed to load videos". Should pagination ever be enabled
    project-wide, this endpoint has to stay unaffected.

    The queryset is unfiltered on purpose. Videos are platform content without
    an owner, and every activated member sees the same catalogue.
    """

    queryset = Video.objects.all()
    serializer_class = VideoSerializer
    pagination_class = None
