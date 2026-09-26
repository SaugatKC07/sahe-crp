from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .linkedin_coach import build_about, build_headline
from .models import JobListing, LinkedInProfile, Resume, ResumeEducation, ResumeExperience, Student


class LinkedInCoachTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='linkedin_student',
            password='password',
            first_name='LinkedIn',
            last_name='Student',
            email='student@example.com',
        )
        self.student = Student.objects.create(
            user=self.user,
            student_id='LI-001',
            specialisation='ai',
            cohort='Q3 2026',
            program_start_date=date.today() - timedelta(days=30),
            program_end_date=date.today() + timedelta(days=300),
        )
        self.resume = Resume.objects.create(
            student=self.student,
            summary='A genuine resume summary.',
            skills=['Python', 'SQL'],
            linkedin_url='https://www.linkedin.com/in/linkedin-student/',
        )
        ResumeEducation.objects.create(
            resume=self.resume,
            degree='Bachelor of Information Technology',
            institution='SAHE',
            start_date=date.today() - timedelta(days=30),
            is_current=True,
        )
        ResumeExperience.objects.create(
            resume=self.resume,
            role='Data Analyst Intern',
            company='Real Company',
            start_date=date.today() - timedelta(days=30),
            is_current=True,
            bullets=['Built a real report'],
        )
        self.client.force_login(self.user)

    def make_job(self, **kwargs):
        values = {
            'title': 'Junior Python Analyst',
            'company': 'Real Employer',
            'location': 'Sydney',
            'salary': '$80K',
            'fields': ['ai'],
            'skills': ['Python', 'AWS'],
            'description': 'Python and AWS role.',
            'posted_date': date.today(),
        }
        values.update(kwargs)
        return JobListing.objects.create(**values)

    def test_student_owns_linkedin_profile_and_resume_data(self):
        response = self.client.get(reverse('crp:student_linkedin'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Real Company')
        self.assertContains(response, 'Python')
        self.assertEqual(
            LinkedInProfile.objects.get(student=self.student).student,
            self.student,
        )

    def test_cross_student_access_is_not_exposed(self):
        other_user = User.objects.create_user(username='other', password='password')
        other_student = Student.objects.create(
            user=other_user,
            student_id='LI-002',
            specialisation='data_analytics',
            cohort='Q3 2026',
            program_start_date=date.today(),
            program_end_date=date.today() + timedelta(days=300),
        )
        Resume.objects.create(student=other_student, skills=['SECRET-SKILL'])
        LinkedInProfile.objects.create(student=other_student, headline='SECRET HEADLINE')

        response = self.client.get(reverse('crp:student_linkedin'))
        self.assertNotContains(response, 'SECRET-SKILL')
        self.assertNotContains(response, 'SECRET HEADLINE')

    def test_invalid_linkedin_url_is_rejected(self):
        response = self.client.post(reverse('crp:student_linkedin'), {
            'headline': 'A real headline',
            'about': 'A real About section.',
            'linkedin_url': 'https://example.com/profile',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Use a LinkedIn profile URL')
        self.resume.refresh_from_db()
        self.assertEqual(self.resume.linkedin_url, 'https://www.linkedin.com/in/linkedin-student/')

    def test_headline_and_about_editing_persist_without_overwriting_resume(self):
        response = self.client.post(reverse('crp:student_linkedin'), {
            'headline': 'Edited genuine headline',
            'about': 'Edited genuine About section.',
            'linkedin_url': self.resume.linkedin_url,
        })
        self.assertEqual(response.status_code, 302)
        profile = LinkedInProfile.objects.get(student=self.student)
        self.assertEqual(profile.headline, 'Edited genuine headline')
        self.assertEqual(profile.about, 'Edited genuine About section.')
        self.resume.refresh_from_db()
        self.assertEqual(self.resume.summary, 'A genuine resume summary.')
        self.assertEqual(self.resume.skills, ['Python', 'SQL'])

    def test_completeness_uses_real_saved_data(self):
        response = self.client.get(reverse('crp:student_linkedin'))
        profile = LinkedInProfile.objects.get(student=self.student)
        self.assertEqual(response.context['completeness_score'], 65)
        self.assertEqual(profile.completeness_score, 65)
        self.assertTrue(response.context['li_items'][2]['done'])
        self.assertTrue(response.context['li_items'][4]['done'])

    def test_builders_are_deterministic_and_use_only_resume_data(self):
        data = {
            'education': list(self.resume.education.all()),
            'experience': list(self.resume.experience.all()),
            'skills': ['Python', 'SQL'],
        }
        headline = build_headline(self.student, data)
        about = build_about(self.student, self.resume, data)
        self.assertEqual(headline, build_headline(self.student, data))
        self.assertEqual(about, build_about(self.student, self.resume, data))
        self.assertIn('Data Analyst Intern', headline)
        self.assertIn('Python', headline)
        self.assertIn('Real Company', about)
        self.assertNotIn('Invented Employer', about)
        self.assertNotIn('Java', about)

    def test_existing_linkedin_page_behavior_remains_available(self):
        response = self.client.get(reverse('crp:student_linkedin'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'LinkedIn Profile Coach')
        self.assertContains(response, 'Copy headline')
        self.assertContains(response, 'Open LinkedIn Profile')

    def test_visible_job_selection_uses_real_data(self):
        job = self.make_job()
        response = self.client.get(reverse('crp:student_linkedin'), {'job_id': job.id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Real Employer')
        self.assertContains(response, 'Already evidenced', status_code=200)
        self.assertContains(response, 'AWS')
        self.assertEqual(response.context['job_analysis']['matched'], ['Python'])
        self.assertEqual(response.context['job_analysis']['missing'], ['AWS'])

    def test_inactive_or_expired_jobs_are_not_selectable(self):
        inactive = self.make_job(is_active=False)
        expired = self.make_job(expires_at=timezone.now() - timedelta(days=1))
        for job in (inactive, expired):
            response = self.client.get(reverse('crp:student_linkedin'), {'job_id': job.id})
            self.assertIsNone(response.context['selected_job'])

    def test_job_suggestions_do_not_add_missing_requirements(self):
        job = self.make_job()
        response = self.client.get(reverse('crp:student_linkedin'), {'job_id': job.id})
        self.assertContains(response, 'Junior Python Analyst')
        self.assertNotContains(response, 'AWS ·')
        self.assertNotIn('AWS', response.context['job_about_suggestion'])

    def test_zero_requirements_has_no_fake_match(self):
        job = self.make_job(
            title='General Operations Role',
            skills=[],
            description='A role with no reliable structured requirements.',
        )
        response = self.client.get(reverse('crp:student_linkedin'), {'job_id': job.id})
        self.assertIsNone(response.context['job_analysis']['match_percentage'])
        self.assertContains(response, 'Not enough structured requirements')

    def test_job_detail_links_to_linkedin_coach(self):
        job = self.make_job()
        response = self.client.get(reverse('crp:student_job_detail', args=[job.id]))
        self.assertContains(response, f'?job_id={job.id}')
