from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from crp_app.models import (
    Assessment,
    AssessmentSubmission,
    Course,
    Department,
    Instructor,
    LearningWeek,
    Registration,
    Student,
    SubmissionFile,
    Rubric,
    RubricCriterion,
    RubricPerformanceLevel,
    SubmissionRubricResult,
)


class TrainerMarkingQueueTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        department = Department.objects.create(name='Marking QA', code='MQA')
        self.trainer_user = User.objects.create_user('marking_trainer', password='test123')
        trainer = Instructor.objects.create(
            user=self.trainer_user, employee_id='MQA-T1', department=department,
        )
        self.student_user = User.objects.create_user('marking_student', password='test123')
        self.other_student_user = User.objects.create_user('marking_other', password='test123')
        self.student = Student.objects.create(
            user=self.student_user, student_id='MQA-S1', cohort='MQA',
            program_start_date=today, program_end_date=today + timedelta(days=90),
        )
        self.other_student = Student.objects.create(
            user=self.other_student_user, student_id='MQA-S2', cohort='MQA',
            program_start_date=today, program_end_date=today + timedelta(days=90),
        )
        self.second_student_user = User.objects.create_user('marking_second', password='test123')
        self.second_student = Student.objects.create(
            user=self.second_student_user, student_id='MQA-S3', cohort='MQA',
            program_start_date=today, program_end_date=today + timedelta(days=90),
        )
        self.course = Course.objects.create(
            code='MQA-101', name='Marking QA', description='QA', credits=3,
            level='certificate', department=department, status='active',
            start_date=today, end_date=today + timedelta(days=90),
        )
        self.course.trainers.add(trainer)
        Registration.objects.create(
            student=self.student_user, course=self.course, semester='QA', status='approved',
        )
        Registration.objects.create(
            student=self.second_student_user, course=self.course, semester='QA', status='approved',
        )
        self.week = LearningWeek.objects.create(
            course=self.course, week_number=1, title='Week 1', description='Week',
            learning_objectives='Objectives', completion_requirements='Requirements',
            topics=['topic'], is_published=True,
        )
        self.assessment = Assessment.objects.create(
            week=self.week, course=self.course, title='Marking Assessment',
            assessment_type='assignment', course_code=self.course.code,
            due_date=timezone.now() + timedelta(days=3), accepted_formats=['pdf'],
            required_file_count=1, max_file_size_mb=5, is_published=True,
        )
        self.client.force_login(self.trainer_user)

    def _submission(self, student, status):
        submission = AssessmentSubmission.objects.create(
            student=student, assessment=self.assessment, status=status,
            submitted_at=timezone.now() if status != 'draft' else None,
            feedback='Student comment',
        )
        if status != 'draft':
            SubmissionFile.objects.create(
                submission=submission,
                file=SimpleUploadedFile('work.pdf', b'%PDF-1.4 test', content_type='application/pdf'),
                file_name='work.pdf', file_type='PDF',
                file_size='0.0 MB',
            )
        return submission

    def test_marking_queue_excludes_drafts_and_includes_submitted(self):
        draft = self._submission(self.student, 'draft')
        submitted = self._submission(self.second_student, 'submitted')

        response = self.client.get(reverse('crp:trainer_reference_module', args=['marking']))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(draft.id, [record['id'] for record in response.context['records']])
        self.assertIn(submitted.id, [record['id'] for record in response.context['records']])
        self.assertContains(response, submitted.student.user.get_full_name())
        self.assertContains(response, 'Submitted')
        self.assertContains(response, 'Awaiting Marking')
        self.assertContains(
            response,
            reverse('crp:trainer_submission_detail', args=[submitted.id]),
        )

    def test_open_resolves_exact_in_scope_submission(self):
        submission = self._submission(self.student, 'submitted')

        response = self.client.get(
            reverse('crp:trainer_submission_detail', args=[submission.id]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.student.user.get_full_name())
        self.assertContains(response, self.assessment.title)
        self.assertContains(response, 'Student comment')

    def test_trainer_cannot_open_out_of_scope_submission(self):
        submission = AssessmentSubmission.objects.create(
            student=self.other_student, assessment=self.assessment, status='submitted',
            submitted_at=timezone.now(),
        )

        response = self.client.get(
            reverse('crp:trainer_submission_detail', args=[submission.id]),
        )

        self.assertEqual(response.status_code, 404)

    def test_marking_submission_changes_status_to_marked(self):
        submission = self._submission(self.student, 'submitted')

        response = self.client.post(
            reverse('crp:trainer_submission_detail', args=[submission.id]),
            {'action': 'grade', 'marks_awarded': '8', 'feedback': 'Good work'},
        )

        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, 'marked')
        self.assertEqual(submission.marks_awarded, 8)
        self.assertIsNotNone(submission.marked_at)

    def test_submission_file_download_is_scoped_to_trainer(self):
        submission = self._submission(self.student, 'submitted')
        submission_file = submission.files.get()

        response = self.client.get(
            reverse('crp:trainer_submission_file_download', args=[submission_file.id]),
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url)

    def test_published_rubric_draft_does_not_mark_submission(self):
        rubric = Rubric.objects.create(assessment=self.assessment, name='QA rubric', is_published=True)
        criterion = RubricCriterion.objects.create(rubric=rubric, name='Quality', max_marks=10, weight_percentage=100)
        level = RubricPerformanceLevel.objects.create(
            criterion=criterion, name='Good', description='Good', min_marks=6, max_marks=10, order=1,
        )
        submission = self._submission(self.student, 'submitted')
        response = self.client.post(reverse('crp:trainer_submission_detail', args=[submission.id]), {
            'action': 'save_rubric_draft',
            f'criterion_{criterion.id}_level': level.id,
            f'criterion_{criterion.id}_marks': '8',
            f'criterion_{criterion.id}_feedback': 'Good',
        })
        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, 'submitted')
        self.assertEqual(SubmissionRubricResult.objects.get(submission=submission).awarded_marks, 8)

    def test_rubric_draft_persists_valid_subset_and_reports_blank_criterion(self):
        rubric = Rubric.objects.create(assessment=self.assessment, name='QA rubric', is_published=True)
        first = RubricCriterion.objects.create(rubric=rubric, name='Quality', max_marks=10, weight_percentage=50)
        second = RubricCriterion.objects.create(rubric=rubric, name='Evidence', max_marks=10, weight_percentage=50, order=1)
        first_level = RubricPerformanceLevel.objects.create(
            criterion=first, name='Good', description='Good descriptor', min_marks=6, max_marks=10, order=1,
        )
        RubricPerformanceLevel.objects.create(
            criterion=second, name='Good', description='Good descriptor', min_marks=6, max_marks=10, order=1,
        )
        submission = self._submission(self.student, 'submitted')
        response = self.client.post(
            reverse('crp:trainer_submission_detail', args=[submission.id]),
            {
                'action': 'save_rubric_draft',
                f'criterion_{first.id}_level': first_level.id,
                f'criterion_{first.id}_marks': '8',
                f'criterion_{second.id}_marks': '8',
            },
            follow=True,
        )
        self.assertContains(response, 'Invalid result for Evidence.')
        result = SubmissionRubricResult.objects.get(submission=submission, criterion=first)
        self.assertEqual(result.awarded_marks, 8)
        submission.refresh_from_db()
        self.assertEqual(submission.status, 'submitted')

    def test_rubric_finalize_rejects_total_above_assessment_maximum(self):
        self.assessment.max_marks = 10
        self.assessment.save(update_fields=['max_marks'])
        rubric = Rubric.objects.create(assessment=self.assessment, name='QA rubric', is_published=True)
        criteria = [
            RubricCriterion.objects.create(rubric=rubric, name=name, max_marks=10, weight_percentage=50, order=index)
            for index, name in enumerate(('Quality', 'Evidence'))
        ]
        levels = [
            RubricPerformanceLevel.objects.create(
                criterion=criterion, name='Good', description='Good descriptor', min_marks=0, max_marks=10, order=1,
            )
            for criterion in criteria
        ]
        submission = self._submission(self.student, 'submitted')
        data = {'action': 'finalize_rubric'}
        for criterion, level in zip(criteria, levels):
            data[f'criterion_{criterion.id}_level'] = level.id
            data[f'criterion_{criterion.id}_marks'] = '6'
        response = self.client.post(
            reverse('crp:trainer_submission_detail', args=[submission.id]),
            data,
            follow=True,
        )
        self.assertContains(response, 'cannot exceed the assessment maximum')
        submission.refresh_from_db()
        self.assertEqual(submission.status, 'submitted')
        self.assertIsNone(submission.marks_awarded)
        self.assertFalse(SubmissionRubricResult.objects.filter(submission=submission).exists())

    def test_published_rubric_finalize_requires_valid_complete_criteria(self):
        rubric = Rubric.objects.create(assessment=self.assessment, name='QA rubric', is_published=True)
        criterion = RubricCriterion.objects.create(rubric=rubric, name='Quality', max_marks=10, weight_percentage=100)
        level = RubricPerformanceLevel.objects.create(
            criterion=criterion, name='Good', description='Good', min_marks=6, max_marks=10, order=1,
        )
        submission = self._submission(self.student, 'submitted')
        self.client.post(reverse('crp:trainer_submission_detail', args=[submission.id]), {
            'action': 'finalize_rubric',
            f'criterion_{criterion.id}_level': level.id,
            f'criterion_{criterion.id}_marks': '11',
        })
        submission.refresh_from_db()
        self.assertEqual(submission.status, 'submitted')
        self.assertIsNone(submission.marks_awarded)
        response = self.client.post(reverse('crp:trainer_submission_detail', args=[submission.id]), {
            'action': 'finalize_rubric',
            f'criterion_{criterion.id}_level': level.id,
            f'criterion_{criterion.id}_marks': '8',
        })
        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, 'marked')
        self.assertEqual(submission.marks_awarded, 8)
