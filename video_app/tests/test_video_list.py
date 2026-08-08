"""Tests for GET /api/video/.

Two properties of this endpoint are invisible in a browser until the dashboard
stays empty: the response has to be a plain array, and it has to be ordered
newest first. loadAndSetupVideos catches every exception and only reports
"Failed to load videos", so a paginated object would look like a network
problem rather than a shape mismatch.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from video_app.models import Video
from video_app.tests.support import CONTRACT_FIELDS, create_video

User = get_user_model()


class VideoListAuthenticationTests(APITestCase):
    """The catalogue is for members; the documentation lists 401 for this path."""

    def setUp(self):
        self.url = reverse("video-list")
        create_video()

    def test_request_without_a_cookie_is_rejected(self):
        """401, not 403 — the frontend refreshes on 401 and gives up on 403."""
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_request_with_a_valid_cookie_is_accepted(self):
        user = User.objects.create_user(
            username="viewer@example.com",
            email="viewer@example.com",
            password="secret123",
        )
        access = RefreshToken.for_user(user).access_token
        self.client.cookies[settings.AUTH_COOKIE_ACCESS] = str(access)
        self.assertEqual(self.client.get(self.url).status_code, 200)


class VideoListPayloadTests(APITestCase):
    """Shape and order are both read directly by video_list.js."""

    def setUp(self):
        self.url = reverse("video-list")
        user = User.objects.create_user(
            username="viewer@example.com",
            email="viewer@example.com",
            password="secret123",
        )
        access = RefreshToken.for_user(user).access_token
        self.client.cookies[settings.AUTH_COOKIE_ACCESS] = str(access)

    def test_response_is_a_plain_array(self):
        """Pagination would wrap the list in an object and break VIDEOS.forEach."""
        create_video()
        self.assertIsInstance(self.client.get(self.url).json(), list)

    def test_each_entry_carries_the_contract_fields(self):
        create_video(thumbnail="thumbnails/film.jpg")
        self.assertEqual(set(self.client.get(self.url).json()[0]), CONTRACT_FIELDS)

    def test_thumbnail_url_is_absolute(self):
        """The view has to pass the request into the serializer context."""
        create_video(thumbnail="thumbnails/film.jpg")
        thumbnail_url = self.client.get(self.url).json()[0]["thumbnail_url"]
        self.assertTrue(thumbnail_url.startswith("http://"))

    def test_newest_video_comes_first(self):
        """VIDEOS[0] becomes the hero teaser (video_list.js:104-107)."""
        now = timezone.now()
        for title, age_in_days in (("Oldest", 3), ("Middle", 2), ("Newest", 1)):
            video = create_video(title=title)
            Video.objects.filter(pk=video.pk).update(
                created_at=now - timedelta(days=age_in_days)
            )
        titles = [entry["title"] for entry in self.client.get(self.url).json()]
        self.assertEqual(titles, ["Newest", "Middle", "Oldest"])

    def test_an_empty_catalogue_returns_an_empty_array(self):
        """No video is not an error; the frontend decides what to show."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
