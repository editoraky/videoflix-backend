"""Root URL configuration.

Only the thumbnail subtree of MEDIA_ROOT is published. The frontend loads
thumbnails as plain images and needs a public route for them, while the same
tree also holds the uploaded source files. Routing MEDIA_ROOT as a whole would
serve the complete film without a login and make the authenticated HLS
endpoints pointless.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('django-rq/', include('django_rq.urls')),
    path('api/', include('auth_app.api.urls')),
    path('api/', include('video_app.api.urls')),
    re_path(
        r'^media/thumbnails/(?P<path>.*)$',
        serve,
        {'document_root': settings.MEDIA_ROOT / 'thumbnails'},
    ),
]
