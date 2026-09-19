from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta

from .models import (
    AssessmentSubmission,
    Assessment,
    LearningWeek,
    MaterialProgress,
    QuizAttempt,
    Student,
    StudentWeekProgress,
)


def approved_course_ids(student):
    """Return the courses for which this student has access."""
    return student.user.registrations.filter(
        status__in=('approved', 'completed')
    ).values('course_id')


def has_course_access(student, course):
    return student.user.registrations.filter(
        course=course,
        status__in=('approved', 'completed'),
    ).exists()


def eligible_weeks(student, course=None):
    """Return published curriculum scoped to the student's approved courses."""
    weeks = LearningWeek.objects.filter(
        course_id__in=approved_course_ids(student),
        is_published=True,
        is_archived=False,
    ).filter(Q(release_date__isnull=True) | Q(release_date__lte=timezone.now()))
    if course is not None:
        weeks = weeks.filter(course=course)
    return weeks.order_by('course_id', 'week_number')


def eligible_assessments(student):
    """Return published, non-archived assessments assigned to this student."""
    program_id = student.cohort_relation.program_id if student.cohort_relation_id else None
    return Assessment.objects.filter(
        is_published=True,
        is_archived=False,
        week__in=eligible_weeks(student),
    ).filter(
        Q(program__isnull=True) | Q(program_id=program_id),
        Q(cohort__isnull=True) | Q(cohort_id=student.cohort_relation_id),
    ).select_related('week', 'course')


def week_requirements_met(student, week):
    program_id = student.cohort_relation.program_id if student.cohort_relation_id else None
    materials = week.materials.filter(
        is_archived=False, is_published=True,
    ).filter(
        Q(program__isnull=True) | Q(program_id=program_id),
        Q(cohort__isnull=True) | Q(cohort_id=student.cohort_relation_id),
    )
    has_requirements = week.require_materials or week.require_quiz or week.require_assessment
    if week.require_materials and materials.filter(progress__student=student, progress__completed=False).exists():
        return False
    if week.require_materials and materials.exists() and not MaterialProgress.objects.filter(
        student=student, material__week=week, completed=True
    ).count() == materials.count():
        return False
    quiz = getattr(week, 'quiz', None)
    if week.require_quiz and (not quiz or quiz.is_archived or not quiz.is_published):
        return False
    if week.require_quiz and quiz and not quiz.is_archived and quiz.is_published and (
        (not quiz.program_id or quiz.program_id == program_id)
        and (not quiz.cohort_id or quiz.cohort_id == student.cohort_relation_id)
    ):
        has_requirements = True
    if week.require_quiz and quiz and not quiz.is_archived and quiz.is_published and not QuizAttempt.objects.filter(
        student=student, quiz=quiz, completed_at__isnull=False, is_passed=True
    ).exists():
        return False
    assessments = week.assessments.filter(is_published=True, is_archived=False)
    if week.require_assessment and not assessments.exists():
        return False
    for assessment in assessments if week.require_assessment else []:
        if assessment.required_submission and not AssessmentSubmission.objects.filter(
            student=student,
            assessment=assessment,
            status__in=['submitted', 'marked', 'returned'],
        ).exists():
            return False
    return has_requirements


def sync_student_progress(student):
    """Compute student-specific week state without persisting untouched GET state."""
    weeks = list(eligible_weeks(student))
    if not weeks:
        return []
    progress_by_week = {
        row.week_id: row for row in StudentWeekProgress.objects.filter(
            student=student, week__in=weeks
        )
    }
    rows = []
    previous_completed_by_course = {}
    for week in weeks:
        previous_completed = previous_completed_by_course.get(week.course_id, True)
        row = progress_by_week.get(week.id)
        is_persisted = row is not None
        if row is None:
            row = StudentWeekProgress(student=student, week=week, status='locked')
        if row.status == 'completed':
            previous_completed = True
        elif previous_completed:
            row.status = 'available' if not row.status == 'in_progress' else row.status
            previous_completed = week_requirements_met(student, week)
        else:
            row.status = 'locked'
        if row.status in ('available', 'in_progress') and week_requirements_met(student, week):
            row.status = 'completed'
            row.completed_at = row.completed_at or timezone.now()
            previous_completed = True
        if is_persisted or row.status == 'completed':
            row.save()
        rows.append(row)
        previous_completed_by_course[week.course_id] = previous_completed
    return rows


def student_progress_summary(student):
    rows = sync_student_progress(student)
    completed = sum(row.status == 'completed' for row in rows)
    current = next((row.week for row in rows if row.status in ('available', 'in_progress')), None)
    return rows, completed, current


def student_activity_dates(student):
    """Return dates with persisted student activity for streak calculation."""
    dates = set()
    dates.update(
        value.date() for value in MaterialProgress.objects.filter(
            student=student, completed=True, completed_at__isnull=False
        ).values_list('completed_at', flat=True)
    )
    dates.update(
        value.date() for value in QuizAttempt.objects.filter(
            student=student, completed_at__isnull=False
        ).values_list('completed_at', flat=True)
    )
    dates.update(
        value.date() for value in AssessmentSubmission.objects.filter(
            student=student, submitted_at__isnull=False
        ).values_list('submitted_at', flat=True)
    )
    return dates
