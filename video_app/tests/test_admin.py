"""Tests for the video admin.

The admin is not a convenience here, it is the only way a film enters the
system: the API documentation lists three GET endpoints for video and no
upload at all. Whatever the admin cannot do, nobody can do.

Uploads are written to disk, so these tests run against their own media root
rather than leaving files behind in the volume that serves the application.
"""

import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from video_app.models import Video, VideoVariant

User = get_user_model()

TEMPORARY_MEDIA_ROOT = tempfile.mkdtemp()


def upload(filename="film.mp4", content_type="video/mp4"):
    """Build a minimal uploaded file; the bytes are never decoded here."""
    return SimpleUploadedFile(filename, b"not a real movie", content_type=content_type)


def add_form_payload(**fields):
    """Complete a POST body the way a browser would.

    The change form carries an inline formset for the variants, and Django
    renders its bookkeeping as hidden inputs. Without them every POST fails on
    a missing management form — before any field validation runs at all, which
    makes a test pass or fail for reasons that have nothing to do with it.
    """
    return {
        "variants-TOTAL_FORMS": "0",
        "variants-INITIAL_FORMS": "0",
        "variants-MIN_NUM_FORMS": "0",
        "variants-MAX_NUM_FORMS": "1000",
        **fields,
    }


@override_settings(MEDIA_ROOT=TEMPORARY_MEDIA_ROOT)
class VideoAdminAccessTests(TestCase):
    """Only staff may reach the upload form."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMPORARY_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def test_staff_reaches_the_add_form(self):
        self.client.force_login(
            User.objects.create_superuser(
                username="admin", email="admin@example.com", password="adminpassword"
            )
        )
        response = self.client.get("/admin/video_app/video/add/")
        self.assertEqual(response.status_code, 200)

    def test_a_registered_user_is_turned_away(self):
        """Registration never grants is_staff, and this test keeps it that way.

        C-16 makes the admin the single upload path, so the door has to stay
        closed for everyone who merely holds an account.
        """
        self.client.force_login(
            User.objects.create_user(
                username="viewer@example.com",
                email="viewer@example.com",
                password="secret123",
            )
        )
        response = self.client.get("/admin/video_app/video/add/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])


@override_settings(MEDIA_ROOT=TEMPORARY_MEDIA_ROOT)
class VideoAdminFormTests(TestCase):
    """The form has to offer every field a film needs — and nothing more."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMPORARY_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client.force_login(
            User.objects.create_superuser(
                username="admin", email="admin@example.com", password="adminpassword"
            )
        )

    def test_add_form_offers_the_upload_fields(self):
        response = self.client.get("/admin/video_app/video/add/")
        for field in ("title", "description", "category", "video_file", "thumbnail"):
            self.assertContains(response, f'name="{field}"')

    def test_add_form_hides_the_conversion_state(self):
        """The pipeline owns these two values.

        A hand-written "ready" would tell the streaming view that segments exist
        which FFMPEG never wrote.
        """
        response = self.client.get("/admin/video_app/video/add/")
        self.assertNotContains(response, 'name="hls_status"')
        self.assertNotContains(response, 'name="hls_error"')

    def test_admin_creates_a_video_from_an_upload(self):
        """This is the path C-16 describes; if it breaks, no film ever arrives."""
        response = self.client.post(
            "/admin/video_app/video/add/",
            add_form_payload(
                title="Heavy Rain",
                description="Water falls.",
                category="drama",
                video_file=upload(),
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Video.objects.count(), 1)

    def test_admin_rejects_a_document(self):
        """The model validator has to run inside the admin form, not only in code.

        Naming the field in the assertion matters: without it the test would
        also pass if the form failed somewhere else entirely and never reached
        the validator.
        """
        response = self.client.post(
            "/admin/video_app/video/add/",
            add_form_payload(
                title="Wrong File",
                description="Not a movie.",
                category="drama",
                video_file=upload("report.pdf", "application/pdf"),
            ),
        )
        self.assertEqual(Video.objects.count(), 0)
        self.assertIn("video_file", response.context["adminform"].form.errors)


@override_settings(MEDIA_ROOT=TEMPORARY_MEDIA_ROOT)
class VideoAdminChangelistTests(TestCase):
    """The list has to answer "what is ready?" without opening every entry."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMPORARY_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.client.force_login(
            User.objects.create_superuser(
                username="admin", email="admin@example.com", password="adminpassword"
            )
        )
        self.video = Video.objects.create(
            title="Heavy Rain",
            description="Water falls.",
            category="drama",
            video_file="uploads/videos/film.mp4",
        )

    def test_changelist_shows_title_and_conversion_state(self):
        """A field with choices renders its label, so the column shows "Pending"."""
        response = self.client.get("/admin/video_app/video/")
        self.assertContains(response, "Heavy Rain")
        self.assertContains(response, "Pending")

    def test_change_page_lists_the_converted_resolutions(self):
        """Three renditions finish one after another; the page has to show which."""
        VideoVariant.objects.create(video=self.video, resolution="480p")
        response = self.client.get(f"/admin/video_app/video/{self.video.pk}/change/")
        self.assertContains(response, "480p")
