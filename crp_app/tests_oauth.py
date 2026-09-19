from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import Student
from .oauth_adapter import CRPSocialAccountAdapter


class GoogleOAuthProfileTests(TestCase):
    def setUp(self):
        self.adapter = CRPSocialAccountAdapter(request=None)

    def test_new_student_profile_is_empty_and_unique(self):
        user = User.objects.create_user(
            username='new.google.user',
            email='new@example.com',
            first_name='New',
        )

        profile = self.adapter._ensure_student_profile(user)
        duplicate = self.adapter._ensure_student_profile(user)

        self.assertEqual(profile.pk, duplicate.pk)
        self.assertEqual(Student.objects.filter(user=user).count(), 1)
        self.assertEqual(profile.attendance_percentage, 0)
        self.assertEqual(profile.employability_score, 0)
        self.assertEqual(profile.current_streak, 0)
        self.assertEqual(user.registrations.count(), 0)

    def test_privileged_user_never_receives_student_profile(self):
        user = User.objects.create_user(
            username='existing.admin',
            email='admin@example.com',
            is_superuser=True,
            is_staff=True,
        )

        self.assertIsNone(self.adapter._ensure_student_profile(user))
        self.assertFalse(Student.objects.filter(user=user).exists())

    def test_verified_email_links_existing_user_and_preserves_profile(self):
        user = User.objects.create_user(
            username='existing.student',
            email='student@example.com',
            first_name='Existing',
        )
        today = timezone.localdate()
        profile = Student.objects.create(
            user=user,
            student_id='EXISTING-001',
            cohort='Existing Cohort',
            program_start_date=today,
            program_end_date=today + timedelta(days=365),
        )
        connected = []
        sociallogin = SimpleNamespace(
            is_existing=False,
            user=SimpleNamespace(
                email='student@example.com',
                first_name='Changed',
                last_name='Name',
            ),
            email_addresses=[SimpleNamespace(email='student@example.com', verified=True)],
            connect=lambda request, matched_user: connected.append(matched_user),
        )

        self.adapter.pre_social_login(None, sociallogin)

        user.refresh_from_db()
        self.assertEqual(connected, [user])
        self.assertEqual(user.first_name, 'Existing')
        self.assertEqual(user.last_name, 'Name')
        self.assertEqual(user.student_profile.pk, profile.pk)
        self.assertEqual(user.student_profile.cohort, 'Existing Cohort')

    def test_login_page_keeps_password_and_google_options(self):
        response = self.client.get('/crp/login/')

        self.assertContains(response, 'name="password"')
        self.assertContains(response, 'Continue with Google')
        self.assertContains(response, '/accounts/google/login/')
