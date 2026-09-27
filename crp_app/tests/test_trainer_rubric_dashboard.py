from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from crp_app.models import (
    Assessment,
    Course,
    Department,
    Instructor,
    LearningWeek,
    Rubric,
    RubricCriterion,
)


class TrainerRubricDashboardTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.department = Department.objects.create(name='Rubric Dashboard QA', code='RDQ')
        self.trainer_user = User.objects.create_user('rubric_dashboard_trainer', password='test123')
        self.trainer = Instructor.objects.create(
            user=self.trainer_user,
            employee_id='RDQ-T1',
            department=self.department,
        )
        self.other_trainer_user = User.objects.create_user('rubric_dashboard_other', password='test123')
        self.other_trainer = Instructor.objects.create(
            user=self.other_trainer_user,
            employee_id='RDQ-T2',
            department=self.department,
        )
        self.course = self._course('RDQ-101', 'Rubric Dashboard', today)
        self.course.trainers.add(self.trainer)
        self.other_course = self._course('RDQ-202', 'Outside Scope', today)
        self.other_course.trainers.add(self.other_trainer)
        self.week_one = self._week(self.course, 1)
        self.week_two = self._week(self.course, 2)
        self.outside_week = self._week(self.other_course, 1)
        self.not_started = self._assessment(self.week_one, 'Not Started Assessment')
        self.draft = self._assessment(self.week_one, 'Draft Assessment')
        self.published = self._assessment(self.week_two, 'Published Assessment')
        self.outside = self._assessment(self.outside_week, 'Outside Scope Assessment')
        draft_rubric = Rubric.objects.create(assessment=self.draft, name='Draft Rubric')
        RubricCriterion.objects.create(
            rubric=draft_rubric,
            name='Draft quality',
            max_marks=50,
            weight_percentage=50,
        )
        published_rubric = Rubric.objects.create(
            assessment=self.published,
            name='Published Rubric',
            is_published=True,
        )
        RubricCriterion.objects.create(
            rubric=published_rubric,
            name='Analysis',
            max_marks=50,
            weight_percentage=50,
        )
        RubricCriterion.objects.create(
            rubric=published_rubric,
            name='Evidence',
            max_marks=50,
            weight_percentage=50,
            order=1,
        )
        self.client.force_login(self.trainer_user)

    def _course(self, code, name, today):
        return Course.objects.create(
            code=code,
            name=name,
            description='QA course',
            credits=3,
            level='certificate',
            department=self.department,
            status='active',
            start_date=today,
            end_date=today + timedelta(days=90),
        )

    def _week(self, course, week_number):
        return LearningWeek.objects.create(
            course=course,
            week_number=week_number,
            title=f'Week {week_number}',
            description='Week',
            learning_objectives='Objectives',
            completion_requirements='Requirements',
            topics=['rubrics'],
            is_published=True,
        )

    def _assessment(self, week, title):
        return Assessment.objects.create(
            week=week,
            course=week.course,
            title=title,
            assessment_type='assignment',
            description='Assessment description',
            course_code=week.course.code,
            due_date=timezone.now() + timedelta(days=week.week_number),
            accepted_formats=['pdf'],
            is_published=True,
        )

    def test_statuses_actions_counts_and_criteria_use_real_rubric_data(self):
        response = self.client.get(reverse('crp:trainer_rubrics'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['summary'], {
            'total_assessments': 3,
            'published_rubrics': 1,
            'draft_rubrics': 1,
            'not_started_rubrics': 1,
        })
        rows = {row['assessment'].id: row for row in response.context['assessment_rows']}
        self.assertEqual(rows[self.not_started.id]['status'], 'not_started')
        self.assertEqual(rows[self.not_started.id]['action_label'], 'Create Rubric')
        self.assertEqual(rows[self.draft.id]['status'], 'draft')
        self.assertEqual(rows[self.draft.id]['action_label'], 'Continue Editing')
        self.assertEqual(rows[self.draft.id]['criteria_count'], 1)
        self.assertEqual(rows[self.draft.id]['total_weight'], 50)
        self.assertEqual(rows[self.published.id]['status'], 'published')
        self.assertEqual(rows[self.published.id]['action_label'], 'View / Manage Rubric')
        self.assertEqual(rows[self.published.id]['criteria_count'], 2)
        self.assertEqual(rows[self.published.id]['total_weight'], 100)
        self.assertContains(response, 'Not Started')
        self.assertContains(response, 'Create Rubric')
        self.assertContains(response, 'Published')
        self.assertContains(response, 'View / Manage Rubric')

    def test_filters_are_limited_to_authorized_assessments(self):
        draft_response = self.client.get(reverse('crp:trainer_rubrics'), {'status': 'draft'})
        self.assertEqual([row['assessment'] for row in draft_response.context['assessment_rows']], [self.draft])
        self.assertEqual(draft_response.context['summary']['total_assessments'], 3)

        search_response = self.client.get(reverse('crp:trainer_rubrics'), {'q': 'Published'})
        self.assertEqual([row['assessment'] for row in search_response.context['assessment_rows']], [self.published])

        week_response = self.client.get(reverse('crp:trainer_rubrics'), {'week': self.week_one.id})
        self.assertEqual(
            {row['assessment'] for row in week_response.context['assessment_rows']},
            {self.not_started, self.draft},
        )
        course_response = self.client.get(reverse('crp:trainer_rubrics'), {'course': self.other_course.code})
        self.assertEqual(course_response.context['assessment_rows'], [])
        self.assertNotContains(course_response, self.outside.title)

    def test_out_of_scope_assessment_is_hidden_and_builder_access_is_denied(self):
        response = self.client.get(reverse('crp:trainer_rubrics'))
        self.assertNotContains(response, self.outside.title)
        builder_response = self.client.get(reverse('crp:trainer_rubric_builder', args=[self.outside.id]))
        self.assertEqual(builder_response.status_code, 302)
        self.assertEqual(builder_response.url, reverse('crp:trainer_assessments'))

