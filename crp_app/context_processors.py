from datetime import timedelta

from django.utils import timezone

from .models import AssessmentSubmission, MaterialProgress, Notification, QuizAttempt, StudentMessage
from .services import student_activity_dates


def student_shell(request):
    """Expose persisted student-shell metrics without creating any records."""
    if not request.user.is_authenticated:
        return {'is_crp_admin': False}
    notification_qs = Notification.objects.filter(user=request.user)
    base_context = {
        'portal_notifications': notification_qs[:5],
        'portal_unread_notifications': notification_qs.filter(is_read=False).count(),
    }
    student = getattr(request.user, 'student_profile', None)
    if student is None:
        return {
            **base_context,
            'is_crp_admin': request.user.is_superuser or request.user.groups.filter(
                name__in=['CRP Admin', 'Administrators']
            ).exists(),
        }

    activity_dates = student_activity_dates(student)
    current_streak = 0
    day = timezone.localdate()
    while day in activity_dates:
        current_streak += 1
        day -= timedelta(days=1)

    has_activity = bool(activity_dates)
    unread_messages = StudentMessage.objects.filter(
        recipient=request.user,
        is_read=False,
        thread__student=student,
    ).count()
    unread_notifications = notification_qs.filter(is_read=False).count()
    return {
        **base_context,
        'is_crp_admin': request.user.is_superuser or request.user.groups.filter(
            name__in=['CRP Admin', 'Administrators']
        ).exists(),
        'student_shell_readiness': student.employability_score if has_activity else 0,
        'student_shell_streak': current_streak,
        'student_shell_alerts': unread_messages + unread_notifications,
        'student_shell_notifications': Notification.objects.filter(user=request.user)[:5],
    }
