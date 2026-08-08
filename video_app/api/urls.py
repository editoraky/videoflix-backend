"""URL routes for the video endpoints.

config.js builds every request as API_BASE_URL + a relative path, so "video/"
has to resolve to /api/video/. The playlist and segment paths end in a file
name and therefore carry no trailing slash.

The segment path is registered in both spellings. The API documentation writes
it with a trailing slash, while a player resolves "000.ts" against the manifest
URL and asks without one. Leaving that to APPEND_SLASH would put a 301 in front
of every single segment.
"""

from django.urls import path

from .views import HlsPlaylistView, HlsSegmentView, VideoListView

urlpatterns = [
    path('video/', VideoListView.as_view(), name='video-list'),
    path(
        'video/<int:movie_id>/<str:resolution>/index.m3u8',
        HlsPlaylistView.as_view(),
        name='hls-playlist',
    ),
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
