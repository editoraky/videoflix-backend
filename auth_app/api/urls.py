"""URL routes for the authentication endpoints.

The paths are dictated by the frontend: config.js builds every request as
API_BASE_URL + a relative path, so "register/" has to resolve to /api/register/.
"""

from django.urls import path

from .views import ActivationView, LoginView, RegistrationView

urlpatterns = [
    path('register/', RegistrationView.as_view(), name='register'),
    path('activate/<str:uidb64>/<str:token>/', ActivationView.as_view(), name='activate'),
    path('login/', LoginView.as_view(), name='login'),
]
