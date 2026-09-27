from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
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
    Rubric,
    RubricCriterion,
    RubricPerformanceLevel,
    Student,
    SubmissionFile,
    SubmissionRubricResult,
)


class StudentRubricResultTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.department = Department.objects.create(name='Result QA', code='RQA')
        self.trainer_user = User.objects.create_user('result_trainer', password='test123')
        self.trainer = Instructor.objects.create(
            user=self.trainer_user,
            employee_id='RQA-T1',
            department=self.department,
        )
        self.student_user = User.objects.create_user('result_student_a', password='test123')
        self.other_user = User.objects.create_user('result_student_b', password='test123')
        self.student = Student.objects.create(
            user=self.student_user,
            student_id='RQA-S1',
            cohort='RQA',
            program_start_date=today,
            program_end_date=today + timedelta(days=90),
        )
        self.other_student = Student.objects.create(
            user=self.other_user,
            student_id='RQA-S2',
            cohort='RQA',
            program_start_date=today,
            program_end_date=today + timedelta(days=90),
        )
        self.course = Course.objects.create(
            code='RQA-101',
            name='Result Quality Assurance',
            description='QA',
            credits=3,
            level='certificate',
            department=self.department,
            status='active',
            start_date=today,
            end_date=today + timedelta(days=90),
        )
        self.course.trainers.add(self.trainer)
        for user in (self.student_user, self.other_user):
            registration = Registration.objects.create(
                student=user,
                course=self.course,
                semester='QA',
                status='approved',
            )
            registration.approved_by = self.trainer_user
            registration.save(update_fields=['approved_by'])
        self.week = LearningWeek.objects.create(
            course=self.course,
            week_number=3,
            title='Week 3',
            description='Week',
            learning_objectives='Objectives',
            completion_requirements='Requirements',
            topics=['results'],
            is_published=True,
        )
        self.assessment = Assessment.objects.create(
            week=self.week,
            course=self.course,
            title='Rubric Result Assessment',
            assessment_type='project',
            description='Complete the project.',
            course_code=self.course.code,
            max_marks=100,
            weight_percentage=40,
            due_date=timezone.now() + timedelta(days=3),
            accepted_formats=['pdf'],
            required_file_count=1,
            is_published=True,
        )
        self.rubric = Rubric.objects.create(
            assessment=self.assessment,
            name='Project Rubric',
            description='Project assessment criteria',
            is_published=True,
        )
        self.criterion = RubricCriterion.objects.create(
            rubric=self.rubric,
            name='Problem Analysis',
            description='Analyse the root cause.',
            max_marks=100,
            weight_percentage=100,
        )
        self.developing = RubricPerformanceLevel.objects.create(
            criterion=self.criterion,
            name='Developing',
            description='Basic analysis.',
            min_marks=0,
            max_marks=49,
            order=0,
        )
        self.proficient = RubricPerformanceLevel.objects.create(
            criterion=self.criterion,
            name='Proficient',
            description='Root-cause analysis with evidence.',
            min_marks=50,
            max_marks=89,
            order=1,
        )
        self.exemplary = RubricPerformanceLevel.objects.create(
            criterion=self.criterion,
            name='Exemplary',
            description='Exceptional evidence-led analysis.',
            min_marks=90,
            max_marks=100,
            order=2,
        )
        self.client.force_login(self.student_user)

    def _submission(self, status='marked', student=None, marks=Decimal('83'), feedback='Excellent overall progress.'):
        return AssessmentSubmission.objects.create(
            student=student or self.student,
            assessment=self.assessment,
            status=status,
            submitted_at=timezone.now() - timedelta(days=2),
            marked_at=timezone.now() - timedelta(hours=4) if status in ('marked', 'returned') else None,
            marks_awarded=marks,
            feedback=feedback,
            marker_comments={'_student_comment': 'Please review the attached project.'},
        )

    def _result(self, submission, marks=Decimal('83'), feedback='Strong analysis. Add more supporting evidence.'):
        return SubmissionRubricResult.objects.create(
            submission=submission,
            criterion=self.criterion,
            performance_level=self.proficient,
            awarded_marks=marks,
            feedback=feedback,
        )

    def _detail(self):
        return self.client.get(reverse('crp:student_assessment_detail', args=[self.assessment.id]))

    def _assert_results_hidden(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['result_is_released'])
        self.assertNotIn('result_summary', response.context)
        self.assertNotIn('rubric_results', response.context)
        self.assertNotIn('marks_awarded', response.context['submission'])
        self.assertNotContains(response, '83/100')
        self.assertNotContains(response, 'Excellent overall progress.')
        self.assertNotContains(response, 'Strong analysis. Add more supporting evidence.')

    def test_draft_submission_does_not_expose_results(self):
        submission = self._submission(status='draft')
        self._result(submission)
        response = self._detail()
        self._assert_results_hidden(response)
        self.assertContains(response, 'Draft Submission')
        self.assertContains(response, 'Continue Draft')

    def test_submitted_submission_does_not_expose_results(self):
        self._submission(status='submitted')
        response = self._detail()
        self._assert_results_hidden(response)
        self.assertContains(response, 'Submitted')
        self.assertContains(response, 'Awaiting Marking')

    def test_trainer_marking_draft_does_not_expose_rubric_results(self):
        submission = self._submission(status='submitted', feedback='Unreleased overall draft.')
        self._result(submission, feedback='Unreleased criterion draft.')
        response = self._detail()
        self.assertNotIn('rubric_results', response.context)
        self.assertNotContains(response, 'Unreleased overall draft.')
        self.assertNotContains(response, 'Unreleased criterion draft.')

    def test_marked_but_unreleased_submission_does_not_expose_marks(self):
        submission = self._submission()
        self._result(submission)
        response = self._detail()
        self._assert_results_hidden(response)
        self.assertContains(response, 'Marked')
        self.assertContains(response, 'Results Pending Release')

    def test_released_submission_exposes_overall_marks(self):
        self._submission()
        self.assessment.results_released = True
        self.assessment.save(update_fields=['results_released'])
        response = self._detail()
        self.assertTrue(response.context['result_is_released'])
        self.assertContains(response, '83/100')
        self.assertContains(response, 'Results Released')

    def test_released_rubric_submission_exposes_exact_normalized_result(self):
        submission = self._submission()
        result = self._result(submission)
        self.assessment.results_released = True
        self.assessment.save(update_fields=['results_released'])
        response = self._detail()
        self.assertEqual(len(response.context['rubric_results']), 1)
        self.assertEqual(response.context['rubric_results'][0]['awarded_marks'], result.awarded_marks)

    def test_correct_selected_performance_level_is_displayed(self):
        submission = self._submission()
        self._result(submission)
        self.assessment.results_released = True
        self.assessment.save(update_fields=['results_released'])
        response = self._detail()
        row = response.context['rubric_results'][0]
        self.assertEqual(row['selected_level'], self.proficient)
        self.assertEqual([level['name'] for level in row['levels'] if level['selected']], ['Proficient'])
        self.assertContains(response, 'PROFICIENT')

    def test_criterion_awarded_marks_are_displayed(self):
        submission = self._submission(marks=Decimal('76'))
        self._result(submission, marks=Decimal('76'))
        self.assessment.results_released = True
        self.assessment.save(update_fields=['results_released'])
        self.assertContains(self._detail(), '76/100')

    def test_criterion_feedback_is_displayed(self):
        submission = self._submission()
        self._result(submission, feedback='Use two additional sources.')
        self.assessment.results_released = True
        self.assessment.save(update_fields=['results_released'])
        self.assertContains(self._detail(), 'Use two additional sources.')

    def test_performance_level_descriptor_is_displayed(self):
        submission = self._submission()
        self._result(submission)
        self.assessment.results_released = True
        self.assessment.save(update_fields=['results_released'])
        self.assertContains(self._detail(), 'Root-cause analysis with evidence.')

    def test_overall_feedback_is_displayed(self):
        self._submission(feedback='Well structured overall.')
        self.assessment.results_released = True
        self.assessment.save(update_fields=['results_released'])
        self.assertContains(self._detail(), 'Well structured overall.')

    def test_marked_timestamp_is_displayed(self):
        submission = self._submission()
        self.assessment.results_released = True
        self.assessment.save(update_fields=['results_released'])
        response = self._detail()
        self.assertEqual(response.context['result_summary']['marked_at'], submission.marked_at)
        self.assertContains(response, timezone.localtime(submission.marked_at).strftime('%d %b %Y, %H:%M'))

    def test_total_and_percentage_use_submission_aggregate(self):
        submission = self._submission(marks=Decimal('86'))
        self._result(submission, marks=Decimal('21'))
        self.assessment.results_released = True
        self.assessment.save(update_fields=['results_released'])
        response = self._detail()
        self.assertEqual(response.context['result_summary']['marks_awarded'], Decimal('86'))
        self.assertEqual(response.context['result_summary']['percentage'], 86.0)
        self.assertContains(response, '86%')

    def test_legacy_non_rubric_result_still_works(self):
        legacy = Assessment.objects.create(
            week=self.week,
            course=self.course,
            title='Legacy Assessment',
            assessment_type='assignment',
            description='Legacy work',
            course_code=self.course.code,
            max_marks=50,
            due_date=timezone.now() + timedelta(days=2),
            accepted_formats=[],
            required_file_count=0,
            is_published=True,
            results_released=True,
        )
        AssessmentSubmission.objects.create(
            student=self.student,
            assessment=legacy,
            status='marked',
            submitted_at=timezone.now() - timedelta(days=2),
            marked_at=timezone.now(),
            marks_awarded=Decimal('40'),
            feedback='Legacy feedback remains available.',
        )
        response = self.client.get(reverse('crp:student_assessment_detail', args=[legacy.id]))
        self.assertContains(response, '40/50')
        self.assertContains(response, '80%')
        self.assertContains(response, 'Legacy feedback remains available.')
        self.assertEqual(response.context['rubric_results'], [])

    def test_student_a_cannot_see_student_b_result(self):
        self._submission(student=self.other_student, feedback='Student B private feedback.')
        self.assessment.results_released = True
        self.assessment.save(update_fields=['results_released'])
        response = self._detail()
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['submission'])
        self.assertNotContains(response, 'Student B private feedback.')

    def test_direct_file_url_manipulation_cannot_access_another_student(self):
        other_submission = self._submission(student=self.other_student)
        other_file = SubmissionFile.objects.create(
            submission=other_submission,
            file='submissions/student-b-private.pdf',
            file_name='student-b-private.pdf',
            file_type='PDF',
            file_size='1.0 MB',
        )
        response = self.client.get(reverse('crp:student_submission_file_download', args=[other_file.id]))
        self.assertEqual(response.status_code, 404)

    def test_unreleased_result_values_are_absent_from_detail_and_submit_contexts(self):
        submission = self._submission(feedback='Context-only secret feedback.')
        self._result(submission, feedback='Context-only criterion feedback.')
        detail = self._detail()
        submit = self.client.get(reverse('crp:student_assessment_submit', args=[self.assessment.id]))
        for response in (detail, submit):
            self.assertNotIn('result_summary', response.context)
            self.assertNotIn('rubric_results', response.context)
            self.assertNotIn('marks_awarded', response.context['submission'])
            self.assertNotContains(response, 'Context-only secret feedback.')
            self.assertNotContains(response, 'Context-only criterion feedback.')

    def test_assessment_list_uses_release_aware_states_without_early_marks(self):
        self._submission()
        response = self.client.get(reverse('crp:student_assessments'))
        self.assertContains(response, 'Results Pending Release')
        self.assertNotContains(response, '83/100')
        self.assessment.results_released = True
        self.assessment.save(update_fields=['results_released'])
        response = self.client.get(reverse('crp:student_assessments'))
        self.assertContains(response, 'Results Released')
        self.assertContains(response, 'View Results')
        self.assertContains(response, '83/100')

    def test_student_comment_survives_trainer_overall_feedback(self):
        submission = self._submission(feedback='Trainer overall feedback.')
        self.assessment.results_released = True
        self.assessment.save(update_fields=['results_released'])
        response = self._detail()
        self.assertContains(response, 'Please review the attached project.')
        self.assertContains(response, 'Trainer overall feedback.')

