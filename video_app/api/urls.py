"""URL routes for the video endpoints.

config.js builds every request as API_BASE_URL + a relative path, so "video/"
has to resolve to /api/video/.
"""

from django.urls import path

from .views import VideoListView

urlpatterns = [
    path('video/', VideoListView.as_view(), name='video-list'),
]
