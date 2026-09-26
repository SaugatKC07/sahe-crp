from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from crp_app.models import JobListing, Resume, ResumeEducation, ResumeExperience, Student
from crp_app.resume_review import analyze_resume


class ResumeReviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('reviewer', password='password')
        self.student = Student.objects.create(
            user=self.user,
            student_id='RR-001',
            specialisation='ai',
            cohort='Q1 2026',
            program_start_date=date.today(),
            program_end_date=date.today() + timedelta(days=300),
        )
        self.resume = Resume.objects.create(
            student=self.student,
            headline='Python Developer',
            summary='A focused summary describing Python development and data work.',
            contact_email='reviewer@example.com',
            skills=['Python'],
        )
        ResumeEducation.objects.create(
            resume=self.resume, degree='Bachelor of IT', institution='SAHE',
            start_date=date.today(), is_current=True,
        )
        ResumeExperience.objects.create(
            resume=self.resume, role='Developer', company='Real Co',
            start_date=date.today(), is_current=True, bullets=['Built Python tools'],
        )
        self.client.force_login(self.user)

    def make_job(self, **kwargs):
        values = {
            'title': 'Python Engineer',
            'company': 'Employer',
            'location': 'Sydney',
            'salary': '$80K',
            'fields': ['ai'],
            'skills': ['Python', 'AWS'],
            'description': 'Python and AWS',
            'posted_date': date.today(),
        }
        values.update(kwargs)
        return JobListing.objects.create(**values)

    def test_analyzer_uses_real_content_and_overall_is_category_average(self):
        result = analyze_resume(self.resume)
        self.assertEqual(
            result['overall_score'],
            round(sum(item['value'] for item in result['scores']) / 4),
        )
        self.assertEqual(result['scores'][2]['value'], 0)
        experience = ResumeExperience.objects.get(resume=self.resume)
        experience.bullets = ['Improved throughput by 40%']
        experience.save()
        self.resume.refresh_from_db()
        improved = analyze_resume(self.resume)
        self.assertGreater(improved['scores'][2]['value'], result['scores'][2]['value'])

    def test_selected_job_keywords_and_missing_requirements_are_explainable(self):
        result = analyze_resume(self.resume, self.make_job())
        self.assertEqual(result['matched_requirements'], ['Python'])
        self.assertEqual(result['missing_requirements'], ['AWS'])
        self.assertEqual(result['keyword_coverage'], 50)
        self.assertNotIn('AWS', ' '.join(self.resume.skills))

    def test_analyze_endpoint_persists_current_student_results(self):
        response = self.client.post(reverse('crp:resume_rerun_ai'))
        self.assertEqual(response.status_code, 200)
        self.resume.refresh_from_db()
        self.assertEqual(self.resume.ai_score, response.json()['ai_score'])
        self.assertEqual(self.resume.ai_feedback['scores'], response.json()['ai_feedback'])

    def test_job_selection_is_limited_to_active_nonexpired_jobs(self):
        expired = self.make_job(expires_at=timezone.now() - timedelta(days=1))
        response = self.client.get(reverse('crp:student_resume'), {'job_id': expired.id})
        self.assertIsNone(response.context['selected_job'])

    def test_other_student_resume_is_not_exposed(self):
        other_user = User.objects.create_user('other-reviewer', password='password')
        other = Student.objects.create(
            user=other_user, student_id='RR-002', specialisation='ai',
            cohort='Q1 2026', program_start_date=date.today(),
            program_end_date=date.today() + timedelta(days=300),
        )
        Resume.objects.create(student=other, headline='SECRET RESUME')
        response = self.client.get(reverse('crp:student_resume'))
        self.assertNotContains(response, 'SECRET RESUME')
