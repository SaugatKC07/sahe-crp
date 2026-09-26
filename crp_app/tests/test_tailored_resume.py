from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from crp_app.models import JobListing, Resume, ResumeExperience, Student, TailoredResume


class TailoredResumeWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('student-one', 'one@example.com', 'pw')
        self.other_user = User.objects.create_user('student-two', 'two@example.com', 'pw')
        self.student = Student.objects.create(
            user=self.user, student_id='S1', cohort='Q1', program_start_date=date.today(),
            program_end_date=date.today(), specialisation='ai',
        )
        self.other_student = Student.objects.create(
            user=self.other_user, student_id='S2', cohort='Q1', program_start_date=date.today(),
            program_end_date=date.today(), specialisation='ai',
        )
        self.resume = Resume.objects.create(
            student=self.student, headline='Python Developer',
            summary='Builds reliable services.', skills=['Python', 'Django'],
        )
        ResumeExperience.objects.create(
            resume=self.resume, role='Developer', company='Acme', start_date=date.today(),
            bullets=['Built Django APIs'],
        )
        self.job = JobListing.objects.create(
            title='Django Engineer', company='Jobs Co', location='Remote', salary='N/A',
            skills=['Django', 'Kubernetes'], description='Build Django services.',
            posted_date=date.today(),
        )

    def test_tailoring_is_selected_job_specific_and_preserves_source(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('crp:student_tailor_resume', args=[self.job.id]))
        tailored = TailoredResume.objects.get()
        self.assertRedirects(response, reverse('crp:student_tailored_resume', args=[tailored.id]))
        self.assertEqual(tailored.job, self.job)
        self.assertEqual(tailored.source_resume, self.resume)
        self.assertEqual(tailored.analysis['missing_requirements'], ['Kubernetes'])
        self.resume.refresh_from_db()
        self.assertEqual(self.resume.skills, ['Python', 'Django'])

    def test_tailored_resume_is_not_cross_student_readable_or_exportable(self):
        tailored = TailoredResume.objects.create(
            student=self.student, job=self.job, source_resume=self.resume,
            headline=self.resume.headline, summary=self.resume.summary,
            skills=self.resume.skills, analysis={},
        )
        self.client.force_login(self.other_user)
        self.assertEqual(
            self.client.get(reverse('crp:student_tailored_resume', args=[tailored.id])).status_code, 404
        )
        self.assertEqual(
            self.client.get(reverse('crp:student_export_tailored_resume', args=[tailored.id])).status_code, 404
        )

    def test_unauthenticated_tailoring_requires_login(self):
        response = self.client.get(reverse('crp:student_tailor_resume', args=[self.job.id]))
        self.assertEqual(response.status_code, 302)
