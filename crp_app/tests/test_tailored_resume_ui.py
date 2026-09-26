from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from crp_app.models import JobListing, Resume, Student, TailoredResume


class TailoredResumeUITests(TestCase):
    def test_empty_job_skills_use_description_requirements(self):
        user = User.objects.create_user('ui-student', password='pw')
        student = Student.objects.create(
            user=user,
            student_id='UI1',
            cohort='Q1',
            program_start_date=date.today(),
            program_end_date=date.today(),
            specialisation='ai',
        )
        Resume.objects.create(student=student, skills=['Python'])
        job = JobListing.objects.create(
            title='Backend Engineer',
            company='UI Co',
            location='Remote',
            salary='N/A',
            skills=[],
            description='Build Kubernetes services with Python.',
            posted_date=date.today(),
        )

        self.client.force_login(user)
        response = self.client.post(reverse('crp:student_tailor_resume', args=[job.id]))
        tailored = TailoredResume.objects.get()

        self.assertRedirects(response, reverse('crp:student_tailored_resume', args=[tailored.id]))
        self.assertIn('Kubernetes', tailored.analysis['missing_requirements'])
        self.assertNotIn('Kubernetes', tailored.skills)

    def test_description_fallback_excludes_generic_company_location_and_date_terms(self):
        user = User.objects.create_user('ui-student-3', password='pw')
        student = Student.objects.create(
            user=user,
            student_id='UI3',
            cohort='Q1',
            program_start_date=date.today(),
            program_end_date=date.today(),
            specialisation='ai',
        )
        Resume.objects.create(student=student, skills=['Python'])
        job = JobListing.objects.create(
            title='Software Development Intern',
            company='Acme Sydney',
            location='Melbourne',
            salary='Paid',
            skills=[],
            description=(
                'Looking for multiple students for a paid internship based in Melbourne '
                'starting November. Experience with Software Development, Python, Git, '
                'REST APIs and Communication is useful.'
            ),
            posted_date=date.today(),
        )

        self.client.force_login(user)
        self.client.post(reverse('crp:student_tailor_resume', args=[job.id]))
        tailored = TailoredResume.objects.get()
        requirements = tailored.analysis['missing_requirements']

        for noisy_term in ('for', 'looking', 'multiple', 'students', 'paid', 'November', 'based', 'Acme', 'Melbourne'):
            self.assertNotIn(noisy_term.casefold(), {value.casefold() for value in requirements})
        self.assertIn('Software Development', requirements)
        self.assertIn('Git', requirements)
        self.assertIn('REST APIs', requirements)
        self.assertIn('Communication', requirements)
        self.assertNotIn('REST APIs', tailored.skills)

    def test_no_reliable_description_requirements_shows_guidance(self):
        user = User.objects.create_user('ui-student-4', password='pw')
        student = Student.objects.create(
            user=user,
            student_id='UI4',
            cohort='Q1',
            program_start_date=date.today(),
            program_end_date=date.today(),
            specialisation='ai',
        )
        Resume.objects.create(student=student, skills=[])
        job = JobListing.objects.create(
            title='Student Opportunity',
            company='Acme',
            location='Sydney',
            salary='Paid',
            skills=[],
            description='Looking for multiple students for a paid opportunity in November.',
            posted_date=date.today(),
        )

        self.client.force_login(user)
        self.client.post(reverse('crp:student_tailor_resume', args=[job.id]))
        tailored = TailoredResume.objects.get()

        self.assertEqual(tailored.analysis['missing_requirements'], [])
        self.assertFalse(tailored.analysis['requirements_available'])
        self.assertIn('No reliable structured requirements were available', tailored.analysis['recommendations'][0])

    def test_tailored_page_uses_workspace_sections(self):
        user = User.objects.create_user('ui-student-2', password='pw')
        student = Student.objects.create(
            user=user,
            student_id='UI2',
            cohort='Q1',
            program_start_date=date.today(),
            program_end_date=date.today(),
            specialisation='ai',
        )
        resume = Resume.objects.create(student=student, skills=['Python'])
        job = JobListing.objects.create(
            title='Python Engineer',
            company='UI Co',
            location='Remote',
            salary='N/A',
            skills=['Python'],
            description='Build services.',
            posted_date=date.today(),
        )
        tailored = TailoredResume.objects.create(
            student=student,
            job=job,
            source_resume=resume,
            skills=['Python'],
            analysis={'matched_skills': ['Python'], 'missing_requirements': [], 'recommendations': []},
        )

        self.client.force_login(user)
        response = self.client.get(reverse('crp:student_tailored_resume', args=[tailored.id]))

        self.assertContains(response, 'Matching analysis')
        self.assertContains(response, 'Resume editor')
        self.assertContains(response, 'Live preview')
        self.assertContains(response, 'tailored-workspace')
