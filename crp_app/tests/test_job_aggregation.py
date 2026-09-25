from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from crp_app.job_providers import AdzunaProvider, JobProviderError
from crp_app.job_sync import sync_job_source
from crp_app.models import (
    JobApplication,
    JobListing,
    JobSource,
    JobSyncRun,
    Resume,
    Student,
    StudentPreference,
)


class AdzunaAdapterTests(TestCase):
    def test_normalizes_external_job_fields(self):
        job = AdzunaProvider.normalize_job({
            'id': 'adzuna-1',
            'title': 'Machine Learning Engineer',
            'company': {'display_name': 'Example Labs'},
            'location': {'display_name': 'Sydney'},
            'category': {'label': 'IT Jobs'},
            'description': 'Build machine learning services in Python.',
            'created': '2026-09-10T10:00:00Z',
            'salary_min': 100000,
            'salary_max': 130000,
            'contract_time': 'full_time',
            'redirect_url': 'https://example.org/job/1',
        }, 'au')

        self.assertEqual(job['source_external_id'], 'adzuna-1')
        self.assertEqual(job['fields'], ['ai'])
        self.assertEqual(job['skills'], ['Python', 'Machine Learning'])
        self.assertEqual(job['salary_min'], 100)
        self.assertEqual(job['salary'], 'A$100,000–A$130,000 per year')
        self.assertEqual(job['apply_url'], 'https://example.org/job/1')

    @override_settings()
    def test_missing_credentials_fail_explicitly(self):
        with patch.dict('os.environ', {'ADZUNA_APP_ID': '', 'ADZUNA_APP_KEY': ''}, clear=False):
            with self.assertRaisesMessage(JobProviderError, 'must both be configured'):
                AdzunaProvider().fetch_jobs(JobSource(name='test'))


class JobSyncTests(TestCase):
    def setUp(self):
        self.source = JobSource.objects.create(name='Adzuna Australia')
        self.job_data = {
            'source_external_id': 'external-42',
            'title': 'Data Analyst',
            'company': 'Example Co',
            'location': 'Sydney',
            'salary': 'A$90,000 per year',
            'salary_min': 90,
            'salary_max': None,
            'job_type': 'full_time',
            'fields': ['data'],
            'skills': ['SQL'],
            'description': 'Analyze product data.',
            'match_percentage': 0,
            'posted_date': date.today(),
            'application_deadline': None,
            'is_active': True,
            'apply_url': 'https://example.org/jobs/42',
            'is_remote': False,
        }

    @patch('crp_app.job_sync.get_provider')
    def test_sync_is_idempotent_and_updates_existing_external_jobs(self, get_provider):
        provider = get_provider.return_value
        provider.fetch_jobs.return_value = [self.job_data]
        first_run = sync_job_source(self.source)
        self.job_data['title'] = 'Senior Data Analyst'
        second_run = sync_job_source(self.source)

        self.assertEqual(first_run.status, 'succeeded')
        self.assertEqual((first_run.jobs_created, first_run.jobs_updated), (1, 0))
        self.assertEqual((second_run.jobs_created, second_run.jobs_updated), (0, 1))
        self.assertEqual(JobListing.objects.filter(source=self.source).count(), 1)
        self.assertEqual(JobListing.objects.get(source=self.source).title, 'Senior Data Analyst')

    @patch('crp_app.job_sync.get_provider')
    def test_failed_sync_is_audited_and_reraised(self, get_provider):
        get_provider.return_value.fetch_jobs.side_effect = RuntimeError('provider unavailable')

        with self.assertRaisesMessage(RuntimeError, 'provider unavailable'):
            sync_job_source(self.source)

        run = JobSyncRun.objects.get(source=self.source)
        self.assertEqual(run.status, 'failed')
        self.assertIn('provider unavailable', run.error_message)
        self.assertIsNotNone(run.finished_at)


class StudentJobFeaturesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='job-student', password='password', email='job-student@example.org',
        )
        self.student = Student.objects.create(
            user=self.user,
            student_id='JOBS-1001',
            specialisation='ai',
            cohort='2026',
            program_start_date=date.today() - timedelta(days=10),
            program_end_date=date.today() + timedelta(days=100),
        )
        Resume.objects.create(student=self.student, skills=['Python', 'Machine Learning'])
        self.client.login(username='job-student', password='password')
        self.job = JobListing.objects.create(
            title='Machine Learning Engineer',
            company='Example Labs',
            location='Sydney',
            salary='A$100,000',
            fields=['ai'],
            skills=['Python', 'Machine Learning'],
            description='Build ML services.',
            posted_date=date.today(),
            apply_url='https://example.org/apply',
        )

    def test_student_can_save_and_view_saved_jobs_and_applications(self):
        self.client.post(reverse('crp:student_save_job', args=[self.job.pk]))
        response = self.client.get(reverse('crp:student_saved_jobs'))
        self.assertContains(response, self.job.title)

        self.client.post(reverse('crp:student_apply_job', args=[self.job.pk]))
        response = self.client.get(reverse('crp:student_job_applications'))
        self.assertContains(response, 'Applied')
        self.assertEqual(
            JobApplication.objects.get(student=self.student, job=self.job).status,
            'applied',
        )

    def test_preferences_and_recommendations_are_student_specific(self):
        self.client.post(reverse('crp:student_job_preferences'), {
            'job_keywords': 'machine learning, graduate',
            'job_locations': 'Sydney',
        })
        preferences = StudentPreference.objects.get(student=self.student)
        self.assertEqual(preferences.job_keywords, ['machine learning', 'graduate'])
        self.assertEqual(preferences.job_locations, ['Sydney'])

        response = self.client.get(reverse('crp:student_job_recommendations'))
        self.assertContains(response, self.job.title)
        self.assertEqual(response.context['job_rows'][0]['match'], 95)

    @patch('crp_app.views.sync_job_source')
    def test_admin_can_configure_sources_and_trigger_a_sync(self, sync_source):
        admin_user = User.objects.create_superuser(
            username='job-admin', email='job-admin@example.org', password='password',
        )
        self.client.force_login(admin_user)
        response = self.client.get(reverse('crp:admin_job_sources'))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse('crp:admin_job_sources'), {
            'action': 'save_source',
            'name': 'Adzuna Australia',
            'provider': 'adzuna',
            'country': 'au',
            'search_query': 'graduate data',
            'results_per_page': '25',
            'is_enabled': 'on',
        })
        self.assertEqual(response.status_code, 302)
        source = JobSource.objects.get(name='Adzuna Australia')
        self.assertEqual(source.search_query, 'graduate data')

        sync_source.return_value = SimpleNamespace(jobs_created=2, jobs_updated=1)
        response = self.client.post(reverse('crp:admin_job_sources'), {'source_id': source.pk})
        self.assertEqual(response.status_code, 302)
        sync_source.assert_called_once_with(source)

    @override_settings(JOB_CRON_SECRET='test-cron-secret')
    @patch('crp_app.views.sync_job_source')
    def test_cron_requires_bearer_secret_and_syncs_enabled_sources(self, sync_source):
        JobSource.objects.create(name='Cron source')
        unauthorized = self.client.get(reverse('job_cron:sync_jobs'))
        self.assertEqual(unauthorized.status_code, 403)

        sync_source.return_value = SimpleNamespace(
            jobs_seen=2, jobs_created=1, jobs_updated=1,
        )
        response = self.client.get(
            reverse('job_cron:sync_jobs'),
            HTTP_AUTHORIZATION='Bearer test-cron-secret',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'][0]['jobs_created'], 1)
        sync_source.assert_called_once()
