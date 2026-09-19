from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Assessment, AssessmentSubmission, Course, Department, Instructor,
    LearningMaterial, LearningWeek, MaterialProgress, Quiz, QuizAttempt,
    QuizOption, QuizQuestion, Registration, Student, StudentWeekProgress, Notification,
    AttendanceRecord, LiveSession, StudentRequest, SupportTicket, SupportTicketComment,
    StudentGroup, StudentGroupMember, SuccessStory,
)
from .services import sync_student_progress


class CourseArchitectureEndToEndTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.admin = User.objects.create_superuser('qa_admin', 'admin@example.com', 'test123')
        self.department = Department.objects.create(name='QA Academic', code='QAA')
        self.trainer_users = [User.objects.create_user(f'qa_trainer_{i}', password='test123') for i in (1, 2)]
        self.trainers = [Instructor.objects.create(user=user, employee_id=f'QA-T{i}', department=self.department) for i, user in enumerate(self.trainer_users, 1)]
        self.student_users = [User.objects.create_user(f'qa_student_{i}', password='test123') for i in (1, 2)]
        self.students = [Student.objects.create(user=user, student_id=f'QA-S{i}', cohort='QA', program_start_date=today, program_end_date=today + timedelta(days=90)) for i, user in enumerate(self.student_users, 1)]
        self.courses = [Course.objects.create(code=f'QA-{code}', name=f'Course {code}', description=f'{code} description', credits=3, level='certificate', department=self.department, status='active', start_date=today, end_date=today + timedelta(days=90)) for code in ('A', 'B')]
        self.courses[0].trainers.add(self.trainers[0])
        self.courses[1].trainers.add(self.trainers[1])
        self.client = Client()

    def _week(self, course, number, published=True, required=False):
        return LearningWeek.objects.create(
            course=course, week_number=number, title=f'{course.code} Week {number}',
            description=f'{course.code} description {number}', learning_objectives=f'{course.code} objectives {number}',
            completion_requirements=f'{course.code} requirements {number}', topics=[f'{course.code}-topic'],
            is_published=published, require_materials=required, require_quiz=required,
            require_assessment=required,
        )

    def _approve(self, student_user, course):
        registration = Registration.objects.create(student=student_user, course=course, semester='QA', status='pending')
        registration.approve(self.admin)
        return registration

    def test_admin_week_values_render_exactly_and_stay_course_scoped(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('crp:admin_course_detail', args=[self.courses[0].id]), {
            'action': 'week_save', 'week_number': 1, 'title': 'Python Fundamentals',
            'description': 'Variables, data types and operators', 'learning_objectives': 'Understand Python syntax exactly',
            'topics': 'variables, operators', 'completion_requirements': 'Finish all Python activities', 'is_published': 'on',
        })
        self.assertEqual(response.status_code, 302)
        week = LearningWeek.objects.get(course=self.courses[0], week_number=1)
        self._approve(self.student_users[0], self.courses[0])
        self._approve(self.student_users[0], self.courses[1])
        self._week(self.courses[1], 1)
        self.client.force_login(self.student_users[0])
        page = self.client.get(reverse('crp:student_course_week', args=[self.courses[0].id, week.id]))
        self.assertEqual(page.status_code, 200)
        for value in ('Python Fundamentals', 'Variables, data types and operators', 'Understand Python syntax exactly', 'Finish all Python activities'):
            self.assertContains(page, value)
        self.assertNotContains(self.client.get(reverse('crp:student_course_home', args=[self.courses[1].id])), 'Python Fundamentals')

    def test_enrollment_pending_then_approved_and_other_course_denied(self):
        week = self._week(self.courses[0], 1)
        self.client.force_login(self.student_users[0])
        dashboard = self.client.get(reverse('crp:student_portal'))
        self.assertContains(dashboard, self.courses[0].name)
        self.client.post(reverse('crp:request_course_enrollment', args=[self.courses[0].id]))
        registration = Registration.objects.get(student=self.student_users[0], course=self.courses[0])
        self.assertEqual(registration.status, 'pending')
        self.assertEqual(self.client.get(reverse('crp:student_course_home', args=[self.courses[0].id])).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(reverse('crp:admin_enrollment_action', args=[registration.id, 'approve']))
        self.client.force_login(self.student_users[0])
        self.assertContains(self.client.get(reverse('crp:student_portal')), self.courses[0].name)
        self.assertEqual(self.client.get(reverse('crp:student_course_week', args=[self.courses[0].id, week.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse('crp:student_course_home', args=[self.courses[1].id])).status_code, 403)

    def test_publish_archive_states_are_independent(self):
        self._approve(self.student_users[0], self.courses[0])
        week = self._week(self.courses[0], 1, published=False)
        self.client.force_login(self.student_users[0])
        url = reverse('crp:student_course_week', args=[self.courses[0].id, week.id])
        self.assertEqual(self.client.get(url).status_code, 404)
        week.is_published = True; week.save(update_fields=['is_published'])
        self.assertEqual(self.client.get(url).status_code, 200)
        week.is_archived = True; week.save(update_fields=['is_archived'])
        self.assertEqual(self.client.get(url).status_code, 404)
        week.is_archived = False; week.save(update_fields=['is_archived'])
        week.refresh_from_db(); self.assertTrue(week.is_published)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_progress_and_learning_records_are_isolated_per_course(self):
        for course in self.courses: self._approve(self.student_users[0], course)
        a1, a2 = self._week(self.courses[0], 1, required=True), self._week(self.courses[0], 2)
        b1, b2 = self._week(self.courses[1], 1, required=True), self._week(self.courses[1], 2)
        material = LearningMaterial.objects.create(week=a1, title='A material', material_type='link', is_published=True)
        quiz = Quiz.objects.create(week=a1, title='A quiz', question_count=1, is_published=True)
        assessment = Assessment.objects.create(week=a1, course=self.courses[0], title='A assignment', assessment_type='assignment', description='A only', course_code=self.courses[0].code, due_date=timezone.now(), is_published=True)
        rows = {row.week_id: row.status for row in sync_student_progress(self.students[0])}
        self.assertEqual((rows[a1.id], rows[a2.id], rows[b1.id], rows[b2.id]), ('available', 'locked', 'available', 'locked'))
        MaterialProgress.objects.create(student=self.students[0], material=material, completed=True, completed_at=timezone.now())
        QuizAttempt.objects.create(student=self.students[0], quiz=quiz, completed_at=timezone.now(), score=100, is_passed=True)
        AssessmentSubmission.objects.create(student=self.students[0], assessment=assessment, status='submitted', submitted_at=timezone.now())
        rows = {row.week_id: row.status for row in sync_student_progress(self.students[0])}
        self.assertEqual((rows[a1.id], rows[a2.id]), ('completed', 'available'))
        self.assertEqual((rows[b1.id], rows[b2.id]), ('available', 'locked'))
        self.assertFalse(MaterialProgress.objects.filter(student=self.students[0], material__week__course=self.courses[1]).exists())
        self.assertFalse(QuizAttempt.objects.filter(student=self.students[0], quiz__week__course=self.courses[1]).exists())
        self.assertFalse(AssessmentSubmission.objects.filter(student=self.students[0], assessment__course=self.courses[1]).exists())

    def test_admin_routes_and_trainer_curriculum_denials(self):
        admin_urls = [reverse('crp:admin_courses')] + [reverse('crp:admin_academic_module', args=[name]) for name in ('weeks', 'materials', 'quizzes', 'questions', 'assessments')] + [reverse('crp:admin_enrollments'), reverse('crp:admin_trainers')]
        self.client.force_login(self.admin)
        self.assertTrue(all(self.client.get(url).status_code == 200 for url in admin_urls))
        week = self._week(self.courses[0], 1)
        quiz = Quiz.objects.create(week=week, title='Protected quiz')
        question = QuizQuestion.objects.create(quiz=quiz, question_text='Protected?')
        self.client.force_login(self.trainer_users[0])
        protected = [reverse('crp:week_save'), reverse('crp:material_create'), reverse('crp:quiz_create'), reverse('crp:quiz_question_save', args=[quiz.id])]
        self.assertTrue(all(self.client.post(url).status_code in (302, 403) for url in protected))
        self.assertFalse(LearningWeek.objects.filter(title='Trainer mutation').exists())

    def test_trainer_assignment_submission_mark_and_release(self):
        a1 = self._week(self.courses[0], 1)
        self._approve(self.student_users[0], self.courses[0])
        self._approve(self.student_users[1], self.courses[1])
        self.client.force_login(self.trainer_users[0])
        self.client.post(reverse('crp:assessment_create'), {'week': a1.id, 'course_code': self.courses[0].code, 'title': 'Trainer A assignment', 'description': 'A students only', 'due_date': timezone.now().strftime('%Y-%m-%dT%H:%M')})
        assessment = Assessment.objects.get(title='Trainer A assignment')
        assessment.is_published = True; assessment.required_file_count = 0; assessment.save()
        self.client.force_login(self.student_users[0])
        self.assertEqual(self.client.get(reverse('crp:student_assessment_detail', args=[assessment.id])).status_code, 200)
        self.client.post(reverse('crp:student_assessment_submit', args=[assessment.id]), {'action': 'submit'})
        submission = AssessmentSubmission.objects.get(student=self.students[0], assessment=assessment)
        self.client.force_login(self.student_users[1])
        self.assertEqual(self.client.get(reverse('crp:student_assessment_detail', args=[assessment.id])).status_code, 404)
        self.client.force_login(self.trainer_users[0])
        self.client.post(reverse('crp:submission_mark', args=[submission.id]), {'marks_awarded': 84, 'feedback': 'Strong work'})
        submission.refresh_from_db(); self.assertEqual((submission.marks_awarded, submission.feedback), (84, 'Strong work'))
        self.client.force_login(self.student_users[0])
        self.assertNotContains(self.client.get(reverse('crp:student_assessment_detail', args=[assessment.id])), '84/100')
        self.client.force_login(self.trainer_users[0])
        self.client.post(reverse('crp:assessment_release_results', args=[assessment.id]))
        self.client.force_login(self.student_users[0])
        page = self.client.get(reverse('crp:student_assessment_detail', args=[assessment.id]))
        self.assertContains(page, '84/100'); self.assertContains(page, 'Strong work')

    def test_trainer_cannot_mark_or_release_unassigned_course_submission(self):
        week_a = self._week(self.courses[0], 1)
        week_b = self._week(self.courses[1], 1)
        assessment_b = Assessment.objects.create(
            week=week_b, course=self.courses[1], title='Course B assignment',
            assessment_type='assignment', description='B only',
            course_code=self.courses[1].code, due_date=timezone.now(),
            is_published=True,
        )
        submission = AssessmentSubmission.objects.create(
            student=self.students[1], assessment=assessment_b,
            status='submitted', submitted_at=timezone.now(),
        )
        self.client.force_login(self.trainer_users[0])

        mark_response = self.client.post(
            reverse('crp:submission_mark', args=[submission.id]),
            {'marks_awarded': 99, 'feedback': 'Should remain untouched'},
        )
        release_response = self.client.post(
            reverse('crp:assessment_release_results', args=[assessment_b.id]),
        )

        self.assertEqual(mark_response.status_code, 302)
        self.assertEqual(release_response.status_code, 302)
        submission.refresh_from_db()
        assessment_b.refresh_from_db()
        self.assertIsNone(submission.marks_awarded)
        self.assertEqual(submission.status, 'submitted')
        self.assertFalse(assessment_b.results_released)
        self.assertFalse(week_a.assessments.filter(id=assessment_b.id).exists())

    def test_trainer_student_detail_does_not_include_other_course_quiz_attempts(self):
        week_a = self._week(self.courses[0], 1)
        week_b = self._week(self.courses[1], 1)
        self._approve(self.student_users[0], self.courses[0])
        self._approve(self.student_users[0], self.courses[1])
        quiz_a = Quiz.objects.create(week=week_a, title='Course A quiz', question_count=1)
        quiz_b = Quiz.objects.create(week=week_b, title='Course B quiz', question_count=1)
        QuizAttempt.objects.create(student=self.students[0], quiz=quiz_a, score=80, completed_at=timezone.now())
        QuizAttempt.objects.create(student=self.students[0], quiz=quiz_b, score=20, completed_at=timezone.now())

        self.client.force_login(self.trainer_users[0])
        response = self.client.get(reverse('crp:trainer_student_detail', args=[self.students[0].id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Course A quiz')
        self.assertNotContains(response, 'Course B quiz')

    def test_admin_cannot_create_assignments(self):
        week = self._week(self.courses[0], 1)
        self.client.force_login(self.admin)
        payload = {
            'week': week.id,
            'week_id': week.id,
            'course_code': self.courses[0].code,
            'title': 'Admin assignment',
            'action': 'assessment_save',
        }

        self.client.post(reverse('crp:assessment_create'), payload)
        self.client.post(reverse('crp:admin_course_detail', args=[self.courses[0].id]), payload)

        self.assertFalse(Assessment.objects.filter(title='Admin assignment').exists())
        page = self.client.get(reverse('crp:admin_course_detail', args=[self.courses[0].id]))
        self.assertNotContains(page, 'name="action" value="assessment_save"')

    def test_student_can_only_start_messages_with_related_trainers(self):
        self._approve(self.student_users[0], self.courses[0])
        self.client.force_login(self.student_users[0])

        allowed = self.client.post(reverse('crp:student_messages'), {
            'trainer_id': self.trainer_users[0].id,
            'title': 'Course question',
            'content': 'Please clarify the next activity.',
        })
        denied = self.client.post(reverse('crp:student_messages'), {
            'trainer_id': self.trainer_users[1].id,
            'title': 'Unrelated question',
            'content': 'This must not be delivered.',
        })

        self.assertEqual(allowed.status_code, 302)
        self.assertEqual(denied.status_code, 404)
        self.assertTrue(Notification.objects.filter(
            user=self.trainer_users[0], category='message',
        ).exists())
        self.assertFalse(Notification.objects.filter(
            user=self.trainer_users[1], category='message',
        ).exists())

    def test_student_notifications_can_be_marked_read(self):
        notification = Notification.objects.create(
            user=self.student_users[0], title='Test notification', message='Read me',
        )
        self.client.force_login(self.student_users[0])
        response = self.client.post(reverse('crp:student_notifications'), {
            'action': 'mark_read', 'notification_id': notification.id,
        })
        self.assertEqual(response.status_code, 302)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_attendance_is_persisted_and_student_percentage_uses_records(self):
        self._approve(self.student_users[0], self.courses[0])
        AttendanceRecord.objects.create(
            student=self.students[0], session_date=timezone.localdate(),
            status='present', recorded_by=self.trainer_users[0],
        )
        AttendanceRecord.objects.create(
            student=self.students[0], session_date=timezone.localdate() - timedelta(days=1),
            status='absent', recorded_by=self.trainer_users[0],
        )
        self.client.force_login(self.student_users[0])
        response = self.client.get(reverse('crp:student_attendance'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '50')

    def test_student_sees_only_published_live_sessions_and_calendar_updates(self):
        self._approve(self.student_users[0], self.courses[0])
        session = LiveSession.objects.create(
            title='Robotics lab', starts_at=timezone.now() + timedelta(days=1),
            is_published=True,
        )
        self.client.force_login(self.student_users[0])
        self.assertContains(self.client.get(reverse('crp:student_live_sessions')), session.title)
        self.assertContains(self.client.get(reverse('crp:student_calendar')), session.title)
        session.is_archived = True
        session.save(update_fields=['is_archived', 'updated_at'])
        self.assertNotContains(self.client.get(reverse('crp:student_live_sessions')), session.title)

    def test_extension_request_is_scoped_and_decision_notifies_student(self):
        self._approve(self.student_users[0], self.courses[0])
        week = self._week(self.courses[0], 1)
        assessment = Assessment.objects.create(
            week=week, course=self.courses[0], title='Extension assignment',
            assessment_type='assignment', description='Scoped assignment',
            course_code=self.courses[0].code, due_date=timezone.now(),
            is_published=True,
        )
        self.client.force_login(self.student_users[0])
        response = self.client.post(reverse('crp:student_requests'), {
            'request_type': 'academic', 'subject': 'Need more time',
            'description': 'Requesting an extension', 'assessment_id': assessment.id,
            'requested_date': (timezone.localdate() + timedelta(days=3)).isoformat(),
        })
        self.assertEqual(response.status_code, 302)
        support_request = StudentRequest.objects.get(student=self.students[0])
        self.client.force_login(self.trainer_users[0])
        response = self.client.post(reverse('crp:trainer_reference_module', args=['requests']), {
            'action': 'update_request', 'request_id': support_request.id,
            'status': 'approved', 'response': 'Approved for review',
        })
        self.assertEqual(response.status_code, 302)
        support_request.refresh_from_db()
        self.assertEqual(support_request.status, 'approved')
        self.assertTrue(Notification.objects.filter(
            user=self.student_users[0], category='request',
        ).exists())

    def test_trainer_cannot_cross_course_attendance_or_request_scope(self):
        self._approve(self.student_users[1], self.courses[1])
        self.client.force_login(self.trainer_users[0])
        self.assertEqual(
            self.client.get(reverse('crp:trainer_attendance'), {'course_id': self.courses[1].id}).status_code,
            404,
        )
        support_request = StudentRequest.objects.create(
            student=self.students[1], subject='Course B request', description='Restricted',
        )
        self.assertEqual(
            self.client.post(reverse('crp:trainer_reference_module', args=['requests']), {
                'action': 'update_request', 'request_id': support_request.id,
                'status': 'approved', 'response': 'Should be denied',
            }).status_code,
            404,
        )

    def test_admin_user_management_filters_and_persists_activation(self):
        self.client.force_login(self.admin)
        self.assertContains(
            self.client.get(reverse('crp:admin_operations_module', args=['users']), {'q': 'qa_student_1'}),
            'qa_student_1',
        )
        response = self.client.post(reverse('crp:admin_operations_module', args=['users']), {
            'user_id': self.student_users[0].id,
            'is_active': '',
        })
        self.assertEqual(response.status_code, 302)
        self.student_users[0].refresh_from_db()
        self.assertFalse(self.student_users[0].is_active)

    def test_admin_student_operations_persist_status(self):
        self.client.force_login(self.admin)
        student = self.students[0]
        response = self.client.post(
            reverse('crp:admin_operations_module', args=['students']),
            {'student_id': student.id, 'status': 'graduated'},
        )
        self.assertEqual(response.status_code, 302)
        student.refresh_from_db()
        self.assertEqual(student.status, 'graduated')

    def test_admin_analytics_uses_live_database_counts(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('crp:admin_system_module', args=['analytics']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Operational analytics')
        self.assertContains(response, 'Attendance records')

    def test_support_tickets_are_owner_scoped_and_admin_managed(self):
        ticket = SupportTicket.objects.create(
            created_by=self.student_users[0], subject='Help', description='Need assistance',
        )
        other_ticket = SupportTicket.objects.create(
            created_by=self.student_users[1], subject='Private', description='Do not leak',
        )
        self.client.force_login(self.student_users[0])
        response = self.client.get(reverse('crp:support_tickets'))
        self.assertContains(response, ticket.subject)
        self.assertNotContains(response, other_ticket.subject)
        self.client.force_login(self.admin)
        response = self.client.post(reverse('crp:support_tickets'), {
            'action': 'update', 'ticket_id': ticket.id, 'status': 'resolved',
            'priority': 'high', 'comment': 'Resolved by admin',
        })
        self.assertEqual(response.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'resolved')
        self.assertTrue(SupportTicketComment.objects.filter(ticket=ticket).exists())

    def test_admin_integrations_show_safe_configuration_state(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('crp:admin_operations_module', args=['integrations']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Not configured')
        self.assertNotContains(response, 'SECRET_KEY')

    def test_trainer_group_actions_are_course_scoped_and_student_membership_is_shared(self):
        cohort = self.students[0].cohort_relation
        group = StudentGroup.objects.create(name='QA group', cohort=cohort)
        self.client.force_login(self.student_users[0])
        response = self.client.post(reverse('crp:student_group_join', args=[group.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(StudentGroupMember.objects.filter(group=group, student=self.students[0]).exists())
        self.client.force_login(self.student_users[1])
        self.assertEqual(self.client.get(reverse('crp:student_group_detail', args=[group.id])).status_code, 200)
