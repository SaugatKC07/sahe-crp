from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from crp_app.achievement_service import (
    calculate_student_points,
    evaluate_student_badges,
    refresh_cohort_leaderboard,
)
from crp_app.models import Badge, LinkedInProfile, LearningWeek, Quiz, QuizAttempt, Resume, Student


class AchievementEngineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('achievement-engine', password='password')
        self.student = Student.objects.create(
            user=self.user, student_id='AE-001', cohort='Q1 2026',
            specialisation='ai', program_start_date=date.today(),
            program_end_date=date.today() + timedelta(days=300),
        )
        self.quiz_badge = Badge.objects.create(name='Quiz Champion', description='90%+ quiz', points=15)
        self.career_badge = Badge.objects.create(name='Career Ready', description='Career milestones', points=30)
        self.manual_badge = Badge.objects.create(name='Team Player', description='Manual', points=15)

    def test_quiz_champion_is_awarded_from_real_completed_score(self):
        self.assertEqual(evaluate_student_badges(self.student), [])
        week = LearningWeek.objects.create(week_number=1, title='Week 1', description='')
        quiz = Quiz.objects.create(week=week, title='Quiz', question_count=1)
        QuizAttempt.objects.create(
            student=self.student, quiz=quiz, score=92,
            completed_at=timezone.now(), is_passed=True,
        )
        awarded = evaluate_student_badges(self.student)
        self.assertEqual([award.badge.name for award in awarded], ['Quiz Champion'])
        self.assertEqual(evaluate_student_badges(self.student), [])

    def test_manual_badges_are_not_automatically_awarded(self):
        evaluate_student_badges(self.student)
        self.assertFalse(self.student.badges.filter(badge=self.manual_badge).exists())

    def test_points_and_leaderboard_use_real_badges_and_deterministic_rank(self):
        evaluate_student_badges(self.student)
        self.assertEqual(calculate_student_points(self.student), 0)
        self.student_badge = self.student.badges.create(badge=self.manual_badge)
        self.assertEqual(calculate_student_points(self.student), 15)
        rows = refresh_cohort_leaderboard(self.student.cohort)
        self.assertEqual(rows[0].total_points, 15)
        self.assertEqual(rows[0].rank, 1)

    def test_career_ready_requires_real_resume_linkedin_and_career_evidence(self):
        Resume.objects.create(student=self.student, completeness_score=90)
        LinkedInProfile.objects.create(student=self.student, completeness_score=90)
        self.assertFalse(evaluate_student_badges(self.student))
        self.assertFalse(self.student.badges.filter(badge=self.career_badge).exists())
