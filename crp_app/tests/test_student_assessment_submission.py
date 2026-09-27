from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from crp_app.models import (
    Assessment,
    AssessmentAttachment,
    AssessmentSubmission,
    Course,
    Department,
    Instructor,
    LearningWeek,
    Registration,
    Rubric,
    RubricCriterion,
    Student,
    SubmissionFile,
)


class StudentAssessmentSubmissionTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.department = Department.objects.create(name='Submission QA', code='SQA')
        self.trainer_user = User.objects.create_user('submission_trainer', password='test123')
        self.trainer = Instructor.objects.create(
            user=self.trainer_user, employee_id='SQA-T1', department=self.department
        )
        self.student_user = User.objects.create_user('submission_student', password='test123')
        self.other_user = User.objects.create_user('submission_other', password='test123')
        self.student = Student.objects.create(
            user=self.student_user, student_id='SQA-S1', cohort='SQA',
            program_start_date=today, program_end_date=today + timedelta(days=90),
        )
        self.other = Student.objects.create(
            user=self.other_user, student_id='SQA-S2', cohort='SQA',
            program_start_date=today, program_end_date=today + timedelta(days=90),
        )
        self.course = Course.objects.create(
            code='SQA-101', name='Submission QA', description='QA',
            credits=3, level='certificate', department=self.department, status='active',
            start_date=today, end_date=today + timedelta(days=90),
        )
        self.course.trainers.add(self.trainer)
        for student_user in (self.student_user,):
            registration = Registration.objects.create(
                student=student_user, course=self.course, semester='QA', status='approved'
            )
            registration.approved_by = self.trainer_user
            registration.save(update_fields=['approved_by'])
        self.week = LearningWeek.objects.create(
            course=self.course, week_number=1, title='Week 1', description='Week',
            learning_objectives='Objectives', completion_requirements='Requirements',
            topics=['topic'], is_published=True,
        )
        self.assessment = Assessment.objects.create(
            week=self.week, course=self.course, title='Submission Assessment',
            assessment_type='assignment', description='Describe the work.',
            instructions='Follow the instructions.', course_code=self.course.code,
            due_date=timezone.now() + timedelta(days=3), accepted_formats=['pdf'],
            required_file_count=1, max_file_size_mb=5, is_published=True,
        )
        self.client.force_login(self.student_user)

    def _file(self, name='work.pdf', content=b'%PDF-1.4 test'):
        return SimpleUploadedFile(name, content, content_type='application/pdf')

    def test_no_rubric_and_no_resources_render_compact_state(self):
        response = self.client.get(reverse('crp:student_assessment_submit', args=[self.assessment.id]))
        self.assertContains(response, 'No marking rubric has been provided')
        self.assertNotContains(response, '0 of 0')
        self.assertNotContains(response, 'Assignment Resources')

    def test_rubric_and_resources_render_with_size(self):
        rubric = Rubric.objects.create(assessment=self.assessment, name='QA rubric')
        RubricCriterion.objects.create(
            rubric=rubric, name='Quality', description='Quality of work',
            max_marks=10, weight_percentage=100,
        )
        attachment = AssessmentAttachment.objects.create(
            assessment=self.assessment, uploaded_by=self.trainer_user,
            original_filename='brief.pdf', file=SimpleUploadedFile('brief.pdf', b'brief'),
        )
        response = self.client.get(reverse('crp:student_assessment_submit', args=[self.assessment.id]))
        self.assertContains(response, 'QA rubric')
        self.assertContains(response, 'brief.pdf')
        self.assertContains(response, 'Download')
        self.assertContains(response, str(attachment.file.size))

    def test_saved_draft_reopens_with_file_and_comment(self):
        response = self.client.post(
            reverse('crp:student_assessment_submit', args=[self.assessment.id]),
            {'action': 'upload', 'submission_file': self._file()},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {
            'success': True,
            'file': {
                'id': SubmissionFile.objects.get().id,
                'name': 'work.pdf',
                'size': '0.0 MB',
                'type': 'PDF',
            },
        })
        self.client.post(
            reverse('crp:student_assessment_submit', args=[self.assessment.id]),
            {'action': 'save_draft', 'comment': 'Draft note'},
        )
        response = self.client.get(reverse('crp:student_assessment_submit', args=[self.assessment.id]))
        self.assertContains(response, 'Submission status')
        self.assertContains(response, 'Draft')
        self.assertContains(response, 'work.pdf')
        self.assertContains(response, 'Draft note')

    def test_ajax_upload_errors_are_json(self):
        response = self.client.post(
            reverse('crp:student_assessment_submit', args=[self.assessment.id]),
            {'action': 'upload', 'submission_file': self._file('work.docx')},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['success'], False)
        self.assertIn('not accepted', response.json()['error'])

    def test_ajax_upload_accepts_docx_mime_type(self):
        self.assessment.accepted_formats = ['docx']
        self.assessment.save(update_fields=['accepted_formats'])
        response = self.client.post(
            reverse('crp:student_assessment_submit', args=[self.assessment.id]),
            {
                'action': 'upload',
                'submission_file': SimpleUploadedFile(
                    'work.docx', b'PK fake docx',
                    content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                ),
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])

    def test_ajax_upload_rejects_oversized_file(self):
        response = self.client.post(
            reverse('crp:student_assessment_submit', args=[self.assessment.id]),
            {
                'action': 'upload',
                'submission_file': self._file(
                    content=b'%PDF-1.4' + b'x' * (self.assessment.max_file_size_mb * 1024 * 1024)
                ),
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('5 MB or smaller', response.json()['error'])
        self.assertFalse(SubmissionFile.objects.exists())

    def test_file_removal_is_owned_by_submission(self):
        submission = AssessmentSubmission.objects.create(student=self.student, assessment=self.assessment)
        file = SubmissionFile.objects.create(
            submission=submission, file=self._file(), file_name='work.pdf',
            file_type='PDF', file_size='0.0 MB',
        )
        response = self.client.post(
            reverse('crp:student_assessment_submit', args=[self.assessment.id]),
            {'action': 'delete_file', 'file_id': file.id},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SubmissionFile.objects.filter(pk=file.id).exists())

    def test_final_submission_receipt_and_timestamp(self):
        submission = AssessmentSubmission.objects.create(student=self.student, assessment=self.assessment)
        SubmissionFile.objects.create(
            submission=submission, file=self._file(), file_name='work.pdf',
            file_type='PDF', file_size='0.0 MB',
        )
        response = self.client.post(
            reverse('crp:student_assessment_submit', args=[self.assessment.id]),
            {'action': 'submit', 'comment': 'Final note'},
        )
        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, 'submitted')
        self.assertIsNotNone(submission.submitted_at)
        self.assertEqual(submission.feedback, 'Final note')
        self.assertContains(self.client.get(response.url), 'Assessment submitted successfully')

    def test_marked_state_renders_feedback_timestamp_and_rubric_result(self):
        rubric = Rubric.objects.create(assessment=self.assessment, name='QA rubric')
        criterion = RubricCriterion.objects.create(
            rubric=rubric, name='Quality', description='Quality',
            max_marks=10, weight_percentage=100,
        )
        submission = AssessmentSubmission.objects.create(
            student=self.student, assessment=self.assessment, status='marked',
            marks_awarded=4, feedback='Good work', marked_at=timezone.now(),
            marker_comments={str(criterion.id): 'Meets expectations'},
        )
        self.assessment.results_released = True
        self.assessment.save(update_fields=['results_released'])
        response = self.client.get(reverse('crp:student_assessment_detail', args=[self.assessment.id]))
        self.assertContains(response, '4/100')
        self.assertContains(response, 'Good work')
        self.assertContains(response, 'Marked')
        self.assertContains(response, 'Meets expectations')

    def test_unpublished_and_ineligible_assessments_are_denied(self):
        self.assessment.is_published = False
        self.assessment.save(update_fields=['is_published'])
        self.assertEqual(
            self.client.get(reverse('crp:student_assessment_detail', args=[self.assessment.id])).status_code,
            404,
        )
        self.assessment.is_published = True
        self.assessment.save(update_fields=['is_published'])
        self.client.force_login(self.other_user)
        self.assertEqual(
            self.client.get(reverse('crp:student_assessment_submit', args=[self.assessment.id])).status_code,
            404,
        )
