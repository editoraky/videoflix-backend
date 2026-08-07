"""Views for the video endpoints."""

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework.generics import ListAPIView
from rest_framework.views import APIView

from video_app.models import Video

from .serializers import VideoSerializer
from .utils import build_hls_path

PLAYLIST_CONTENT_TYPE = 'application/vnd.apple.mpegurl'
SEGMENT_CONTENT_TYPE = 'video/MP2T'
SEGMENT_SUFFIX = '.ts'


def stream_hls_file(movie_id, resolution, filename, content_type):
    """Return the requested HLS file as a streamed response.

    Raises Http404 for an unknown video, a resolution outside the whitelist, a
    path that would leave the folder, and a file that does not exist — all of
    them indistinguishable from outside, so nothing about the layout leaks.
    """
    get_object_or_404(Video, pk=movie_id)
    target = build_hls_path(movie_id, resolution, filename)
    if target is None or not target.is_file():
        raise Http404
    return FileResponse(target.open('rb'), content_type=content_type)


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


class HlsPlaylistView(APIView):
    """The media playlist of one resolution.

    Authentication is not optional here: without a valid access cookie the
    answer is 401, because the manifest lists every segment of the film.

    Anything missing answers 404 — an unknown video, a resolution the player
    does not offer, or a conversion that has not run yet. None of these is a
    server error, and none of them may leak whether a directory exists.
    """

    def get(self, request, movie_id, resolution):
        """Stream index.m3u8 for the requested video and resolution."""
        return stream_hls_file(
            movie_id, resolution, 'index.m3u8', PLAYLIST_CONTENT_TYPE
        )


class HlsSegmentView(APIView):
    """One transport stream segment of a resolution.

    Guarded like the manifest: a segment is a piece of the film, and an open
    segment endpoint hands out the whole thing to anyone who can count.

    The file name arrives from the URL, so it never reaches the file system
    without passing build_hls_path first.
    """

    def get(self, request, movie_id, resolution, segment):
        """Stream a single .ts segment."""
        if not segment.endswith(SEGMENT_SUFFIX):
            raise Http404
        return stream_hls_file(movie_id, resolution, segment, SEGMENT_CONTENT_TYPE)
