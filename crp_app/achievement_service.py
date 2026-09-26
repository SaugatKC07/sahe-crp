from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import (
    Badge,
    Leaderboard,
    LinkedInProfile,
    Resume,
    Student,
    StudentBadge,
)
from .services import student_activity_dates


AUTOMATED_BADGES = {'Quiz Champion', 'Career Ready'}
MANUAL_BADGES = {
    'Early Bird', 'Team Player', 'Problem Solver', 'Quick Learner',
    'Perfect Attendance', 'Mentor Helper', 'Innovation Award',
}


def _quiz_champion_eligible(student):
    return student.quiz_attempts.filter(
        completed_at__isnull=False,
        score__gte=90,
    ).exists()


def _career_ready_eligible(student):
    try:
        resume = student.resume
        linkedin = student.linkedin_profile
    except (Resume.DoesNotExist, LinkedInProfile.DoesNotExist):
        return False
    career_evidence = (
        student.interview_attempts.filter(is_completed=True).exists()
        or student.job_applications.exists()
    )
    return (
        resume.completeness_score >= 80
        and linkedin.completeness_score >= 80
        and career_evidence
    )


def badge_eligibility(student, badge):
    if badge.name == 'Quiz Champion':
        return _quiz_champion_eligible(student)
    if badge.name == 'Career Ready':
        return _career_ready_eligible(student)
    return False


@transaction.atomic
def evaluate_student_badges(student):
    """Award objectively eligible badges once; never revoke historical awards."""
    awarded = []
    for badge in Badge.objects.filter(name__in=AUTOMATED_BADGES, is_active=True):
        if badge_eligibility(student, badge):
            award, created = StudentBadge.objects.get_or_create(
                student=student,
                badge=badge,
                defaults={'is_displayed': True},
            )
            if created:
                awarded.append(award)
    return awarded


def calculate_student_points(student):
    return sum(
        badge.points
        for badge in Badge.objects.filter(
            student_badges__student=student,
            student_badges__is_displayed=True,
        ).distinct()
    )


def calculate_current_streak(student):
    dates = student_activity_dates(student)
    cursor = timezone.localdate()
    streak = 0
    while cursor in dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


@transaction.atomic
def refresh_cohort_leaderboard(cohort):
    """Refresh real cohort aggregates using deterministic ranking."""
    if not cohort:
        return []
    students = list(Student.objects.filter(cohort=cohort).select_related('user'))
    rows = []
    for student in students:
        evaluate_student_badges(student)
        rows.append({
            'student': student,
            'total_points': calculate_student_points(student),
            'badges_count': student.badges.filter(is_displayed=True).count(),
            'streak_days': calculate_current_streak(student),
        })
    rows.sort(key=lambda row: (
        -row['total_points'],
        -row['badges_count'],
        -row['streak_days'],
        row['student'].student_id,
    ))
    result = []
    for rank, row in enumerate(rows, start=1):
        entry, _ = Leaderboard.objects.update_or_create(
            student=row['student'],
            cohort=cohort,
            defaults={
                'total_points': row['total_points'],
                'badges_count': row['badges_count'],
                'streak_days': row['streak_days'],
                'rank': rank,
            },
        )
        result.append(entry)
    return result
