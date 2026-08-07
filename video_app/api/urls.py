"""URL routes for the video endpoints.

config.js builds every request as API_BASE_URL + a relative path, so "video/"
has to resolve to /api/video/.
"""

from django.urls import path

from .views import HlsPlaylistView, HlsSegmentView, VideoListView

urlpatterns = [
    path('video/', VideoListView.as_view(), name='video-list'),
    # No trailing slash: the last part is a file name, and config.js:68 builds
    # exactly this path.
    path(
        'video/<int:movie_id>/<str:resolution>/index.m3u8',
        HlsPlaylistView.as_view(),
        name='hls-playlist',
    ),
    # Both spellings are routed. The documentation ends the segment path with a
    # slash, while a player resolves "000.ts" against the manifest URL and asks
    # without one. Relying on APPEND_SLASH would put a 301 in front of every
    # single segment.
    path(
        'video/<int:movie_id>/<str:resolution>/<str:segment>',
        HlsSegmentView.as_view(),
        name='hls-segment',
    ),
    path(
        'video/<int:movie_id>/<str:resolution>/<str:segment>/',
        HlsSegmentView.as_view(),
        name='hls-segment-slash',
    ),
]
