from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import authenticate, login, logout
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.contrib import messages
from django.db.models import Q, Count, Sum, Avg
from django.utils import timezone
from django.utils.text import slugify
from django.http import Http404, HttpResponse, JsonResponse, HttpResponseForbidden
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from django.contrib.auth.models import User
from django.conf import settings
from datetime import timedelta, datetime
from decimal import Decimal
import json
import random
import hmac

from .models import (
    Course, Registration, Schedule, Instructor, Room, TimeSlot, Waitlist, Announcement, 
    FinanceProfile, MarketingProfile, UploadedImage,
    Student, LearningWeek, LearningMaterial, MaterialProgress,
    StudentWeekProgress,
    Program, Cohort,
    Quiz, QuizQuestion, QuizOption, QuizAttempt,
    Assessment, Rubric, RubricCriterion, AssessmentSubmission, SubmissionFile,
    Invoice, Payment, ApplicationDocument, ApplicationContract,
    StudentTask, AttendanceRecord, Event, LiveSession, StudentRequest,
    StudentMessageThread, StudentMessage, StudentNote, StudentGroup, StudentGroupMember,
    Notification,
    StudentCommunityPost, StudentCommunityComment, StudentPreference, SupportTicket,
    SupportTicketComment, SuccessStory,
    # Career Section Models - Phase 2B
    JobListing, JobApplication, Resume, TailoredResume, ResumeExperience, ResumeEducation,
    InterviewSet, InterviewQuestion, InterviewAttempt,
    LinkedInProfile, Badge, StudentBadge, Streak, Leaderboard,
    JobSource, JobSyncRun, AssessmentAttachment,
)
from .services import (
    eligible_assessments,
    eligible_weeks,
    has_course_access,
    student_activity_dates,
    student_progress_summary,
    sync_student_progress,
)
from .forms import (
    RegistrationForm, CourseForm, InstructorForm, AnnouncementForm, UploadedImageForm,
    LinkedInProfileForm,
)
from .utils import (
    generate_registration_pdf, export_courses_to_excel, send_registration_email, export_rows_to_excel,
    generate_resume_pdf,
)
from .decorators import get_user_role, role_required
from .material_uploads import validate_assessment_resource_upload, validate_material_upload
from .job_matching import extract_job_requirements, normalize_requirement, recommendation_score
from .job_sync import sync_job_source
from .linkedin_coach import (
    build_about, build_headline, completeness_items, profile_data,
    build_job_about, build_job_headline, job_profile_analysis, profile_recommendations,
)
from .achievement_service import (
    calculate_current_streak,
    calculate_student_points,
    evaluate_student_badges,
    refresh_cohort_leaderboard,
)
from .resume_review import analyze_resume


def create_notification(user, title, message='', target_url='', category='general'):
    """Create a persisted notification for a portal user."""
    return Notification.objects.create(
        user=user, title=title, message=message, target_url=target_url, category=category,
    )


def eligible_assessments_for_student(student):
    return eligible_assessments(student).filter(is_archived=False).order_by('due_date', 'title')

@never_cache
def custom_login(request):
    """Custom login view that accepts all users, not just staff"""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            next_url = request.POST.get('next')
            if next_url:
                return redirect(next_url)
            else:
                return redirect('crp:dashboard')
        else:
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'crp/login.html')

def custom_logout(request):
    """Custom logout view"""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('crp:login')

@login_required
def crp_dashboard(request):
    """Main dashboard that routes to appropriate role-based dashboard (CRP roles only)"""
    role = get_user_role(request.user)
    
    if role == 'admin':
        return admin_dashboard(request)
    elif role == 'trainer':
        return trainer_dashboard(request)
    elif role == 'admissions':
        return admissions_dashboard(request)
    elif role == 'finance':
        return admissions_finance_dashboard(request)
    else:  # student
        return student_dashboard(request)

@role_required('student')
def student_dashboard(request):
    """Student dashboard - redirect to new student portal"""
    return redirect('crp:student_portal')


@role_required('student')
def student_course_home(request, course_id):
    """Course-scoped home; every learning object is filtered through enrollment."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')

    course = get_object_or_404(Course.objects.select_related('instructor'), pk=course_id)
    if not has_course_access(student, course):
        return HttpResponseForbidden("Approved enrollment is required to access this course.")

    all_course_weeks = eligible_weeks(student, course).prefetch_related('materials', 'quiz', 'assessments')
    progress_rows, completed_weeks, current_week = student_progress_summary(student)
    progress_by_week = {row.week_id: row for row in progress_rows}
    weeks = [week for week in all_course_weeks if progress_by_week.get(week.id) and progress_by_week[week.id].status != 'locked']
    for week in weeks:
        week.display_progress = progress_by_week[week.id]
    course_week_ids = {week.id for week in weeks}
    course_progress = [row for row in progress_rows if row.week_id in course_week_ids]
    completed = sum(row.status == 'completed' for row in course_progress)
    progress = int(completed / len(course_progress) * 100) if course_progress else 0
    assessments = eligible_assessments(student).filter(week__course=course)
    return render(request, 'crp/student/course_home.html', {
        'student': student,
        'course': course,
        'weeks': weeks,
        'assessments': assessments,
        'current_week': current_week if current_week and current_week.course_id == course.id else None,
        'progress_percentage': progress,
        'completed_weeks': completed,
        'total_weeks': len(course_progress),
        'role': 'student',
    })


@role_required('student')
def student_course_week(request, course_id, week_id):
    student = get_object_or_404(Student, user=request.user)
    course = get_object_or_404(Course, pk=course_id)
    if not has_course_access(student, course):
        return HttpResponseForbidden("Approved enrollment is required to access this course.")
    week = get_object_or_404(
        eligible_weeks(student, course).prefetch_related('materials', 'assessments', 'quiz__questions'),
        pk=week_id,
        course=course,
    )
    progress = next((row for row in sync_student_progress(student) if row.week_id == week.id), None)
    if not progress or progress.status == 'locked':
        return HttpResponseForbidden("This week is not available yet.")
    materials = week.materials.filter(is_published=True, is_archived=False)
    assessments = week.assessments.filter(is_published=True, is_archived=False)
    quiz = getattr(week, 'quiz', None)
    if quiz and (not quiz.is_published or quiz.is_archived):
        quiz = None
    return render(request, 'crp/student/course_week.html', {
        'student': student, 'course': course, 'week': week, 'progress': progress,
        'materials': materials, 'assessments': assessments, 'quiz': quiz, 'role': 'student',
    })


@role_required('student')
@require_POST
def request_course_enrollment(request, course_id):
    course = get_object_or_404(Course, pk=course_id, status='active')
    existing = Registration.objects.filter(
        student=request.user,
        course=course,
        status__in=('pending', 'approved', 'completed'),
    ).first()
    if existing:
        messages.info(request, f"Your enrollment is already {existing.get_status_display().lower()}.")
        return redirect('crp:student_portal')
    Registration.objects.create(
        student=request.user,
        course=course,
        semester=request.POST.get('semester', str(timezone.now().year)),
        status='pending',
    )
    messages.success(request, "Enrollment request submitted for admin approval.")
    return redirect('crp:student_portal')

def _get_trainer_instructor(user):
    try:
        return user.instructor_profile
    except Instructor.DoesNotExist:
        return None


def _get_trainer_courses(user):
    instructor = _get_trainer_instructor(user)
    if not instructor:
        return Course.objects.none()
    return Course.objects.filter(Q(instructor=instructor) | Q(trainers=instructor)).distinct().select_related('department').annotate(
        student_count=Count('registrations', filter=Q(registrations__status='approved'))
    ).order_by('code')


def _trainer_students(user):
    """Return only students enrolled in one of the trainer's assigned courses."""
    courses = _get_trainer_courses(user)
    return Student.objects.filter(
        user__registrations__course__in=courses,
        user__registrations__status__in=('approved', 'completed'),
    ).distinct().select_related('user', 'cohort_relation__program')


def _trainer_cohorts(user):
    return Cohort.objects.filter(
        students__in=_trainer_students(user),
    ).distinct().select_related('program')


@role_required('trainer')
def trainer_dashboard(request):
    """Trainer/Instructor portal dashboard"""
    instructor = _get_trainer_instructor(request.user)
    if not instructor:
        messages.error(request, "No instructor profile found. Please contact administration.")
        return redirect('crp:dashboard')

    my_courses = _get_trainer_courses(request.user)
    my_schedules = Schedule.objects.filter(
        instructor=instructor
    ).select_related('course', 'room', 'time_slot').order_by('day', 'time_slot')

    total_students = _trainer_students(request.user).count()

    assigned_course_codes = list(my_courses.values_list('code', flat=True))
    recent_assessments = Assessment.objects.filter(course_code__in=assigned_course_codes).select_related('week').order_by('-due_date')[:5]
    recent_announcements = Announcement.objects.filter(course__in=my_courses).order_by('-created_at')[:5]

    assigned_students = _trainer_students(request.user)
    attention = []
    for student in assigned_students:
        scores = list(QuizAttempt.objects.filter(
            student=student, completed_at__isnull=False, score__isnull=False,
        ).values_list('score', flat=True))
        overdue = StudentTask.objects.filter(
            student=student, completed=False, due_date__lt=timezone.localdate(),
        ).count()
        average = int(sum(scores) / len(scores)) if scores else None
        if overdue or student.attendance_percentage < 80 or (average is not None and average < 60):
            if overdue:
                detail = f'{overdue} overdue task{"s" if overdue != 1 else ""}'
            elif student.attendance_percentage < 80:
                detail = f'{student.attendance_percentage}% attendance'
            else:
                detail = f'{average}% quiz average'
            attention.append({
                'student': student, 'score': average, 'detail': detail,
                'risk': 'High priority' if overdue > 1 or student.attendance_percentage < 70 else 'Monitor',
            })
    attention = attention[:5]
    assigned_student_ids = assigned_students.values_list('id', flat=True)
    trainer_tasks = StudentTask.objects.filter(
        student_id__in=assigned_student_ids, completed=False,
    ).select_related('student__user').order_by('due_date', '-created_at')[:5]
    scores = list(QuizAttempt.objects.filter(
        student_id__in=assigned_student_ids, completed_at__isnull=False, score__isnull=False,
    ).values_list('score', flat=True))
    average_quiz = int(sum(scores) / len(scores)) if scores else 0
    attendance = list(assigned_students.values_list('attendance_percentage', flat=True))
    average_attendance = int(sum(attendance) / len(attendance)) if attendance else 0
    context = {
        'instructor': instructor,
        'my_courses': my_courses,
        'my_schedules': my_schedules,
        'total_students': total_students,
        'recent_assessments': recent_assessments,
        'recent_announcements': recent_announcements,
        'attention': attention,
        'trainer_tasks': trainer_tasks,
        'cohort_stats': {
            'quiz_average': average_quiz,
            'attendance_average': average_attendance,
            'at_risk': len(attention),
            'awaiting_marks': AssessmentSubmission.objects.filter(
                assessment__course_code__in=assigned_course_codes,
                student__in=assigned_students, status='submitted',
            ).count(),
        },
        'role': 'trainer',
    }
    return render(request, 'crp/trainer_dashboard.html', context)


@role_required('trainer')
def trainer_courses(request):
    """List courses assigned to the logged-in trainer."""
    courses = _get_trainer_courses(request.user)
    context = {'courses': courses, 'role': 'trainer'}
    return render(request, 'crp/trainer/trainer_courses.html', context)


@role_required('trainer')
def trainer_course_detail(request, course_id):
    """Show one assigned course with roster, schedule, learning materials, and assessments."""
    course = get_object_or_404(
        Course.objects.select_related('department', 'instructor__user').filter(
            Q(instructor=request.user.instructor_profile)
            | Q(trainers=request.user.instructor_profile)
        ).distinct(),
        id=course_id,
    )
    return _render_trainer_course_detail(request, course)


@role_required('trainer')
def trainer_course_detail_slug(request, course_slug):
    """Show an assigned course using its readable name-based URL."""
    course = get_object_or_404(
        Course.objects.select_related('department', 'instructor__user').filter(
            Q(instructor=request.user.instructor_profile)
            | Q(trainers=request.user.instructor_profile)
        ).distinct(),
        slug=course_slug,
    )
    return _render_trainer_course_detail(request, course)


def _render_trainer_course_detail(request, course):
    """Build the trainer course workspace for an already-authorized course."""

    registrations = Registration.objects.filter(course=course, status='approved').select_related('student').order_by('student__last_name', 'student__first_name')
    students = []
    for registration in registrations:
        student_profile = Student.objects.filter(user=registration.student).first()
        students.append({
            'user': registration.student,
            'student': student_profile,
            'registration': registration,
        })

    schedules = Schedule.objects.filter(course=course).select_related('room', 'time_slot', 'instructor__user').order_by('day', 'time_slot')
    assessments = Assessment.objects.filter(course_code=course.code).select_related('week').order_by('week__week_number', 'due_date')
    materials = []
    assigned_weeks = LearningWeek.objects.filter(
        Q(assessments__course_code=course.code)
        | Q(program__cohorts__students__in=_trainer_students(request.user)),
    ).distinct().order_by('week_number')
    for week in assigned_weeks:
        week_materials = list(week.materials.all().order_by('order'))
        if week_materials:
            materials.append({'week': week, 'items': week_materials})
    quiz_items = Quiz.objects.filter(
        week__in=assigned_weeks,
    ).select_related('week').order_by('week__week_number')

    context = {
        'course': course,
        'students': students,
        'schedules': schedules,
        'assessments': assessments,
        'materials': materials,
        'quiz_items': quiz_items,
        'role': 'trainer',
    }
    return render(request, 'crp/trainer/trainer_course_detail.html', context)


@role_required('trainer')
def trainer_students(request):
    """List students in courses assigned to the trainer."""
    trainer_courses = _get_trainer_courses(request.user)
    course_ids = list(trainer_courses.values_list('id', flat=True))
    registrations = Registration.objects.filter(
        course_id__in=course_ids,
        status='approved',
    ).select_related('course', 'student').order_by('course__code', 'student__last_name', 'student__first_name')

    student_rows = []
    for registration in registrations:
        student_profile = Student.objects.filter(user=registration.student).first()
        if not student_profile:
            continue
        attempts = QuizAttempt.objects.filter(
            student=student_profile,
            completed_at__isnull=False,
            score__isnull=False,
        ).filter(
            Q(quiz__week__assessments__course_code=registration.course.code)
            | Q(quiz__week__program__cohorts__students=student_profile),
        ).distinct()
        scores = list(attempts.values_list('score', flat=True))
        quiz_average = int(sum(scores) / len(scores)) if scores else 0
        overdue_tasks = StudentTask.objects.filter(
            student=student_profile,
            completed=False,
            due_date__lt=timezone.localdate(),
        ).count()
        student_rows.append({
            'student': student_profile,
            'course': registration.course,
            'registration': registration,
            'quiz_average': quiz_average,
            'overdue_tasks': overdue_tasks,
            'risk': 'Monitor' if overdue_tasks else 'On track',
            'risk_class': 'warning' if overdue_tasks else 'success',
        })

    context = {
        'student_rows': student_rows,
        'courses': trainer_courses,
        'student_count': len(student_rows),
        'quiz_average': int(sum(r['quiz_average'] for r in student_rows) / len(student_rows)) if student_rows else 0,
        'attendance_average': int(sum(r['student'].attendance_percentage for r in student_rows) / len(student_rows)) if student_rows else 0,
        'at_risk_count': sum(1 for r in student_rows if r['risk_class'] != 'success'),
        'role': 'trainer',
    }
    return render(request, 'crp/trainer/trainer_students.html', context)


@role_required('trainer')
def trainer_student_detail(request, student_id):
    """Restrict student review to students enrolled in the trainer's courses."""
    instructor = request.user.instructor_profile
    trainer_courses = _get_trainer_courses(request.user)
    trainer_course_codes = list(trainer_courses.values_list('code', flat=True))

    student = get_object_or_404(Student.objects.select_related('user'), id=student_id)
    registrations = Registration.objects.filter(
        student=student.user,
        course__in=trainer_courses,
        status='approved',
    ).select_related('course', 'course__department').order_by('course__code')
    if not registrations:
        messages.error(request, "Student not assigned to any of your courses.")
        return redirect('crp:trainer_students')

    submissions = AssessmentSubmission.objects.filter(
        student=student,
        assessment__course_code__in=trainer_course_codes,
    ).select_related('assessment')
    attempts = QuizAttempt.objects.filter(
        student=student,
    ).filter(
        Q(quiz__week__course__in=trainer_courses)
        | Q(quiz__week__assessments__course_code__in=trainer_course_codes)
    ).distinct().select_related('quiz__week').order_by('-completed_at')

    context = {
        'student': student,
        'registrations': registrations,
        'submissions': submissions,
        'quiz_attempts': attempts,
        'instructor': instructor,
        'role': 'trainer',
    }
    return render(request, 'crp/trainer/trainer_student_detail.html', context)


@role_required('trainer')
def trainer_assessments(request):
    """List all assessments for courses assigned to the trainer."""
    trainer_courses = _get_trainer_courses(request.user)
    course_codes = list(trainer_courses.values_list('code', flat=True))
    assessments = Assessment.objects.filter(course_code__in=course_codes).select_related('week', 'course').annotate(
        submission_count=Count('submissions'),
        marked_count=Count('submissions', filter=Q(submissions__status='marked')),
        attachment_count=Count('attachments', distinct=True),
    )
    search = request.GET.get('q', '').strip()
    if search:
        assessments = assessments.filter(title__icontains=search)
    if request.GET.get('course'):
        assessments = assessments.filter(course_id=request.GET['course'])
    if request.GET.get('week'):
        assessments = assessments.filter(week_id=request.GET['week'])
    if request.GET.get('type'):
        assessments = assessments.filter(assessment_type=request.GET['type'])
    if request.GET.get('status') == 'archived':
        assessments = assessments.filter(is_archived=True)
    elif request.GET.get('status') == 'published':
        assessments = assessments.filter(is_published=True, is_archived=False)
    elif request.GET.get('status') == 'draft':
        assessments = assessments.filter(is_published=False, is_archived=False)
    assessments = assessments.order_by('week__week_number', 'due_date')
    weeks = LearningWeek.objects.filter(
        course__in=trainer_courses,
        is_archived=False,
    ).select_related('course').order_by('course__code', 'week_number')
    context = {
        'assessments': assessments,
        'courses': trainer_courses,
        'weeks': weeks,
        'assessment_types': Assessment.ASSESSMENT_TYPES,
        'role': 'trainer',
        'filters': request.GET,
        'now': timezone.now(),
    }
    return render(request, 'crp/trainer/trainer_assessments.html', context)


def _trainer_assessment_for_request(request, assessment_id):
    return get_object_or_404(
        Assessment.objects.select_related('week', 'course'),
        id=assessment_id,
        course_code__in=_get_trainer_courses(request.user).values('code'),
    )


@role_required('trainer')
def trainer_assessment_save(request, assessment_id=None):
    if request.method != 'POST':
        return redirect('crp:trainer_assessments')
    courses = _get_trainer_courses(request.user)
    week = get_object_or_404(LearningWeek, id=request.POST.get('week'), course__in=courses, is_archived=False)
    title = request.POST.get('title', '').strip()
    try:
        due_date = timezone.make_aware(datetime.fromisoformat(request.POST.get('due_date', '')))
        max_marks = int(request.POST.get('max_marks', '0'))
        weight = int(request.POST.get('weight_percentage', '0'))
    except (ValueError, TypeError):
        messages.error(request, 'Enter a valid due date, maximum marks, and weighting.')
        return redirect('crp:trainer_assessments')
    if not title or due_date <= timezone.now() or max_marks <= 0 or not 1 <= weight <= 100:
        messages.error(request, 'Title, future due date, positive maximum marks, and weighting from 1 to 100 are required.')
        return redirect('crp:trainer_assessments')
    assessment = _trainer_assessment_for_request(request, assessment_id) if assessment_id else Assessment()
    assessment.week = week
    assessment.course = week.course
    assessment.course_code = week.course.code
    assessment.title = title
    assessment.assessment_type = request.POST.get('assessment_type', 'assignment')
    assessment.due_date = due_date
    assessment.max_marks = max_marks
    assessment.weight_percentage = weight
    assessment.description = request.POST.get('description', '').strip()
    assessment.instructions = request.POST.get('instructions', '').strip()
    assessment.accepted_formats = request.POST.getlist('accepted_formats')
    assessment.required_submission = request.POST.get('required_submission') == 'on'
    assessment.required_file_count = max(1, int(request.POST.get('required_file_count') or 1))
    assessment.max_file_size_mb = max(1, int(request.POST.get('max_file_size_mb') or 500))
    assessment.save()
    for uploaded_file in request.FILES.getlist('resources'):
        try:
            validate_assessment_resource_upload(uploaded_file)
        except ValidationError as exc:
            messages.error(request, str(exc))
            continue
        AssessmentAttachment.objects.create(
            assessment=assessment,
            file=uploaded_file,
            original_filename=uploaded_file.name.rsplit('\\', 1)[-1].rsplit('/', 1)[-1][:255],
            uploaded_by=request.user,
        )
    messages.success(request, 'Assignment saved.')
    return redirect('crp:trainer_assessments')


@role_required('trainer')
def trainer_assessment_publish(request, assessment_id):
    if request.method == 'POST':
        assessment = _trainer_assessment_for_request(request, assessment_id)
        if not assessment.is_archived:
            assessment.is_published = True
            assessment.save(update_fields=['is_published', 'updated_at'])
            messages.success(request, 'Assignment published.')
    return redirect('crp:trainer_assessments')


@role_required('trainer')
def trainer_assessment_archive(request, assessment_id):
    if request.method == 'POST':
        assessment = _trainer_assessment_for_request(request, assessment_id)
        assessment.is_archived = True
        assessment.is_published = False
        assessment.save(update_fields=['is_archived', 'is_published', 'updated_at'])
        messages.success(request, 'Assignment archived.')
    return redirect('crp:trainer_assessments')


@role_required('trainer')
def trainer_assessment_attachment_remove(request, attachment_id):
    if request.method == 'POST':
        attachment = get_object_or_404(
            AssessmentAttachment,
            id=attachment_id,
            assessment__course_code__in=_get_trainer_courses(request.user).values('code'),
        )
        attachment.file.delete(save=False)
        attachment.delete()
        messages.success(request, 'Resource removed.')
    return redirect('crp:trainer_assessment_detail', assessment_id=attachment.assessment_id)


@login_required
def assessment_attachment_download(request, attachment_id):
    attachment = get_object_or_404(
        AssessmentAttachment.objects.select_related('assessment'),
        id=attachment_id,
    )
    role = get_user_role(request.user)
    if role == 'trainer':
        allowed = attachment.assessment.course_code in _get_trainer_courses(request.user).values_list('code', flat=True)
    elif role == 'student':
        allowed = eligible_assessments(request.user.student_profile).filter(id=attachment.assessment_id).exists()
    else:
        allowed = role == 'admin'
    if not allowed:
        raise Http404
    return redirect(attachment.file.url)


@role_required('trainer')
def trainer_assessment_detail(request, assessment_id):
    """View one assessment and all student submissions for the assigned course."""
    trainer_courses = _get_trainer_courses(request.user)
    trainer_course_codes = list(trainer_courses.values_list('code', flat=True))
    assessment = get_object_or_404(Assessment.objects.select_related('week'), id=assessment_id)
    if assessment.course_code not in trainer_course_codes:
        messages.error(request, "This assessment is not in your assigned courses.")
        return redirect('crp:trainer_assessments')
    if request.method == 'POST' and request.POST.get('action') == 'upload_resource':
        for uploaded_file in request.FILES.getlist('resources'):
            try:
                validate_assessment_resource_upload(uploaded_file)
            except ValidationError as exc:
                messages.error(request, str(exc))
                continue
            AssessmentAttachment.objects.create(
                assessment=assessment,
                file=uploaded_file,
                original_filename=uploaded_file.name.rsplit('\\', 1)[-1].rsplit('/', 1)[-1][:255],
                uploaded_by=request.user,
            )
        messages.success(request, 'Resources uploaded.')
        return redirect('crp:trainer_assessment_detail', assessment_id=assessment.id)

    rubric = getattr(assessment, 'rubric', None)
    submissions = AssessmentSubmission.objects.filter(
        assessment=assessment, student__in=_trainer_students(request.user),
    ).select_related('student__user').order_by('-submitted_at')
    context = {
        'assessment': assessment,
        'rubric': rubric,
        'submissions': submissions,
        'attachments': assessment.attachments.all(),
        'role': 'trainer',
    }
    return render(request, 'crp/trainer/trainer_assessment_detail.html', context)


@role_required('trainer')
def trainer_submission_detail(request, submission_id):
    """Review a specific student submission and mark it if appropriate."""
    trainer_courses = _get_trainer_courses(request.user)
    trainer_course_codes = list(trainer_courses.values_list('code', flat=True))
    submission = get_object_or_404(
        AssessmentSubmission.objects.select_related('student__user', 'assessment__week'),
        id=submission_id, student__in=_trainer_students(request.user),
    )
    if submission.assessment.course_code not in trainer_course_codes:
        messages.error(request, "You do not have access to this submission.")
        return redirect('crp:trainer_assessments')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'grade':
            marks = request.POST.get('marks_awarded')
            feedback = request.POST.get('feedback', '').strip()
            if marks not in ('', None):
                submission.marks_awarded = int(marks)
            submission.feedback = feedback
            submission.status = 'marked'
            submission.marked_at = timezone.now()
            submission.save()
            messages.success(request, 'Submission marked successfully.')
            return redirect('crp:trainer_submission_detail', submission_id=submission.id)

    context = {
        'submission': submission,
        'files': submission.files.all(),
        'role': 'trainer',
    }
    return render(request, 'crp/trainer/trainer_submission_detail.html', context)


@role_required('trainer')
def trainer_learning_content(request):
    """View learning content for the trainer's assigned courses."""
    trainer_courses = _get_trainer_courses(request.user)
    course_codes = list(trainer_courses.values_list('code', flat=True))

    relevant_weeks = LearningWeek.objects.filter(
        Q(course__in=trainer_courses)
        | Q(assessments__course_code__in=course_codes)
    ).distinct().order_by('week_number')

    course_rows = []
    scoped_materials = LearningMaterial.objects.filter(week__in=relevant_weeks)
    for course in trainer_courses:
        course_weeks = relevant_weeks.filter(
            Q(course=course)
            | Q(assessments__course_code=course.code),
        ).distinct().order_by('week_number')
        week_items = []
        for week in course_weeks:
            materials = LearningMaterial.objects.filter(week=week).select_related('week').order_by('order')
            if materials.exists():
                week_items.append({'week': week, 'materials': materials})
        course_rows.append({'course': course, 'weeks': week_items})

    context = {
        'courses': trainer_courses,
        'course_rows': course_rows,
        'weeks': relevant_weeks,
        'material_count': scoped_materials.count(),
        'published_material_count': scoped_materials.filter(is_published=True).count(),
        'hidden_material_count': scoped_materials.filter(is_published=False).count(),
        'video_material_count': scoped_materials.filter(material_type='video').count(),
        'role': 'trainer',
    }
    return render(request, 'crp/trainer/trainer_learning_content.html', context)


@role_required('trainer')
def trainer_quizzes(request):
    """List quiz activity for assigned courses and their students."""
    trainer_courses = _get_trainer_courses(request.user)
    course_codes = list(trainer_courses.values_list('code', flat=True))
    relevant_weeks = LearningWeek.objects.filter(
        Q(course__in=trainer_courses)
        | Q(assessments__course_code__in=course_codes)
    ).distinct().order_by('week_number')

    trainer_quiz_rows = []
    for quiz in Quiz.objects.filter(week__in=relevant_weeks).select_related('week').order_by('week__week_number'):
        attempts = QuizAttempt.objects.filter(
            quiz=quiz, student__in=_trainer_students(request.user),
        ).select_related('student__user').order_by('-completed_at')
        trainer_quiz_rows.append({'quiz': quiz, 'attempts': attempts, 'attempt_count': attempts.count()})

    context = {'quizzes': trainer_quiz_rows, 'courses': trainer_courses, 'role': 'trainer'}
    return render(request, 'crp/trainer/trainer_quizzes.html', context)


@role_required('trainer')
def trainer_quiz_detail(request, quiz_id):
    """View a quiz and results for that quiz within assigned courses only."""
    trainer_courses = _get_trainer_courses(request.user)
    course_codes = list(trainer_courses.values_list('code', flat=True))
    quiz = get_object_or_404(Quiz.objects.select_related('week'), id=quiz_id)

    if not quiz.week.assessments.filter(course_code__in=course_codes).exists():
        messages.error(request, 'This quiz is not in one of your assigned courses.')
        return redirect('crp:trainer_quizzes')

    attempts = QuizAttempt.objects.filter(
        quiz=quiz, student__in=_trainer_students(request.user),
    ).select_related('student__user').order_by('-completed_at')
    context = {'quiz': quiz, 'attempts': attempts, 'role': 'trainer'}
    return render(request, 'crp/trainer/trainer_quiz_detail.html', context)


@role_required('trainer')
def trainer_announcements(request):
    """View and create announcements for the trainer's courses."""
    trainer_courses = _get_trainer_courses(request.user)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            course_id = request.POST.get('course')
            course = get_object_or_404(Course, id=course_id, instructor=request.user.instructor_profile)
            title = request.POST.get('title', '').strip()
            content = request.POST.get('content', '').strip()
            priority = request.POST.get('priority', 'normal')
            if title and content:
                Announcement.objects.create(
                    title=title,
                    content=content,
                    course=course,
                    author=request.user,
                    priority=priority,
                    published=True,
                )
                messages.success(request, 'Announcement created successfully.')
                return redirect('crp:trainer_announcements')
            messages.error(request, 'Title and content are required.')

    trainer_cohorts = _trainer_cohorts(request.user)
    announcements = Announcement.objects.filter(
        Q(course__in=trainer_courses)
        | Q(cohort__in=trainer_cohorts)
        | Q(program_id__in=trainer_cohorts.values('program_id')),
    ).distinct().select_related('course', 'author').order_by('-created_at')
    context = {'announcements': announcements, 'courses': trainer_courses, 'role': 'trainer'}
    return render(request, 'crp/trainer/trainer_announcements.html', context)


@role_required('trainer')
def trainer_announcement_delete(request, announcement_id):
    announcement = get_object_or_404(
        Announcement,
        id=announcement_id,
        course__in=_get_trainer_courses(request.user),
        author=request.user,
    )
    if request.method == 'POST':
        announcement.delete()
        messages.success(request, 'Announcement deleted.')
    return redirect('crp:trainer_announcements')


@role_required('trainer')
def trainer_schedule(request):
    """View the trainer schedule and assigned sessions."""
    instructor = request.user.instructor_profile
    schedules = Schedule.objects.filter(instructor=instructor).select_related('course', 'room', 'time_slot').order_by('day', 'time_slot')
    context = {'schedules': schedules, 'role': 'trainer'}
    return render(request, 'crp/trainer/trainer_schedule.html', context)


def _trainer_operation_context(request, title, subtitle, records, students=None):
    students = students if students is not None else _trainer_students(request.user)
    rows = []
    for record in records:
        student = getattr(record, 'student', None)
        if isinstance(record, AttendanceRecord):
            course = record.schedule.course.code if record.schedule else 'Ad-hoc'
            rows.append({
                'label': student.user.get_full_name() if student else str(record),
                'meta': f'{record.session_date} · {course}',
                'value': record.get_status_display(),
                'status': record.get_status_display(),
                'status_class': 'success' if record.status in ('present', 'excused') else
                                ('warning' if record.status == 'late' else 'danger'),
                'id': record.id,
            })
            continue
        label = getattr(record, 'title', None) or getattr(record, 'name', None)
        if not label and student:
            label = student.user.get_full_name() or student.user.username
        rows.append({'label': label or str(record), 'meta': str(getattr(record, 'notes', '') or ''),
                     'value': getattr(record, 'status', '') or '', 'status': 'Open',
                     'status_class': 'info', 'id': getattr(record, 'id', None)})
    return {'module_title': title, 'module_subtitle': subtitle, 'module': 'operations',
            'summary_cards': [(str(len(rows)), 'Records in scope'), (str(students.count()), 'Assigned students')],
            'records': rows, 'students': students, 'role': 'trainer'}


@role_required('trainer')
def trainer_task_manager(request):
    """Assign, edit, remove and complete tasks for one or more assigned students."""
    students = _trainer_students(request.user)
    student_ids = set(students.values_list('id', flat=True))
    if request.method == 'POST':
        action = request.POST.get('action', 'create')
        task = None
        if action == 'create':
            target = request.POST.get('target', 'student')
            ids = request.POST.getlist('student_ids') or request.POST.getlist('student')
            if target == 'cohort':
                cohort_id = request.POST.get('cohort_id')
                ids = list(students.filter(cohort_relation_id=cohort_id).values_list('id', flat=True))
            ids = [int(value) for value in ids if str(value).isdigit() and int(value) in student_ids]
            title = (request.POST.get('title') or '').strip()
            if not ids or not title:
                messages.error(request, 'Select at least one student and provide a title.')
            else:
                for student_id in ids:
                    StudentTask.objects.create(
                        student_id=student_id, title=title,
                        description=request.POST.get('description', '').strip(),
                        due_date=request.POST.get('due_date') or None,
                        priority=request.POST.get('priority', 'medium'),
                        tag='Trainer', created_by=request.user.get_username())
                messages.success(request, f'Task assigned to {len(ids)} student(s).')
        elif action in ('edit', 'delete', 'complete'):
            task = get_object_or_404(StudentTask, id=request.POST.get('task_id'), student_id__in=student_ids)
            if action == 'delete':
                task.delete()
            elif action == 'complete':
                task.completed = request.POST.get('completed', 'true').lower() in ('true', '1', 'on')
                task.completed_at = timezone.now() if task.completed else None
                task.save(update_fields=['completed', 'completed_at', 'updated_at'])
            else:
                task.title = (request.POST.get('title') or task.title).strip()
                task.description = request.POST.get('description', task.description)
                task.due_date = request.POST.get('due_date') or None
                task.priority = request.POST.get('priority', task.priority)
                task.save()
        return redirect('crp:trainer_task_manager')
    tasks = StudentTask.objects.filter(student_id__in=student_ids).select_related('student__user')
    context = _trainer_operation_context(request, 'Task Manager', 'Assign and track student tasks.', tasks, students)
    context.update({'tasks': tasks, 'cohorts': _trainer_cohorts(request.user), 'operation': 'tasks'})
    return render(request, 'crp/trainer/trainer_reference_module.html', context)


@role_required('trainer')
def trainer_attendance(request):
    """Manage a dated attendance roll and keep student percentages in sync."""
    trainer_students = _trainer_students(request.user)
    schedules = Schedule.objects.filter(
        Q(instructor=request.user.instructor_profile) | Q(course__trainers=request.user.instructor_profile)
    ).distinct().select_related('course')
    course_id = request.GET.get('course_id') or request.POST.get('course_id') or ''
    selected_course = get_object_or_404(
        _get_trainer_courses(request.user), id=course_id
    ) if str(course_id).isdigit() else None
    selected_schedule_id = request.GET.get('schedule_id') or request.POST.get('schedule_id') or ''
    selected_schedule = get_object_or_404(schedules, id=selected_schedule_id) if str(selected_schedule_id).isdigit() else None
    if selected_schedule:
        selected_course = selected_schedule.course
    students = trainer_students.filter(
        user__registrations__course=selected_course,
        user__registrations__status__in=('approved', 'completed'),
    ).distinct() if selected_course else trainer_students.none()
    student_ids = list(students.values_list('id', flat=True))
    session_date = request.GET.get('date') or request.POST.get('session_date') or timezone.localdate().isoformat()
    if request.method == 'POST':
        schedule = selected_schedule
        if not selected_course or not students.exists():
            messages.error(request, 'Select an assigned course with enrolled students.')
            return redirect('crp:trainer_attendance')
        for student in students:
            status = request.POST.get(f'status_{student.id}', 'absent')
            if status not in dict(AttendanceRecord.STATUS_CHOICES):
                continue
            AttendanceRecord.objects.update_or_create(
                student=student, schedule=schedule, session_date=session_date,
                defaults={'status': status, 'notes': request.POST.get(f'notes_{student.id}', ''),
                          'recorded_by': request.user})
        for student in students:
            records = AttendanceRecord.objects.filter(student=student)
            total = records.count()
            attended = records.filter(status__in=('present', 'late', 'excused')).count()
            student.attendance_percentage = round(attended * 100 / total) if total else 0
            student.save(update_fields=['attendance_percentage', 'updated_at'])
        messages.success(request, 'Attendance roll saved.')
        return redirect(f"{reverse_lazy('crp:trainer_attendance')}?date={session_date}")
    # Filters are deliberately applied after scoping to this trainer's students.
    cohorts = _trainer_cohorts(request.user)
    selected_cohort = request.GET.get('cohort_id', '')
    selected_student = request.GET.get('student_id', '')
    selected_status = request.GET.get('status', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    records = AttendanceRecord.objects.filter(student_id__in=student_ids)
    if selected_cohort.isdigit():
        records = records.filter(student__cohort_relation_id=int(selected_cohort))
    if selected_student.isdigit():
        records = records.filter(student_id=int(selected_student))
    if selected_status in dict(AttendanceRecord.STATUS_CHOICES):
        records = records.filter(status=selected_status)
    if start_date:
        records = records.filter(session_date__gte=start_date)
    if end_date:
        records = records.filter(session_date__lte=end_date)
    if not any((selected_cohort, selected_student, selected_status, start_date, end_date)):
        records = records.filter(session_date=session_date)
    records = records.select_related('student__user', 'student__cohort_relation', 'schedule__course').order_by('-session_date', 'student__user__last_name')
    context = _trainer_operation_context(request, 'Attendance', 'Mark and review the session roll.', records, students)
    context.update({'attendance_records': records, 'schedules': schedules, 'session_date': session_date,
                    'courses': _get_trainer_courses(request.user), 'selected_course': selected_course,
                    'selected_schedule': selected_schedule,
                    'operation': 'attendance', 'cohorts': cohorts, 'selected_cohort': selected_cohort,
                    'selected_student': selected_student, 'selected_status': selected_status,
                    'start_date': start_date, 'end_date': end_date})
    return render(request, 'crp/trainer/trainer_reference_module.html', context)


def _trainer_report_queryset(request):
    """Return trainer-scoped students and the common report filters."""
    students = _trainer_students(request.user)
    params = request.GET
    cohort_id, student_id = params.get('cohort_id', ''), params.get('student_id', '')
    if cohort_id.isdigit():
        students = students.filter(cohort_relation_id=int(cohort_id))
    if student_id.isdigit():
        students = students.filter(id=int(student_id))
    return students, params


@role_required('trainer')
def trainer_report_export(request, report_type):
    """Export trainer reports without exposing records outside assigned courses."""
    students, params = _trainer_report_queryset(request)
    student_ids = list(students.values_list('id', flat=True))
    headers, rows, filename = [], [], f'{report_type}_report.xlsx'
    if report_type == 'attendance':
        records = AttendanceRecord.objects.filter(student_id__in=student_ids)
        if params.get('status') in dict(AttendanceRecord.STATUS_CHOICES):
            records = records.filter(status=params['status'])
        if params.get('start_date'):
            records = records.filter(session_date__gte=params['start_date'])
        if params.get('end_date'):
            records = records.filter(session_date__lte=params['end_date'])
        records = records.select_related('student__user', 'schedule__course').order_by('session_date')
        headers = ['Date', 'Student', 'Cohort', 'Course', 'Status', 'Notes']
        rows = [[r.session_date, r.student.user.get_full_name(), str(r.student.cohort_relation or ''),
                  r.schedule.course.code if r.schedule else '', r.get_status_display(), r.notes] for r in records]
    elif report_type == 'tasks':
        records = StudentTask.objects.filter(student_id__in=student_ids).select_related('student__user')
        headers = ['Student', 'Task', 'Due date', 'Status', 'Priority', 'Completed at']
        rows = [[r.student.user.get_full_name(), r.title, r.due_date,
                 'Completed' if r.completed else 'Open', r.get_priority_display(), r.completed_at] for r in records]
    elif report_type == 'assessments':
        records = AssessmentSubmission.objects.filter(student_id__in=student_ids).select_related('student__user', 'assessment')
        headers = ['Student', 'Assessment', 'Course', 'Status', 'Marks', 'Submitted at', 'Late']
        rows = [[r.student.user.get_full_name(), r.assessment.title, r.assessment.course_code,
                  r.get_status_display(), r.marks_awarded, r.submitted_at, 'Yes' if r.is_late else 'No'] for r in records]
    elif report_type == 'progress':
        headers = ['Student', 'Cohort', 'Attendance %', 'Tasks completed', 'Tasks total', 'Weeks completed', 'Weeks total']
        for student in students.select_related('user', 'cohort_relation'):
            tasks = StudentTask.objects.filter(student=student)
            weeks = StudentWeekProgress.objects.filter(student=student)
            rows.append([student.user.get_full_name(), str(student.cohort_relation or ''), student.attendance_percentage,
                         tasks.filter(completed=True).count(), tasks.count(),
                         weeks.filter(status='completed').count(), weeks.count()])
        filename = 'student_progress_report.xlsx'
    elif report_type == 'cohort-summary':
        headers = ['Cohort', 'Students', 'Average attendance %', 'Tasks completed', 'Tasks total', 'Weeks completed', 'Weeks total']
        for cohort in _trainer_cohorts(request.user):
            cohort_students = students.filter(cohort_relation=cohort)
            task_qs = StudentTask.objects.filter(student__in=cohort_students)
            week_qs = StudentWeekProgress.objects.filter(student__in=cohort_students)
            attendance = list(cohort_students.values_list('attendance_percentage', flat=True))
            rows.append([str(cohort), cohort_students.count(), round(sum(attendance) / len(attendance)) if attendance else 0,
                         task_qs.filter(completed=True).count(), task_qs.count(),
                         week_qs.filter(status='completed').count(), week_qs.count()])
        filename = 'cohort_summary_report.xlsx'
    else:
        return HttpResponseForbidden('Unknown report type')
    content = export_rows_to_excel(headers, rows, title=report_type.replace('-', ' ').title())
    response = HttpResponse(content, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@role_required('trainer')
def trainer_risk_workflow(request):
    """Review early-warning students and log an intervention as a support request."""
    students = _trainer_students(request.user)
    at_risk = students.filter(Q(attendance_percentage__lt=80) | Q(tasks__completed=False)).distinct()
    if request.method == 'POST':
        student = get_object_or_404(at_risk, id=request.POST.get('student_id'))
        StudentRequest.objects.create(
            student=student, request_type='academic',
            subject=request.POST.get('subject', 'Trainer intervention').strip(),
            description=request.POST.get('description', '').strip() or 'Follow-up required.',
            status='in_progress')
        messages.success(request, 'Intervention logged.')
        return redirect('crp:trainer_risk_workflow')
    requests = StudentRequest.objects.filter(student__in=at_risk).select_related('student__user')
    context = _trainer_operation_context(request, 'At Risk', 'Prioritise students and log interventions.', requests, students)
    context.update({'at_risk_students': at_risk, 'support_requests': requests, 'operation': 'risk'})
    return render(request, 'crp/trainer/trainer_reference_module.html', context)


@role_required('trainer')
def trainer_communications(request):
    """Send a scoped announcement or direct message to a course/cohort audience."""
    students = _trainer_students(request.user)
    if request.method == 'POST':
        audience = request.POST.get('audience', 'cohort')
        if audience == 'course':
            course = get_object_or_404(_get_trainer_courses(request.user), id=request.POST.get('course_id'))
            recipients = students.filter(user__registrations__course=course).distinct()
            announcement_kwargs = {'course': course}
        else:
            cohort = get_object_or_404(_trainer_cohorts(request.user), id=request.POST.get('cohort_id'))
            recipients = students.filter(cohort_relation=cohort)
            announcement_kwargs = {'cohort': cohort, 'program': cohort.program}
        title = (request.POST.get('title') or '').strip()
        content = (request.POST.get('content') or '').strip()
        if title and content:
            if request.POST.get('channel', 'announcement') == 'message':
                for student in recipients:
                    thread, _ = StudentMessageThread.objects.get_or_create(
                        student=student, trainer=request.user, defaults={'title': title})
                    StudentMessage.objects.create(thread=thread, sender=request.user,
                                                  recipient=student.user, content=content)
                    thread.save(update_fields=['updated_at'])
                    create_notification(
                        student.user,
                        f'New message from {request.user.get_full_name() or request.user.username}',
                        content[:200], reverse('crp:student_messages'), 'message',
                    )
            else:
                Announcement.objects.create(title=title, content=content, author=request.user, **announcement_kwargs)
                for student in recipients.select_related('user'):
                    create_notification(
                        student.user, 'New announcement', title,
                        reverse('crp:student_announcements'), 'announcement',
                    )
            messages.success(request, f'Communication sent to {recipients.count()} student(s).')
        return redirect('crp:trainer_communications')
    context = _trainer_operation_context(request, 'Bulk Comms', 'Communicate with a scoped student audience.', [], students)
    context.update({'cohorts': _trainer_cohorts(request.user), 'courses': _get_trainer_courses(request.user), 'operation': 'comms'})
    return render(request, 'crp/trainer/trainer_reference_module.html', context)


@role_required('trainer')
def trainer_messages(request):
    """Trainer-facing conversation inbox (kept separate from student messaging)."""
    return trainer_reference_module(request, 'messages')


@role_required('trainer')
def trainer_reference_module(request, module):
    """Render trainer workspace modules from records in the trainer's scope."""
    courses = _get_trainer_courses(request.user)
    course_codes = list(courses.values_list('code', flat=True))
    students = _trainer_students(request.user)
    student_ids = students.values_list('id', flat=True)
    cohorts = _trainer_cohorts(request.user)
    cohort_ids = cohorts.values_list('id', flat=True)
    assessments = Assessment.objects.filter(course_code__in=course_codes).select_related('week')
    schedules = Schedule.objects.filter(
        Q(instructor=request.user.instructor_profile) | Q(course__trainers=request.user.instructor_profile),
    ).select_related('course', 'room', 'time_slot')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create_task':
            title = request.POST.get('title', '').strip()
            targets = request.POST.getlist('student_ids') or [request.POST.get('student')]
            if request.POST.get('target') == 'cohort':
                targets = list(students.filter(cohort_relation_id=request.POST.get('cohort_id')).values_list('id', flat=True))
            for student_id in targets:
                if title and str(student_id).isdigit() and int(student_id) in student_ids:
                    StudentTask.objects.create(
                        student_id=student_id, title=title,
                        description=request.POST.get('description', '').strip(),
                        due_date=request.POST.get('due_date') or None,
                        priority=request.POST.get('priority', 'medium'),
                        tag='Trainer', created_by=request.user.get_username(),
                    )
        elif action in ('edit_task', 'delete_task', 'complete_task'):
            task = get_object_or_404(StudentTask, id=request.POST.get('task_id'), student_id__in=student_ids)
            if action == 'delete_task':
                task.delete()
            elif action == 'complete_task':
                task.completed = request.POST.get('completed', 'true').lower() in ('true', '1', 'on')
                task.completed_at = timezone.now() if task.completed else None
                task.save(update_fields=['completed', 'completed_at', 'updated_at'])
            else:
                task.title = request.POST.get('title', task.title).strip() or task.title
                task.description = request.POST.get('description', task.description)
                task.due_date = request.POST.get('due_date') or None
                task.priority = request.POST.get('priority', task.priority)
                task.save()
        elif action == 'create_note':
            student = get_object_or_404(Student, id=request.POST.get('student'), id__in=student_ids)
            title = request.POST.get('title', '').strip()
            content = request.POST.get('content', '').strip()
            if title and content:
                StudentNote.objects.create(
                    student=student, author=request.user, title=title, content=content,
                    is_published=request.POST.get('published') == 'on',
                )
        elif action == 'send_message':
            student = get_object_or_404(Student, id=request.POST.get('student'), id__in=student_ids)
            content = request.POST.get('content', '').strip()
            if content:
                thread, _ = StudentMessageThread.objects.get_or_create(
                    student=student, trainer=request.user,
                    defaults={'title': request.POST.get('title', '').strip()},
                )
                StudentMessage.objects.create(
                    thread=thread, sender=request.user, recipient=student.user, content=content,
                )
                thread.save(update_fields=['updated_at'])
                create_notification(
                    student.user, f'New message from {request.user.get_full_name() or request.user.username}',
                    content[:200], reverse('crp:student_messages'), 'message',
                )
        elif action == 'create_group':
            cohort = get_object_or_404(Cohort, id=request.POST.get('cohort'), id__in=cohort_ids)
            name = request.POST.get('name', '').strip()
            if name:
                StudentGroup.objects.create(
                    name=name, description=request.POST.get('description', '').strip(), cohort=cohort,
                )
        elif action == 'create_live_session':
            cohort = get_object_or_404(Cohort, id=request.POST.get('cohort'), id__in=cohort_ids)
            title = request.POST.get('title', '').strip()
            starts_at = request.POST.get('starts_at')
            if title and starts_at:
                starts_at = timezone.make_aware(datetime.fromisoformat(starts_at))
                session = LiveSession.objects.create(
                    title=title, description=request.POST.get('description', '').strip(),
                    cohort=cohort, program=cohort.program, starts_at=starts_at,
                    meeting_url=request.POST.get('meeting_url', '').strip(),
                    is_published=request.POST.get('is_published', request.POST.get('published')) == 'on',
                )
                if session.is_published:
                    for student in students.filter(cohort_relation=cohort).select_related('user'):
                        create_notification(
                            student.user, 'New live session', session.title,
                            reverse('crp:student_live_sessions'), 'live-session',
                        )
        elif action == 'edit_live_session':
            session = get_object_or_404(LiveSession, id=request.POST.get('session_id'), cohort_id__in=cohort_ids)
            session.title = request.POST.get('title', '').strip()
            session.description = request.POST.get('description', '').strip()
            session.starts_at = timezone.make_aware(datetime.fromisoformat(request.POST['starts_at']))
            session.meeting_url = request.POST.get('meeting_url', '').strip()
            session.recording_url = request.POST.get('recording_url', '').strip()
            session.is_published = request.POST.get('is_published') == 'on'
            session.is_archived = request.POST.get('is_archived') == 'on'
            session.save()
            if session.is_published:
                for student in students.filter(cohort_relation=session.cohort).select_related('user'):
                    create_notification(
                        student.user, 'Live session updated', session.title,
                        reverse('crp:student_live_sessions'), 'live-session',
                    )
        elif action == 'delete_live_session':
            session = get_object_or_404(LiveSession, id=request.POST.get('session_id'), cohort_id__in=cohort_ids)
            session.is_archived = True
            session.save(update_fields=['is_archived', 'updated_at'])
        elif action == 'edit_group':
            group = get_object_or_404(StudentGroup, id=request.POST.get('group_id'), cohort_id__in=cohort_ids)
            group.name = request.POST.get('name', '').strip()
            group.description = request.POST.get('description', '').strip()
            group.save(update_fields=['name', 'description', 'updated_at'])
        elif action == 'archive_group':
            group = get_object_or_404(StudentGroup, id=request.POST.get('group_id'), cohort_id__in=cohort_ids)
            group.is_archived = request.POST.get('is_archived') == 'on'
            group.save(update_fields=['is_archived', 'updated_at'])
        elif action == 'delete_group':
            get_object_or_404(StudentGroup, id=request.POST.get('group_id'), cohort_id__in=cohort_ids).delete()
        elif action in ('add_group_member', 'remove_group_member', 'set_group_leader'):
            group = get_object_or_404(StudentGroup, id=request.POST.get('group_id'), cohort_id__in=cohort_ids)
            student = get_object_or_404(Student, id=request.POST.get('student_id'), id__in=student_ids, cohort_relation_id=group.cohort_id)
            if action == 'add_group_member':
                StudentGroupMember.objects.get_or_create(group=group, student=student, defaults={'role': 'member'})
            elif action == 'remove_group_member':
                StudentGroupMember.objects.filter(group=group, student=student).delete()
            else:
                StudentGroupMember.objects.filter(group=group).update(role='member')
                StudentGroupMember.objects.update_or_create(group=group, student=student, defaults={'role': 'leader'})
        elif action == 'edit_note':
            note = get_object_or_404(StudentNote, id=request.POST.get('note_id'), student_id__in=student_ids, author=request.user)
            note.title = request.POST.get('title', '').strip()
            note.content = request.POST.get('content', '').strip()
            note.is_read = request.POST.get('published') != 'on'
            note.save(update_fields=['title', 'content', 'is_read', 'updated_at'])
        elif action == 'delete_note':
            get_object_or_404(StudentNote, id=request.POST.get('note_id'), student_id__in=student_ids, author=request.user).delete()
        elif action == 'create_event':
            student = get_object_or_404(Student, id=request.POST.get('student'), id__in=student_ids)
            title = request.POST.get('title', '').strip()
            event_date = request.POST.get('date')
            if title and event_date:
                event_date = datetime.fromisoformat(event_date).date()
                Event.objects.create(
                    student=student, title=title,
                    event_type=request.POST.get('event_type', 'other'),
                    description=request.POST.get('description', '').strip(),
                    date=event_date, time=request.POST.get('time') or None,
                    location=request.POST.get('location', '').strip(),
                )
        elif action == 'update_request':
            support_request = get_object_or_404(
                StudentRequest, id=request.POST.get('request_id'), student_id__in=student_ids,
            )
            if request.POST.get('status') in dict(StudentRequest.STATUS_CHOICES):
                support_request.status = request.POST['status']
            support_request.response = request.POST.get('response', '').strip()
            support_request.save(update_fields=['status', 'response', 'updated_at'])
            create_notification(
                support_request.student.user,
                'Your support request was updated',
                support_request.response or support_request.get_status_display(),
                reverse('crp:student_requests'),
                'request',
            )
        return redirect('crp:trainer_reference_module', module=module)

    modules = {
        'rubrics': ('Rubric Builder', 'Structured criteria, weightings and level descriptors.',
                    Rubric.objects.filter(assessment__in=assessments).prefetch_related('criteria')),
        'marking': ('Marking Queue', 'Rubric-based marking with integrity checks.',
                    AssessmentSubmission.objects.filter(assessment__in=assessments).select_related('student__user', 'assessment')),
        'attendance': ('Attendance', 'Current attendance for assigned students.', students),
        'analytics': ('Cohort Analytics', 'Performance and engagement for assigned students.', students),
        'risks': ('At Risk', 'Early-warning list from current student records.',
                  students.filter(Q(attendance_percentage__lt=80) | Q(tasks__completed=False)).distinct()),
        'groups': ('Groups & Leaders', 'Groups belonging to assigned cohorts.',
                   StudentGroup.objects.filter(cohort_id__in=cohort_ids).prefetch_related('members__student__user')),
        'live': ('Online Classes', 'Live sessions for assigned cohorts.',
                 LiveSession.objects.filter(Q(cohort_id__in=cohort_ids) | Q(program_id__in=cohorts.values('program_id'))).distinct()),
        'requests': ('Support Requests', 'Student support requests in your scope.',
                     StudentRequest.objects.filter(student_id__in=student_ids).select_related('student__user')),
        'unit': ('Unit Coordination', 'Courses assigned to this trainer.', courses),
        'tasks': ('Task Manager', 'Tasks assigned to your students.',
                  StudentTask.objects.filter(student_id__in=student_ids).select_related('student__user')),
        'notes': ('Student Notes', 'Notes authored for your assigned students.',
                  StudentNote.objects.filter(student_id__in=student_ids, author=request.user).select_related('student__user')),
        'comms': ('Bulk Comms', 'Announcements for assigned courses.',
                  Announcement.objects.filter(course__in=courses).select_related('course')),
        'messages': ('Messages', 'Conversations with assigned students.',
                     StudentMessageThread.objects.filter(trainer=request.user, student_id__in=student_ids).select_related('student__user')),
        'calendar': ('Calendar', 'Scheduled classes, live sessions and student events.',
                     list(schedules) + list(Event.objects.filter(student_id__in=student_ids)) +
                     list(LiveSession.objects.filter(cohort_id__in=cohort_ids))),
    }
    title, subtitle, records = modules.get(module, ('Trainer Module', 'Trainer workspace.', courses))
    rows = []
    for record in records:
        if isinstance(record, dict):
            rows.append(record)
            continue
        label = getattr(record, 'title', None) or getattr(record, 'name', None)
        if not label and hasattr(record, 'user'):
            label = record.user.get_full_name() or record.user.username
        label = label or str(record)
        student = getattr(record, 'student', None)
        meta = student.user.get_full_name() if student else str(getattr(record, 'description', '') or '')
        value = getattr(record, 'priority', '') or getattr(record, 'status', '') or ''
        if hasattr(record, 'attendance_percentage'):
            value = f'{record.attendance_percentage}%'
        rows.append({'id': getattr(record, 'id', None), 'label': label, 'meta': meta, 'value': value,
                     'starts_at': getattr(record, 'starts_at', None),
                     'meeting_url': getattr(record, 'meeting_url', ''),
                     'recording_url': getattr(record, 'recording_url', ''),
                     'status': 'Complete' if getattr(record, 'completed', False) else 'Open',
                     'status_class': 'success' if getattr(record, 'completed', False) else 'info'})
    context = {
        'module_title': title, 'module_subtitle': subtitle, 'module': module,
        'summary_cards': [(str(len(rows)), 'Records in scope'), (str(students.count()), 'Assigned students'),
                          (str(courses.count()), 'Assigned courses')],
        'records': rows, 'students': students, 'cohorts': cohorts, 'group_students': students,
        'role': 'trainer',
    }
    return render(request, 'crp/trainer/trainer_reference_module.html', context)


def _invoice_total_payments(invoice):
    return Payment.objects.filter(invoice=invoice).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')


def _invoice_outstanding(invoice):
    return max(Decimal(str(invoice.amount)) - _invoice_total_payments(invoice), Decimal('0.00'))


@role_required('admissions')
def admissions_dashboard(request):
    """Admissions dashboard for the shared portal shell; keep platform behavior consistent with the role contract."""
    return admissions_finance_dashboard(request)


@role_required('finance')
def finance_dashboard(request):
    """Legacy finance dashboard kept for compatibility; redirects to the shared portal."""
    return admissions_finance_dashboard(request)


@role_required('admissions', 'finance')
def admissions_finance_dashboard(request):
    """Shared Admissions & Finance dashboard backed by actual records."""
    registrations = Registration.objects.select_related('student', 'course')
    applications = registrations.order_by('-registration_date')
    pending_applications = applications.filter(workflow_status='submitted')
    documents_required = applications.filter(workflow_status='documents_required')
    contracts = applications.filter(workflow_status__in=['conditional_offer', 'unconditional_offer', 'offer_sent', 'offer_accepted', 'pending_finance'])
    offers_out = applications.filter(workflow_status__in=['conditional_offer', 'unconditional_offer', 'offer_sent', 'offer_accepted'])
    enrolled = applications.filter(workflow_status='enrolled')
    invoices = Invoice.objects.select_related('student', 'registration__course').order_by('-created_at')
    total_invoiced = sum((Decimal(str(invoice.amount)) for invoice in invoices), Decimal('0.00'))
    total_paid = sum((Decimal(str(payment.amount)) for payment in Payment.objects.all()), Decimal('0.00'))
    unpaid_invoices = [invoice for invoice in invoices if _invoice_outstanding(invoice) > 0]
    overdue_count = sum(1 for invoice in unpaid_invoices if invoice.due_date < timezone.localdate())
    payment_risk_count = overdue_count
    conversion_rate = round((enrolled.count() / applications.count()) * 100, 1) if applications.exists() else 0
    context = {
        'applications': applications[:10],
        'pending_applications': pending_applications[:10],
        'documents_required': documents_required[:10],
        'contracts': contracts[:10],
        'contract_count': contracts.count(),
        'documents_required_count': documents_required.count(),
        'offers_out': offers_out[:10],
        'enrolled': enrolled[:10],
        'invoices': invoices[:10],
        'total_invoiced': total_invoiced,
        'total_paid': total_paid,
        'outstanding_total': sum((_invoice_outstanding(invoice) for invoice in invoices), Decimal('0.00')),
        'overdue_count': overdue_count,
        'payment_risk_count': payment_risk_count,
        'applications_needing_action': pending_applications.count() + documents_required.count() + offers_out.count(),
        'finance_items_needing_action': len(unpaid_invoices),
        'conversion_rate': conversion_rate,
        'pipeline_chart': {
            'labels': ['Submitted', 'Documents required', 'Offers', 'Enrolled'],
            'values': [pending_applications.count(), documents_required.count(), offers_out.count(), enrolled.count()],
        },
        'finance_chart': {
            'labels': ['Collected', 'Outstanding'],
            'values': [float(total_paid), float(max(total_invoiced - total_paid, Decimal('0.00')))],
        },
        'role': get_user_role(request.user),
    }
    return render(request, 'crp/admissions_finance_dashboard.html', context)


@role_required('admissions', 'finance')
def admissions_applications(request):
    """Application list with search and status filtering."""
    qs = Registration.objects.select_related('student', 'course').order_by('-registration_date')
    search = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    if search:
        qs = qs.filter(
            Q(student__email__icontains=search)
            | Q(student__first_name__icontains=search)
            | Q(student__last_name__icontains=search)
            | Q(course__code__icontains=search)
            | Q(course__name__icontains=search)
        )
    if status:
        qs = qs.filter(workflow_status=status)
    context = {
        'applications': qs,
        'selected_status': status,
        'query': search,
        'application_status_choices': Registration.WORKFLOW_CHOICES,
        'role': get_user_role(request.user),
    }
    return render(request, 'crp/admissions_applications.html', context)


@role_required('admissions', 'finance')
def admissions_application_detail(request, registration_id):
    """Application detail page for the shared portal."""
    registration = get_object_or_404(Registration.objects.select_related('student', 'course'), id=registration_id)
    context = {
        'application': registration,
        'invoices': Invoice.objects.filter(registration=registration).select_related('student'),
        'payments': Payment.objects.filter(application=registration).select_related('invoice'),
        'role': get_user_role(request.user),
    }
    return render(request, 'crp/admissions_application_detail.html', context)


@role_required('admissions')
def admissions_application_transition(request, registration_id):
    """Transition an application through the admissions-only workflow."""
    if request.method != 'POST':
        messages.error(request, 'This action requires a POST request.')
        return redirect('crp:admissions_application_detail', registration_id=registration_id)

    registration = get_object_or_404(Registration.objects.select_related('student', 'course'), id=registration_id)
    next_status = request.POST.get('workflow_status')
    allowed = {
        'submitted': ['in_review'],
        'in_review': ['documents_required', 'conditional_offer', 'unconditional_offer', 'rejected'],
        'documents_required': ['in_review'],
        'conditional_offer': ['offer_sent', 'rejected'],
        'unconditional_offer': ['offer_sent', 'rejected'],
        'offer_sent': ['offer_accepted', 'declined'],
        'offer_accepted': ['pending_finance', 'declined'],
        'pending_finance': ['finance_cleared', 'rejected'],
        'finance_cleared': ['enrolled'],
    }
    if next_status not in allowed.get(registration.workflow_status, []):
        messages.error(request, 'Invalid workflow transition for this application.')
        return redirect('crp:admissions_application_detail', registration_id=registration_id)

    registration.workflow_status = next_status
    if next_status in ['rejected', 'declined', 'withdrawn', 'expired']:
        registration.status = 'rejected'
    elif next_status == 'enrolled':
        registration.status = 'completed'
    elif next_status in ['offer_accepted', 'pending_finance', 'finance_cleared']:
        registration.status = 'approved'
    registration.save(update_fields=['workflow_status', 'status', 'updated_at'])
    messages.success(request, f'Application moved to {next_status.replace("_", " ").title()}.')
    return redirect('crp:admissions_application_detail', registration_id=registration_id)


@role_required('admissions')
def admissions_contracts(request):
    """Offer and contract list for admissions staff."""
    applications = Registration.objects.filter(workflow_status__in=['conditional_offer', 'unconditional_offer', 'offer_sent', 'offer_accepted', 'pending_finance']).select_related('student', 'course').order_by('-registration_date')
    context = {'applications': applications, 'contract_count': applications.count(), 'role': 'admissions'}
    return render(request, 'crp/admissions_contracts.html', context)


@role_required('admissions')
def application_document_request(request, registration_id):
    """Create or request an application document for admissions processing."""
    registration = get_object_or_404(Registration.objects.select_related('student', 'course'), id=registration_id)
    if request.method != 'POST':
        messages.error(request, 'Document request requires a POST submission.')
        return redirect('crp:admissions_application_detail', registration_id=registration.id)

    document_name = (request.POST.get('document_name') or '').strip()
    document_type = (request.POST.get('document_type') or 'identity').strip() or 'identity'
    notes = (request.POST.get('notes') or '').strip()
    if not document_name:
        messages.error(request, 'Document name is required.')
        return redirect('crp:admissions_application_detail', registration_id=registration.id)

    document = ApplicationDocument.objects.create(
        registration=registration,
        document_name=document_name,
        document_type=document_type,
        notes=notes,
        status='requested',
        requested_by=request.user,
    )
    registration.workflow_status = 'documents_required'
    registration.save(update_fields=['workflow_status', 'updated_at'])
    messages.success(request, f'{document.document_name} requested successfully.')
    return redirect('crp:admissions_application_detail', registration_id=registration.id)


@role_required('admissions')
def application_document_verify(request, registration_id, document_id):
    """Verify a requested application document and record the admissions reviewer."""
    registration = get_object_or_404(Registration.objects.select_related('student', 'course'), id=registration_id)
    document = get_object_or_404(ApplicationDocument, id=document_id)
    if document.registration_id != registration.id:
        return HttpResponseForbidden('This document does not belong to the selected application.')

    if request.method != 'POST':
        messages.error(request, 'Verification requires a POST submission.')
        return redirect('crp:application_document_detail', registration_id=registration.id, document_id=document.id)

    document.status = 'verified'
    document.verified_by = request.user
    document.verified_at = timezone.now()
    document.notes = (request.POST.get('verification_notes') or document.notes or '').strip() or document.notes
    document.save(update_fields=['status', 'verified_by', 'verified_at', 'notes', 'updated_at'])
    messages.success(request, 'document verified successfully.')
    return redirect('crp:application_document_detail', registration_id=registration.id, document_id=document.id)


@role_required('admissions')
def application_document_detail(request, registration_id, document_id):
    """Detail view for an application document with ownership enforcement."""
    registration = get_object_or_404(Registration.objects.select_related('student', 'course'), id=registration_id)
    document = get_object_or_404(ApplicationDocument, id=document_id)
    if document.registration_id != registration.id:
        return HttpResponseForbidden('This document is not associated with this application.')
    context = {'registration': registration, 'document': document, 'role': 'admissions'}
    return render(request, 'crp/application_document_detail.html', context)


@role_required('admissions')
def application_contract_create(request, registration_id):
    """Create a conditional or unconditional contract for an applicant."""
    registration = get_object_or_404(Registration.objects.select_related('student', 'course'), id=registration_id)
    if request.method != 'POST':
        messages.error(request, 'Contract creation requires a POST submission.')
        return redirect('crp:admissions_application_detail', registration_id=registration.id)

    contract_type = (request.POST.get('contract_type') or 'conditional').strip() or 'conditional'
    title = (request.POST.get('title') or 'Offer Letter').strip() or 'Offer Letter'
    contract_text = (request.POST.get('contract_text') or '').strip()
    expires_at = request.POST.get('expires_at')
    expires_dt = timezone.datetime.strptime(expires_at, '%Y-%m-%d').replace(tzinfo=timezone.get_current_timezone()) if expires_at else None

    contract, _ = ApplicationContract.objects.get_or_create(
        registration=registration,
        contract_type=contract_type,
        defaults={
            'title': title,
            'contract_text': contract_text,
            'status': 'draft',
            'generated_by': request.user,
            'expires_at': expires_dt,
        },
    )
    if contract.title != title or contract.contract_text != contract_text or (expires_dt and contract.expires_at != expires_dt):
        contract.title = title
        contract.contract_text = contract_text
        contract.expires_at = expires_dt
        contract.generated_by = request.user
        contract.save(update_fields=['title', 'contract_text', 'expires_at', 'generated_by', 'updated_at'])

    registration.workflow_status = 'conditional_offer' if contract_type == 'conditional' else 'unconditional_offer'
    registration.save(update_fields=['workflow_status', 'updated_at'])
    messages.success(request, f'{title} created successfully.')
    return redirect('crp:admissions_application_detail', registration_id=registration.id)


@role_required('admissions')
def application_contract_send(request, registration_id, contract_id):
    """Send a generated contract to the applicant."""
    registration = get_object_or_404(Registration.objects.select_related('student', 'course'), id=registration_id)
    contract = get_object_or_404(ApplicationContract, id=contract_id)
    if contract.registration_id != registration.id:
        return HttpResponseForbidden('This contract does not belong to the selected application.')

    contract.status = 'sent'
    contract.sent_by = request.user
    contract.sent_at = timezone.now()
    contract.save(update_fields=['status', 'sent_by', 'sent_at', 'updated_at'])
    registration.workflow_status = 'offer_sent'
    registration.save(update_fields=['workflow_status', 'updated_at'])
    messages.success(request, 'contract sent successfully.')
    return redirect('crp:admissions_application_detail', registration_id=registration.id)


@role_required('admissions')
def application_contract_accept(request, registration_id, contract_id):
    """Accept the applicant contract and move the workflow to finance pending."""
    registration = get_object_or_404(Registration.objects.select_related('student', 'course'), id=registration_id)
    contract = get_object_or_404(ApplicationContract, id=contract_id)
    if contract.registration_id != registration.id:
        return HttpResponseForbidden('This contract is not associated with the selected application.')

    contract.status = 'accepted'
    contract.accepted_by = request.user
    contract.signed_at = timezone.now()
    contract.save(update_fields=['status', 'accepted_by', 'signed_at', 'updated_at'])
    registration.workflow_status = 'offer_accepted'
    registration.status = 'approved'
    registration.save(update_fields=['workflow_status', 'status', 'updated_at'])
    messages.success(request, 'Contract accepted.')
    return redirect('crp:admissions_application_detail', registration_id=registration.id)


@role_required('admissions')
def application_contract_detail(request, registration_id, contract_id):
    """Detail view for an application contract with ownership enforcement."""
    registration = get_object_or_404(Registration.objects.select_related('student', 'course'), id=registration_id)
    contract = get_object_or_404(ApplicationContract, id=contract_id)
    if contract.registration_id != registration.id:
        return HttpResponseForbidden('This contract is not associated with this application.')
    context = {'registration': registration, 'contract': contract, 'role': 'admissions'}
    return render(request, 'crp/application_contract_detail.html', context)


@role_required('finance')
def finance_invoices(request):
    """Invoice list for the finance user."""
    qs = Invoice.objects.select_related('student', 'registration__course').order_by('-created_at')
    search = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    if search:
        qs = qs.filter(
            Q(invoice_number__icontains=search)
            | Q(student__email__icontains=search)
            | Q(student__first_name__icontains=search)
            | Q(student__last_name__icontains=search)
        )
    if status:
        qs = qs.filter(status=status)
    for invoice in qs:
        invoice.outstanding = _invoice_outstanding(invoice)
    context = {'invoices': qs, 'selected_status': status, 'query': search, 'role': 'finance'}
    return render(request, 'crp/finance_invoices.html', context)


@role_required('finance')
def finance_invoice_detail(request, invoice_id):
    """Finance invoice detail page."""
    invoice = get_object_or_404(Invoice.objects.select_related('student', 'registration__course'), id=invoice_id)
    context = {
        'invoice': invoice,
        'payments': Payment.objects.filter(invoice=invoice).select_related('processed_by'),
        'outstanding': _invoice_outstanding(invoice),
        'role': 'finance',
    }
    return render(request, 'crp/finance_invoice_detail.html', context)


@require_POST
def record_payment(request, invoice_id):
    """Create a payment record against a valid invoice."""
    if get_user_role(request.user) != 'finance':
        return HttpResponseForbidden('Only finance staff can record payments.')

    invoice = get_object_or_404(Invoice.objects.select_related('student', 'registration__course'), id=invoice_id)
    amount_raw = request.POST.get('amount')
    try:
        amount = Decimal(str(amount_raw))
    except Exception:
        messages.error(request, 'Invalid payment amount.')
        return redirect('crp:finance_invoice_detail', invoice_id=invoice_id)
    if amount <= 0:
        messages.error(request, 'Payment amount must be greater than zero.')
        return redirect('crp:finance_invoice_detail', invoice_id=invoice_id)
    if amount > _invoice_outstanding(invoice):
        messages.error(request, 'Payment cannot exceed the outstanding balance.')
        return redirect('crp:finance_invoice_detail', invoice_id=invoice_id)

    ref = (request.POST.get('transaction_reference') or '').strip()
    if ref and Payment.objects.filter(transaction_reference=ref).exists():
        messages.error(request, 'Duplicate transaction reference detected.')
        return redirect('crp:finance_invoice_detail', invoice_id=invoice_id)

    payment = Payment.objects.create(
        invoice=invoice,
        application=invoice.registration,
        amount=amount,
        payment_date=request.POST.get('payment_date') or timezone.localdate(),
        payment_method=request.POST.get('payment_method', 'card'),
        transaction_reference=ref or f'PMT-{invoice.id}-{timezone.now().strftime("%Y%m%d%H%M%S")}',
        notes=request.POST.get('notes', ''),
        processed_by=request.user,
    )
    invoice.status = 'paid' if _invoice_outstanding(invoice) == Decimal('0.00') else 'partial'
    invoice.save(update_fields=['status', 'updated_at'])
    messages.success(request, 'Payment recorded successfully.')
    return redirect('crp:finance_invoice_detail', invoice_id=invoice_id)


@require_POST
def finance_clearance(request, invoice_id):
    """Finance-only clearance action for applications under review."""
    if get_user_role(request.user) != 'finance':
        return HttpResponseForbidden('Only finance staff can clear finances.')

    invoice = get_object_or_404(Invoice.objects.select_related('student', 'registration__course'), id=invoice_id)
    outstanding = _invoice_outstanding(invoice)
    registration = invoice.registration

    if registration and registration.workflow_status == 'enrolled':
        messages.info(request, 'Application is already cleared.')
        return redirect('crp:finance_invoice_detail', invoice_id=invoice_id)

    if registration and registration.workflow_status not in ['pending_finance', 'finance_cleared', 'enrolled']:
        messages.error(request, 'This application is not ready for finance clearance.')
        return redirect('crp:finance_invoice_detail', invoice_id=invoice_id)

    if registration:
        if registration.workflow_status == 'enrolled':
            messages.info(request, 'Application is already cleared.')
            return redirect('crp:finance_invoice_detail', invoice_id=invoice_id)
        registration.workflow_status = 'enrolled' if outstanding == Decimal('0.00') else 'finance_cleared'
        registration.status = 'completed' if outstanding == Decimal('0.00') else 'approved'
        registration.save(update_fields=['workflow_status', 'status', 'updated_at'])
    invoice.status = 'paid' if outstanding == Decimal('0.00') else 'partial'
    invoice.save(update_fields=['status', 'updated_at'])
    messages.success(request, 'Finance clearance recorded successfully.')
    return redirect('crp:finance_invoice_detail', invoice_id=invoice_id)


@role_required('admissions', 'finance')
def revenue_analytics(request):
    """Revenue summary for the shared portal."""
    invoices = Invoice.objects.select_related('student', 'registration__course').order_by('-created_at')
    for invoice in invoices:
        invoice.outstanding = _invoice_outstanding(invoice)
    total_invoiced = sum((Decimal(str(invoice.amount)) for invoice in invoices), Decimal('0.00'))
    total_paid = sum((Decimal(str(payment.amount)) for payment in Payment.objects.all()), Decimal('0.00'))
    outstanding_total = sum((_invoice_outstanding(invoice) for invoice in invoices), Decimal('0.00'))
    context = {'total_invoiced': total_invoiced, 'total_paid': total_paid, 'outstanding_total': outstanding_total, 'invoices': invoices, 'role': get_user_role(request.user)}
    return render(request, 'crp/revenue_analytics.html', context)


@role_required('admissions', 'finance')
def payment_risk(request):
    """Risk list derived from actual invoice and due-date data."""
    items = []
    for invoice in Invoice.objects.select_related('student', 'registration__course').order_by('due_date'):
        outstanding = _invoice_outstanding(invoice)
        if outstanding > 0:
            days_overdue = (timezone.localdate() - invoice.due_date).days if invoice.due_date < timezone.localdate() else 0
            items.append({'invoice': invoice, 'outstanding': outstanding, 'days_overdue': days_overdue})
    context = {'items': items, 'role': get_user_role(request.user)}
    return render(request, 'crp/payment_risk.html', context)


@role_required('admin')
def admin_dashboard(request):
    """Admin dashboard with full system overview"""
    total_students = User.objects.filter(groups__name='Students').count()
    total_instructors = Instructor.objects.filter(status='active').count()
    total_courses = Course.objects.count()
    active_courses = Course.objects.filter(status='active').count()
    pending_registrations = Registration.objects.filter(status='pending').count()
    
    recent_activity = Registration.objects.all().select_related(
        'student', 'course'
    ).order_by('-registration_date')[:10]
    
    course_capacity_stats = Course.objects.filter(
        status__in=['active', 'full']
    ).annotate(
        enrolled=Count('registrations', filter=Q(registrations__status='approved'))
    )
    
    context = {
        'total_students': total_students,
        'total_instructors': total_instructors,
        'total_courses': total_courses,
        'active_courses': active_courses,
        'pending_registrations': pending_registrations,
        'recent_activity': recent_activity,
        'course_capacity_stats': course_capacity_stats,
        'capacity_chart': {
            'labels': [course.code for course in course_capacity_stats[:10]],
            'enrolled': [course.enrolled for course in course_capacity_stats[:10]],
            'capacity': [course.max_capacity for course in course_capacity_stats[:10]],
        },
        'role': 'admin',
    }
    return render(request, 'crp/admin/dashboard.html', context)


@role_required('admin')
def admin_courses(request):
    courses = Course.objects.select_related('department', 'instructor').prefetch_related('trainers').annotate(
        enrolled_count=Count('registrations', filter=Q(registrations__status__in=('approved', 'completed'))),
        week_count=Count('learning_weeks', distinct=True),
    )
    search = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    if search:
        courses = courses.filter(Q(code__icontains=search) | Q(name__icontains=search))
    if status:
        courses = courses.filter(status=status)
    return render(request, 'crp/admin/courses.html', {'courses': courses, 'status_choices': Course.STATUS_CHOICES})


@role_required('admin')
def admin_course_toggle(request, course_id, action):
    if request.method == 'POST':
        course = get_object_or_404(Course, pk=course_id)
        if action == 'publish':
            course.status = 'active' if course.status == 'draft' else 'draft'
        elif action == 'archive':
            course.status = 'cancelled' if course.status != 'cancelled' else 'draft'
        course.save(update_fields=['status', 'updated_at'])
    return redirect('crp:admin_courses')


@role_required('admin')
def admin_course_detail(request, course_id):
    course = get_object_or_404(
        Course.objects.select_related('department', 'instructor').prefetch_related(
            'trainers', 'registrations__student', 'learning_weeks__materials', 'learning_weeks__quiz',
            'learning_weeks__assessments',
        ),
        pk=course_id,
    )
    if request.method == 'POST':
        action = request.POST.get('action')
        week = get_object_or_404(LearningWeek, pk=request.POST.get('week_id'), course=course) if request.POST.get('week_id') else None
        if action == 'assign_trainers':
            course.trainers.set(Instructor.objects.filter(pk__in=request.POST.getlist('trainer_ids')))
        elif action == 'week_save':
            week = week or LearningWeek(course=course)
            week.week_number = int(request.POST.get('week_number') or 1)
            week.title = request.POST.get('title', '').strip()
            week.description = request.POST.get('description', '').strip()
            week.learning_objectives = request.POST.get('learning_objectives', '').strip()
            week.topics = [item.strip() for item in request.POST.get('topics', '').split(',') if item.strip()]
            release_value = request.POST.get('release_date')
            week.release_date = timezone.make_aware(datetime.fromisoformat(release_value)) if release_value else None
            week.completion_requirements = request.POST.get('completion_requirements', '').strip()
            week.require_materials = 'require_materials' in request.POST
            week.require_quiz = 'require_quiz' in request.POST
            week.require_assessment = 'require_assessment' in request.POST
            week.is_published = 'is_published' in request.POST
            week.is_archived = 'is_archived' in request.POST
            week.save()
        elif action == 'week_delete' and week:
            week.delete()
        elif action in ('week_archive', 'week_publish') and week:
            if action == 'week_archive':
                week.is_archived = not week.is_archived
                fields = ['is_archived', 'updated_at']
            else:
                week.is_published = not week.is_published
                fields = ['is_published', 'updated_at']
            week.save(update_fields=fields)
        elif action == 'material_save' and week:
            material = get_object_or_404(LearningMaterial, pk=request.POST.get('material_id'), week=week) if request.POST.get('material_id') else LearningMaterial(week=week)
            material.title = request.POST.get('title', '').strip()
            material.material_type = request.POST.get('material_type', 'other')
            material.file_url = request.POST.get('file_url', '').strip()
            uploaded_file = request.FILES.get('file')
            try:
                validate_material_upload(uploaded_file, material.material_type)
            except ValidationError as error:
                messages.error(request, error.messages[0])
                return redirect('crp:admin_course_detail', course_id=course.id)
            if uploaded_file:
                material.file = uploaded_file
            if not material.file and not material.file_url:
                messages.error(request, 'Upload a PDF/video or provide a material URL.')
                return redirect('crp:admin_course_detail', course_id=course.id)
            material.order = int(request.POST.get('order') or 0)
            material.is_published = 'is_published' in request.POST
            material.is_archived = 'is_archived' in request.POST
            material.save()
        elif action == 'material_delete':
            get_object_or_404(LearningMaterial, pk=request.POST.get('material_id'), week__course=course).delete()
        elif action == 'quiz_save' and week:
            quiz = get_object_or_404(Quiz, pk=request.POST.get('quiz_id'), week=week) if request.POST.get('quiz_id') else Quiz(week=week)
            quiz.title = request.POST.get('title', '').strip()
            quiz.description = request.POST.get('description', '').strip()
            quiz.question_count = int(request.POST.get('question_count') or 10)
            quiz.time_limit_minutes = int(request.POST.get('time_limit_minutes') or 30)
            quiz.passing_score = int(request.POST.get('passing_score') or 60)
            quiz.is_published = 'is_published' in request.POST
            quiz.is_archived = 'is_archived' in request.POST
            quiz.save()
        elif action == 'quiz_delete':
            get_object_or_404(Quiz, pk=request.POST.get('quiz_id'), week__course=course).delete()
        elif action == 'question_save':
            quiz = get_object_or_404(Quiz, pk=request.POST.get('quiz_id'), week__course=course)
            question = get_object_or_404(QuizQuestion, pk=request.POST.get('question_id'), quiz=quiz) if request.POST.get('question_id') else QuizQuestion(quiz=quiz)
            question.question_text = request.POST.get('question_text', '').strip()
            question.difficulty = request.POST.get('difficulty', 'medium')
            question.explanation = request.POST.get('explanation', '').strip()
            question.order = int(request.POST.get('order') or 0)
            question.save()
        elif action == 'question_archive':
            question = get_object_or_404(QuizQuestion, pk=request.POST.get('question_id'), quiz__week__course=course)
            question.is_archived = not question.is_archived
            question.save(update_fields=['is_archived'])
        elif action == 'question_delete':
            get_object_or_404(QuizQuestion, pk=request.POST.get('question_id'), quiz__week__course=course).delete()
        elif action == 'option_save':
            question = get_object_or_404(QuizQuestion, pk=request.POST.get('question_id'), quiz__week__course=course)
            option = get_object_or_404(QuizOption, pk=request.POST.get('option_id'), question=question) if request.POST.get('option_id') else QuizOption(question=question)
            option.option_text = request.POST.get('option_text', '').strip()
            option.order = int(request.POST.get('order') or 0)
            option.is_correct = 'is_correct' in request.POST
            option.save()
        elif action == 'option_delete':
            get_object_or_404(QuizOption, pk=request.POST.get('option_id'), question__quiz__week__course=course).delete()
        elif action == 'assessment_save' and week:
            messages.error(request, 'Assignments can only be created by the trainer assigned to this course.')
        elif action == 'assessment_delete':
            get_object_or_404(Assessment, pk=request.POST.get('assessment_id'), week__course=course).delete()
        return redirect('crp:admin_course_detail', course_id=course.id)
    weeks = course.learning_weeks.all().order_by('week_number')
    trainers = Instructor.objects.filter(status='active').select_related('user')
    return render(request, 'crp/admin/course_detail.html', {
        'course': course, 'weeks': weeks, 'trainers': trainers,
        'enrollments': course.registrations.select_related('student').order_by('-registration_date'),
        'material_types': LearningMaterial.MATERIAL_TYPES,
        'assessment_types': Assessment.ASSESSMENT_TYPES,
    })


@role_required('admin')
def admin_enrollments(request):
    enrollments = Registration.objects.select_related('student', 'course', 'approved_by').order_by('-registration_date')
    status = request.GET.get('status', '')
    course_id = request.GET.get('course', '')
    query = request.GET.get('q', '').strip()
    if status:
        enrollments = enrollments.filter(status=status)
    if course_id:
        enrollments = enrollments.filter(course_id=course_id)
    if query:
        enrollments = enrollments.filter(Q(student__username__icontains=query) | Q(student__email__icontains=query) | Q(course__code__icontains=query))
    if request.GET.get('date_from'):
        enrollments = enrollments.filter(registration_date__date__gte=request.GET['date_from'])
    if request.GET.get('date_to'):
        enrollments = enrollments.filter(registration_date__date__lte=request.GET['date_to'])
    return render(request, 'crp/admin/enrollments.html', {
        'enrollments': enrollments, 'courses': Course.objects.order_by('code'),
        'status_choices': Registration.STATUS_CHOICES,
    })


@role_required('admin')
def admin_enrollment_detail(request, registration_id):
    registration = get_object_or_404(Registration.objects.select_related('student', 'course', 'approved_by'), pk=registration_id)
    return render(request, 'crp/admin/enrollment_detail.html', {'registration': registration})


@role_required('admin')
@require_POST
def admin_enrollment_action(request, registration_id, action):
    registration = get_object_or_404(Registration, pk=registration_id)
    if action == 'approve':
        registration.approve(request.user)
    elif action == 'reject':
        registration.reject(request.user, request.POST.get('reason', ''))
    return redirect('crp:admin_enrollments')


@role_required('admin')
def admin_legacy_mapping(request):
    if request.method == 'POST':
        content_type = request.POST.get('content_type')
        object_id = request.POST.get('object_id')
        course = get_object_or_404(Course, pk=request.POST.get('course_id'))
        if content_type == 'week':
            week = get_object_or_404(LearningWeek, pk=object_id)
            week.course = course
            week.save(update_fields=['course', 'updated_at'])
        elif content_type == 'assessment':
            assessment = get_object_or_404(Assessment, pk=object_id)
            assessment.course = course
            assessment.course_code = course.code
            assessment.save(update_fields=['course', 'course_code', 'updated_at'])
        return redirect('crp:admin_legacy_mapping')
    return render(request, 'crp/admin/legacy_mapping.html', {
        'weeks': LearningWeek.objects.filter(course__isnull=True).prefetch_related('materials', 'quiz'),
        'assessments': Assessment.objects.filter(course__isnull=True).select_related('week'),
        'courses': Course.objects.order_by('code'),
    })


@role_required('admin')
def admin_trainers(request):
    trainers = Instructor.objects.filter(status='active').select_related('user').prefetch_related('assigned_courses')
    return render(request, 'crp/admin/trainers.html', {'trainers': trainers})


@role_required('admin')
def admin_academic_module(request, module):
    modules = {
        'weeks': ('Weeks / Modules', LearningWeek.objects.select_related('course').order_by('course__code', 'week_number')),
        'materials': ('Learning Materials', LearningMaterial.objects.filter(week__course__isnull=False).select_related('week__course').order_by('week__course__code', 'week__week_number', 'order')),
        'quizzes': ('Quizzes', Quiz.objects.filter(week__course__isnull=False).select_related('week__course').order_by('week__course__code', 'week__week_number')),
        'questions': ('Question Banks', QuizQuestion.objects.filter(quiz__week__course__isnull=False).select_related('quiz__week__course').order_by('quiz__week__course__code', 'quiz__title', 'order')),
        'assessments': ('Assessments', Assessment.objects.filter(week__course__isnull=False).select_related('week__course').order_by('week__course__code', 'week__week_number')),
    }
    title, objects = modules.get(module, (None, None))
    if title is None:
        raise Http404
    return render(request, 'crp/admin/academic_module.html', {'module': module, 'module_title': title, 'objects': objects})


@role_required('admin')
def admin_operations_module(request, module):
    if module == 'support':
        return redirect('crp:support_tickets')
    if module == 'integrations':
        return render(request, 'crp/admin/integrations.html', {
            'module': module, 'module_title': 'Integrations',
            'google_oauth_configured': bool(getattr(settings, 'SOCIAL_AUTH_GOOGLE_OAUTH2_KEY', '')),
            'email_configured': bool(getattr(settings, 'EMAIL_HOST', '')),
            'storage_configured': bool(getattr(settings, 'DEFAULT_FILE_STORAGE', '')),
            'integration_rows': [
                ('Google OAuth', bool(getattr(settings, 'SOCIAL_AUTH_GOOGLE_OAUTH2_KEY', ''))),
                ('Email delivery', bool(getattr(settings, 'EMAIL_HOST', ''))),
                ('File storage', bool(getattr(settings, 'DEFAULT_FILE_STORAGE', ''))),
            ],
        })
    if module == 'success-stories':
        stories = SuccessStory.objects.select_related('student', 'course').all()
        if request.method == 'POST':
            story = get_object_or_404(stories, id=request.POST.get('story_id')) if request.POST.get('story_id') else SuccessStory()
            story.title = request.POST.get('title', '').strip()
            story.content = request.POST.get('content', '').strip()
            story.outcome_type = request.POST.get('outcome_type', '').strip()
            story.employer = request.POST.get('employer', '').strip()
            story.role = request.POST.get('role', '').strip()
            story.is_published = request.POST.get('is_published') == 'on'
            if story.title and story.content:
                story.save()
            return redirect('crp:admin_operations_module', module='success-stories')
        return render(request, 'crp/admin/success_stories.html', {
            'module': module, 'module_title': 'Success Stories', 'stories': stories,
        })
    if module == 'users':
        if request.method == 'POST':
            user = get_object_or_404(User, id=request.POST.get('user_id'))
            if user == request.user:
                messages.error(request, 'You cannot deactivate your own account.')
            else:
                user.is_active = request.POST.get('is_active') == 'on'
                user.save(update_fields=['is_active'])
                messages.success(request, f'User status updated for {user.get_username()}.')
            return redirect('crp:admin_operations_module', module='users')
        users = User.objects.select_related('student_profile', 'instructor_profile').all().order_by(
            'last_name', 'first_name', 'username'
        )
        query = request.GET.get('q', '').strip()
        role = request.GET.get('role', '').strip()
        if query:
            users = users.filter(
                Q(username__icontains=query) | Q(first_name__icontains=query) |
                Q(last_name__icontains=query) | Q(email__icontains=query)
            )
        if role == 'student':
            users = users.filter(student_profile__isnull=False)
        elif role == 'trainer':
            users = users.filter(instructor_profile__isnull=False)
        elif role == 'admin':
            users = users.filter(is_superuser=True)
        return render(request, 'crp/admin/user_management.html', {
            'module': module, 'module_title': 'User Management', 'users': users,
            'query': query, 'selected_role': role,
        })
    modules = {
        'students': ('Students', Student.objects.select_related('user').order_by('user__last_name')),
        'assignments': ('Assignments Overview', AssessmentSubmission.objects.select_related('assessment__course', 'student__user').order_by('-updated_at')),
        'announcements': ('Announcements', Announcement.objects.select_related('course').order_by('-created_at')),
        'live-sessions': ('Live Sessions', LiveSession.objects.select_related('cohort__program').order_by('-starts_at')),
        'attendance': ('Attendance Overview', AttendanceRecord.objects.select_related('student__user', 'schedule__course').order_by('-session_date')),
    }
    title, objects = modules.get(module, (None, None))
    if title is None:
        raise Http404
    if module == 'students' and request.method == 'POST':
        student = get_object_or_404(Student, pk=request.POST.get('student_id'))
        status = request.POST.get('status')
        if status in dict(Student._meta.get_field('status').choices):
            student.status = status
            student.save(update_fields=['status', 'updated_at'])
            messages.success(request, f'Student status updated for {student.user.get_full_name() or student.user.username}.')
        else:
            messages.error(request, 'Select a valid student status.')
        return redirect('crp:admin_operations_module', module='students')
    return render(request, 'crp/admin/operations_module.html', {
        'module': module,
        'module_title': title,
        'objects': objects,
        'student_status_choices': Student._meta.get_field('status').choices,
    })


@role_required('admin')
def admin_system_module(request, module):
    if module not in ('reports', 'settings', 'analytics'):
        raise Http404
    context = {
        'module': module,
        'module_title': module.title(),
        'course_count': Course.objects.count(),
        'published_week_count': LearningWeek.objects.filter(is_published=True, is_archived=False).count(),
        'approved_enrollment_count': Registration.objects.filter(status__in=('approved', 'completed')).count(),
        'trainer_count': Instructor.objects.filter(status='active').count(),
        'attendance_count': AttendanceRecord.objects.count(),
        'published_session_count': LiveSession.objects.filter(is_published=True, is_archived=False).count(),
        'pending_submission_count': AssessmentSubmission.objects.filter(status='submitted').count(),
    }
    return render(request, 'crp/admin/system_module.html', context)

@login_required
def marketing_dashboard(request):
    """Marketing department dashboard (isolated from CRP)"""
    messages.error(request, "Marketing dashboard is not part of CRP. Please access via appropriate system.")
    return redirect('crp:dashboard')

class CourseListView(LoginRequiredMixin, ListView):
    model = Course
    template_name = 'crp/course_list.html'
    context_object_name = 'courses'
    paginate_by = 12

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['catalog_base_template'] = (
            'crp/student/student_base.html'
            if get_user_role(self.request.user) == 'student'
            else 'crp/base.html'
        )
        return context

    def get_queryset(self):
        queryset = Course.objects.select_related('department', 'instructor').prefetch_related('prerequisites')
        if get_user_role(self.request.user) == 'trainer':
            instructor = _get_trainer_instructor(self.request.user)
            queryset = queryset.filter(
                Q(instructor=instructor) | Q(trainers=instructor)
            ).distinct()
        search = self.request.GET.get('search')
        level = self.request.GET.get('level')
        department = self.request.GET.get('department')
        status = self.request.GET.get('status', 'active')
        
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search) | 
                Q(name__icontains=search) | 
                Q(description__icontains=search)
            )
        if level:
            queryset = queryset.filter(level=level)
        if department:
            queryset = queryset.filter(department__code=department)
        if status:
            queryset = queryset.filter(status=status)
            
        return queryset.order_by('-created_at')

class CourseDetailView(LoginRequiredMixin, DetailView):
    model = Course
    template_name = 'crp/course_detail.html'
    context_object_name = 'course'

    def get_queryset(self):
        queryset = Course.objects.select_related('department', 'instructor').prefetch_related('prerequisites')
        if get_user_role(self.request.user) == 'trainer':
            instructor = _get_trainer_instructor(self.request.user)
            queryset = queryset.filter(
                Q(instructor=instructor) | Q(trainers=instructor)
            ).distinct()
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        course = self.object
        context['schedules'] = course.schedules.select_related('room', 'time_slot', 'instructor')
        context['prerequisites'] = course.prerequisites.all()
        context['is_registered'] = Registration.objects.filter(
            student=self.request.user,
            course=course,
            status__in=['approved', 'pending']
        ).exists()
        return context

@login_required
@require_POST
def register_for_course(request, course_id):
    """Register a student for a course"""
    course = get_object_or_404(Course, id=course_id)
    
    # Check if already registered
    existing_registration = Registration.objects.filter(
        student=request.user,
        course=course,
        status__in=['approved', 'pending']
    ).first()
    
    if existing_registration:
        messages.warning(request, "You are already registered for this course.")
        return redirect('crp:course_detail', pk=course_id)
    
    # Check course capacity
    if course.current_enrollment >= course.max_capacity:
        # Add to waitlist
        position = Waitlist.objects.filter(course=course).count() + 1
        Waitlist.objects.create(
            student=request.user,
            course=course,
            semester=course.semester,
            position=position
        )
        messages.info(request, "Course is full. You have been added to the waitlist.")
        return redirect('crp:course_detail', pk=course_id)
    
    # Create registration
    current_semester = "Fall 2026"  # This should be dynamic based on current date
    registration = Registration.objects.create(
        student=request.user,
        course=course,
        semester=current_semester,
        status='pending'
    )
    
    # Send email notification
    try:
        send_registration_email(registration)
    except Exception as e:
        messages.warning(request, f"Registration successful but email notification failed: {e}")
    
    messages.success(request, "Registration submitted successfully. Waiting for approval.")
    return redirect('crp:student_portal')

@login_required
@require_POST
def approve_registration(request, registration_id):
    """Approve a pending registration (Admissions/Admin only)"""
    if get_user_role(request.user) != 'admin':
        messages.error(request, "Permission denied.")
        return redirect('dashboard')
    
    registration = get_object_or_404(Registration, id=registration_id)
    
    if registration.approve(request.user):
        messages.success(request, f"Registration for {registration.student.email} approved successfully.")
        # Send approval email
        try:
            send_registration_email(registration, status='approved')
        except Exception as e:
            messages.warning(request, f"Approval successful but email notification failed: {e}")
    else:
        messages.error(request, "Cannot approve this registration.")
    
    return redirect('admissions_dashboard')

@login_required
@require_POST
def reject_registration(request, registration_id):
    """Reject a pending registration (Admissions/Admin only)"""
    if get_user_role(request.user) != 'admin':
        messages.error(request, "Permission denied.")
        return redirect('dashboard')
    
    registration = get_object_or_404(Registration, id=registration_id)
    reason = request.POST.get('reason', '')
    
    if registration.reject(request.user, reason):
        messages.success(request, f"Registration for {registration.student.email} rejected.")
        # Send rejection email
        try:
            send_registration_email(registration, status='rejected', reason=reason)
        except Exception as e:
            messages.warning(request, f"Rejection successful but email notification failed: {e}")
    else:
        messages.error(request, "Cannot reject this registration.")
    
    return redirect('admissions_dashboard')

@login_required
def my_registrations(request):
    """View current user's registrations"""
    registrations = Registration.objects.filter(
        student=request.user
    ).select_related('course').order_by('-registration_date')
    
    total_credits = sum(reg.course.credits for reg in registrations if reg.status == 'approved')
    approved_count = sum(1 for reg in registrations if reg.status == 'approved')
    
    context = {
        'registrations': registrations,
        'total_credits': total_credits,
        'approved_count': approved_count,
    }
    return render(request, 'crp/my_registrations.html', context)

@login_required
@require_POST
def withdraw_registration(request, registration_id):
    """Withdraw from a course"""
    registration = get_object_or_404(Registration, id=registration_id, student=request.user)
    
    if registration.withdraw():
        messages.success(request, "Successfully withdrawn from the course.")
    else:
        messages.error(request, "Cannot withdraw from this course.")
    
    return redirect('my_registrations')

@login_required
def download_registration_pdf(request, registration_id):
    """Download registration confirmation as PDF"""
    registration = get_object_or_404(Registration, id=registration_id)
    
    # Check permission
    if not (request.user == registration.student or 
            request.user.is_superuser or 
            request.user.is_staff):
        messages.error(request, "Permission denied.")
        return redirect('dashboard')
    
    pdf_content = generate_registration_pdf(registration)
    
    response = HttpResponse(pdf_content, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="registration_{registration.id}.pdf"'
    return response

@login_required
def export_courses(request):
    """Export courses to Excel (Admin/Admissions only)"""
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "Permission denied.")
        return redirect('dashboard')
    
    excel_content = export_courses_to_excel()
    
    response = HttpResponse(excel_content, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="courses_export.xlsx"'
    return response

class CourseCreateView(LoginRequiredMixin, CreateView):
    model = Course
    form_class = CourseForm
    template_name = 'crp/course_form.html'
    success_url = reverse_lazy('crp:admin_courses')

    def dispatch(self, request, *args, **kwargs):
        if get_user_role(request.user) != 'admin':
            messages.error(request, "Permission denied.")
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

class CourseUpdateView(LoginRequiredMixin, UpdateView):
    model = Course
    form_class = CourseForm
    template_name = 'crp/course_form.html'
    success_url = reverse_lazy('crp:admin_courses')

    def dispatch(self, request, *args, **kwargs):
        if get_user_role(request.user) != 'admin':
            messages.error(request, "Permission denied.")
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

class ScheduleListView(LoginRequiredMixin, ListView):
    model = Schedule
    template_name = 'crp/schedule_list.html'
    context_object_name = 'schedules'

    def get_queryset(self):
        return Schedule.objects.select_related(
            'course', 'room', 'time_slot', 'instructor'
        ).order_by('day', 'time_slot')

class AnnouncementListView(LoginRequiredMixin, ListView):
    model = Announcement
    template_name = 'crp/announcement_list.html'
    context_object_name = 'announcements'
    paginate_by = 10

    def get_queryset(self):
        return Announcement.objects.filter(
            published=True
        ).select_related('author', 'course').order_by('-created_at')

class AnnouncementDetailView(LoginRequiredMixin, DetailView):
    model = Announcement
    template_name = 'crp/announcement_detail.html'
    context_object_name = 'announcement'

@method_decorator(login_required, name='dispatch')
class AnnouncementCreateView(CreateView):
    model = Announcement
    form_class = AnnouncementForm
    template_name = 'crp/announcement_form.html'
    success_url = reverse_lazy('announcement_list')

    def form_valid(self, form):
        form.instance.author = self.request.user
        return super().form_valid(form)

# Image Upload Views
@login_required
def image_upload_list(request):
    """List all uploaded images"""
    images = UploadedImage.objects.select_related('uploaded_by').order_by('-created_at')
    
    # Filter by category if provided
    category = request.GET.get('category')
    if category:
        images = images.filter(category=category)
    
    paginator = Paginator(images, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'category': category,
    }
    return render(request, 'crp/image_upload_list.html', context)

@login_required
def image_upload_create(request):
    """Upload a new image"""
    if request.method == 'POST':
        form = UploadedImageForm(request.POST, request.FILES)
        if form.is_valid():
            image = form.save(commit=False)
            image.uploaded_by = request.user
            image.save()
            messages.success(request, "Image uploaded successfully.")
            return redirect('image_upload_list')
    else:
        form = UploadedImageForm()
    
    return render(request, 'crp/image_upload_form.html', {'form': form})

@login_required
def image_upload_detail(request, pk):
    """View image details"""
    image = get_object_or_404(UploadedImage, pk=pk)
    return render(request, 'crp/image_upload_detail.html', {'image': image})

@login_required
def image_upload_delete(request, pk):
    """Delete an uploaded image"""
    image = get_object_or_404(UploadedImage, pk=pk)
    
    # Check permissions
    if image.uploaded_by != request.user and not request.user.is_superuser:
        messages.error(request, "Permission denied.")
        return redirect('image_upload_list')
    
    if request.method == 'POST':
        image.delete()
        messages.success(request, "Image deleted successfully.")
        return redirect('image_upload_list')
    
    return render(request, 'crp/image_upload_confirm_delete.html', {'image': image})

# Student Portal Views - Phase 2A
@role_required('student')
def student_portal_dashboard(request):
    """Student dashboard backed only by the authenticated student's records."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found. Please contact administration.")
        return redirect('crp:dashboard')
    
    progress_rows, completed_weeks, current_week = student_progress_summary(student)
    total_weeks = len(progress_rows)
    progress_percentage = int((completed_weeks / total_weeks) * 100) if total_weeks else 0
    activity_dates = student_activity_dates(student)
    current_streak = 0
    streak_day = timezone.localdate()
    while streak_day in activity_dates:
        current_streak += 1
        streak_day -= timedelta(days=1)
    
    # Quiz statistics
    quiz_attempts = QuizAttempt.objects.filter(
        student=student,
        completed_at__isnull=False,
        score__isnull=False,
    ).select_related('quiz__week')
    quiz_scores = [attempt.score for attempt in quiz_attempts]
    quiz_average = int(sum(quiz_scores) / len(quiz_scores)) if quiz_scores else 0
    
    # Metrics
    badges_count = StudentBadge.objects.filter(student=student, is_displayed=True).count()
    attendance_value = student.attendance_percentage if student.attendance_percentage and student.cohort_relation_id else 0
    mini_stats = [
        {'value': f'{quiz_average}%' if quiz_scores else '—', 'label': 'Quiz average'},
        {'value': f'{attendance_value}%' if attendance_value else '—', 'label': 'Attendance'},
        {'value': str(badges_count), 'label': 'Badges earned'},
    ]
    
    # Weekly agenda (events)
    today = timezone.now().date()
    upcoming_events = Event.objects.filter(
        student=student,
        date__gte=today,
        date__lte=today + timedelta(days=7)
    ).order_by('date', 'time')[:4]
    
    agenda = []
    for event in upcoming_events:
        agenda.append({
            'day': event.date.strftime('%d'),
            'day_label': event.date.strftime('%a %d').upper(),
            'label': event.title,
            'time': event.time.strftime('%I:%M %p') if event.time else 'TBD',
            'kind': event.get_event_type_display(),
        })
    
    # Open tasks
    open_tasks = StudentTask.objects.filter(
        student=student,
        completed=False
    ).order_by('-priority', 'due_date')[:3]
    
    task_list = []
    for task in open_tasks:
        priority_colors = {
            'High': "var(--color-accent)",
            'Medium': "color-mix(in srgb, var(--color-text) 74%, transparent)",
            'Low': "color-mix(in srgb, var(--color-text) 40%, transparent)"
        }
        pri_color = priority_colors.get(task.priority, "color-mix(in srgb, var(--color-text) 74%, transparent)")
        
        task_list.append({
            'id': task.id,
            'title': task.title,
            'by': task.created_by,
            'due': task.due_date.strftime('%d %b') if task.due_date else 'No date',
            'pri': task.get_priority_display(),
            'pri_style': f'font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; font-weight: 800; color: {pri_color};',
            'box_style': f'width: 20px; height: 20px; flex: none; border: 2px solid color-mix(in srgb, var(--color-text) 35%, transparent); border-radius: 7px; background: transparent; color: #fff; display: grid; place-items: center; font-size: 11px; font-weight: 800; cursor: pointer;',
            'mark': '',
        })
    
    remaining_weeks = max(total_weeks - completed_weeks, 0)
    
    # Get job match count
    top_job_match = JobListing.objects.filter(is_active=True).order_by('-match_percentage', '-posted_date').first()
    job_match_count = JobListing.objects.filter(is_active=True).count()

    registrations = Registration.objects.filter(
        student=request.user,
    ).select_related('course', 'course__instructor').order_by('-registration_date')
    available_courses = Course.objects.filter(status='active').select_related(
        'department', 'instructor'
    )
    registration_by_course = {registration.course_id: registration for registration in registrations}
    course_cards = []
    for course in available_courses:
        registration = registration_by_course.get(course.id)
        course_cards.append({
            'course': course,
            'registration': registration,
            'status': registration.get_status_display() if registration else 'Available',
        })

    # Keep the reference dashboard's four KPI sequence, backed by live records.
    metrics = [
        {'label': 'Quiz average', 'value': f'{quiz_average}%' if quiz_scores else '—', 'delta': 'Based on completed attempts'},
        {'label': 'Attendance', 'value': f'{attendance_value}%' if attendance_value else '—', 'delta': 'Recorded attendance' if attendance_value else 'No attendance recorded'},
        {'label': 'Achievements', 'value': str(badges_count), 'delta': 'Earned badges'},
        {'label': 'Current streak', 'value': f'{current_streak} days' if current_streak else '—', 'delta': 'Recorded activity'},
    ]
    
    context = {
        'student': student,
        'current_week': current_week,
        'progress_percentage': progress_percentage,
        'total_weeks': total_weeks,
        'completed_weeks': completed_weeks,
        'remaining_weeks': remaining_weeks,
        'mini_stats': mini_stats,
        'metrics': metrics,
        'agenda': agenda,
        'open_tasks': task_list,
        'career_coach': {
            'message': 'Start your learning activities to receive personalised guidance.',
            'actions': [{'label': 'Complete your profile', 'action': 'student_resume'}],
        },
        'top_job_match': top_job_match,
        'job_match_count': job_match_count,
        'course_cards': course_cards,
        'my_courses': [item for item in course_cards if item['registration'] and item['registration'].status in ('approved', 'completed')],
        'role': 'student',
    }
    return render(request, 'crp/student/student_dashboard.html', context)

@role_required('student')
def student_learning_hub(request):
    """Learning hub with weekly curriculum and materials"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    progress_rows = sync_student_progress(student)
    progress_map = {row.week_id: row for row in progress_rows}
    weeks = eligible_weeks(student)
    cohort_program_id = (
        student.cohort_relation.program_id
        if student.cohort_relation_id
        else None
    )
    
    # Calculate material progress
    visible_materials = LearningMaterial.objects.filter(
        week__in=weeks, is_published=True, is_archived=False,
    ).filter(
        Q(program__isnull=True) | Q(program_id=cohort_program_id),
        Q(cohort__isnull=True) | Q(cohort_id=student.cohort_relation_id),
    )
    materials_done = MaterialProgress.objects.filter(
        student=student,
        material__in=visible_materials,
        completed=True,
    ).count()
    materials_total = LearningMaterial.objects.filter(
        week__in=weeks, is_published=True, is_archived=False,
    ).filter(
        Q(program__isnull=True) | Q(program_id=cohort_program_id),
        Q(cohort__isnull=True) | Q(cohort_id=student.cohort_relation_id),
    ).count()
    
    week_rows = []
    for week in weeks:
        materials = week.materials.filter(
            is_published=True, is_archived=False,
        ).filter(
            Q(program__isnull=True) | Q(program_id=cohort_program_id),
            Q(cohort__isnull=True) | Q(cohort_id=student.cohort_relation_id),
        ).order_by('order')
        material_items = []
        
        for material in materials:
            progress = MaterialProgress.objects.filter(student=student, material=material).first()
            
            material_items.append({
                'title': material.title,
                'meta': f"{material.get_material_type_display()} · {material.file_size or material.duration or ''}",
                'mark': '✓' if progress and progress.completed else '',
                'box_style': f'width: 20px; height: 20px; flex: none; border: 2px solid {"var(--color-accent)" if progress and progress.completed else "color-mix(in srgb, var(--color-text) 35%, transparent)"}; border-radius: 7px; background: {"var(--color-accent)" if progress and progress.completed else "transparent"}; color: #fff; display: grid; place-items: center; font-size: 11px; font-weight: 800; cursor: pointer;',
                'completed': bool(progress and progress.completed),
                'material_id': material.id,
                'file_url': material.resource_url,
            })
        
        student_status = progress_map[week.id].status
        status_label = dict(StudentWeekProgress.STATUS_CHOICES).get(student_status, 'Locked')
        
        week_rows.append({
            'week_number': week.week_number,
            'title': week.title,
            'description': week.description,
            'topics': week.topics,
            'status': student_status,
            'status_label': status_label,
            'tag_style': f'font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 800; padding: 4px 9px; background: {"color-mix(in srgb, var(--color-text) 10%, transparent)" if student_status == "completed" else "var(--color-accent)" if student_status in ("available", "in_progress") else "transparent"}; color: {"inherit" if student_status == "completed" else "var(--color-bg)" if student_status in ("available", "in_progress") else "color-mix(in srgb, var(--color-text) 74%, transparent)"};',
            'items': material_items,
            'has_quiz': (
                hasattr(week, 'quiz')
                and week.quiz.is_published
                and not week.quiz.is_archived
                and (
                    week.quiz.program_id is None
                    or week.quiz.program_id == cohort_program_id
                )
                and (
                    week.quiz.cohort_id is None
                    or week.quiz.cohort_id == student.cohort_relation_id
                )
            ),
            'quiz_id': week.quiz.id if hasattr(week, 'quiz') else None,
        })
    
    context = {
        'student': student,
        'week_rows': week_rows,
        'materials_done': materials_done,
        'materials_total': materials_total,
        'role': 'student',
    }
    return render(request, 'crp/student/student_learning.html', context)

@role_required('student')
def student_quiz_list(request):
    """Quiz list and quiz attempt views"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    weeks = eligible_weeks(student)
    progress_rows = sync_student_progress(student)
    progress_map = {row.week_id: row for row in progress_rows}
    
    # Quiz statistics
    completed_attempts = QuizAttempt.objects.filter(student=student, completed_at__isnull=False)
    quiz_scores = [attempt.score for attempt in completed_attempts]
    quiz_average = int(sum(quiz_scores) / len(quiz_scores)) if quiz_scores else 0
    best_score = max(quiz_scores) if quiz_scores else 0
    
    quiz_stats = [
        {'label': 'Sets completed', 'value': f'{len(completed_attempts)} / {weeks.count()}'},
        {'label': 'Average score', 'value': f'{quiz_average}%' if quiz_scores else '—'},
        {'label': 'Best week', 'value': f'Week {completed_attempts.order_by("-score").first().quiz.week.week_number if completed_attempts else "—"}'},
        {'label': 'Attempts', 'value': str(completed_attempts.count())},
    ]
    
    quiz_weeks = []
    for week in weeks:
        if hasattr(week, 'quiz') and week.quiz.is_published and not week.quiz.is_archived and (
            (not week.quiz.program_id or week.quiz.program_id == student.cohort_relation.program_id)
            and (not week.quiz.cohort_id or week.quiz.cohort_id == student.cohort_relation_id)
        ):
            quiz = week.quiz
            attempt = completed_attempts.filter(quiz=quiz).first()
            
            score = attempt.score if attempt else None
            bar_width = score if score else 0
            
            quiz_weeks.append({
                'week_number': week.week_number,
                'title': week.title,
                'status': progress_map.get(week.id).status if progress_map.get(week.id) else 'locked',
                'score': score,
                'score_label': f'{score}%' if score is not None else '—',
                'bar_style': f'width: {bar_width}%; height: 100%; border-radius: 99px; background: linear-gradient(90deg, var(--c-1), var(--c-6));',
                'quiz_id': quiz.id,
                'locked': not progress_map.get(week.id) or progress_map[week.id].status == 'locked',
                'completed': attempt is not None,
            })
    
    context = {
        'student': student,
        'quiz_stats': quiz_stats,
        'quiz_weeks': quiz_weeks,
        'role': 'student',
    }
    return render(request, 'crp/student/student_quiz.html', context)

@role_required('student')
def student_quiz_take(request, quiz_id):
    """Take a specific quiz"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    quiz = get_object_or_404(
        Quiz,
        id=quiz_id,
        is_published=True,
        is_archived=False,
        week__in=eligible_weeks(student),
    )
    
    # Check if quiz is locked
    progress = next(
        (row for row in sync_student_progress(student) if row.week_id == quiz.week_id),
        None,
    )
    if not progress or progress.status == 'locked':
        messages.error(request, "This quiz is not available yet.")
        return redirect('crp:student_quiz')
    if progress.pk is None:
        progress.save()
    if progress.status == 'available':
        progress.status = 'in_progress'
        progress.save(update_fields=['status', 'updated_at'])
    
    # Create or get existing attempt
    attempt = QuizAttempt.objects.filter(
        student=student, quiz=quiz, completed_at__isnull=True
    ).first()
    created = attempt is None
    if created:
        question_ids = list(quiz.questions.filter(is_archived=False).order_by('?').values_list('id', flat=True)[:quiz.question_count])
        selected_questions = QuizQuestion.objects.filter(id__in=question_ids).prefetch_related('options')
        option_snapshots = {}
        for question in selected_questions:
            options = [
                {
                    'id': option.id,
                    'text': option.option_text,
                    'is_correct': option.is_correct,
                }
                for option in question.options.all()
            ]
            random.shuffle(options)
            option_snapshots[str(question.id)] = options
        attempt = QuizAttempt.objects.create(
            student=student,
            quiz=quiz,
            answers={},
            question_ids=question_ids,
            option_snapshots=option_snapshots,
        )
    
    if not created and attempt.completed_at:
        messages.info(request, f"You already completed this quiz with a score of {attempt.score}%")
        return redirect('crp:student_quiz')
    
    # Get questions
    question_ids = attempt.question_ids or list(quiz.questions.values_list('id', flat=True))
    questions = list(QuizQuestion.objects.filter(id__in=question_ids).prefetch_related('options'))
    question_order = {question_id: index for index, question_id in enumerate(question_ids)}
    questions.sort(key=lambda question: question_order.get(question.id, len(question_order)))
    for question in questions:
        question.shuffled_options = attempt.option_snapshots.get(str(question.id), [])
        if not question.shuffled_options:
            question.shuffled_options = [
                {'id': option.id, 'text': option.option_text, 'is_correct': option.is_correct}
                for option in question.options.all()
            ]
    
    if request.method == 'POST':
        # Process quiz submission
        answers = {}
        correct_count = 0
        
        for question in questions:
            selected_option_id = request.POST.get(f'question_{question.id}')
            if selected_option_id:
                selected_option = next(
                    (option for option in question.shuffled_options if str(option['id']) == str(selected_option_id)),
                    None,
                )
                if selected_option:
                    answers[str(question.id)] = {
                        'selected': selected_option_id,
                        'correct': selected_option['is_correct']
                    }
                    if selected_option['is_correct']:
                        correct_count += 1
        
        score = int((correct_count / len(questions)) * 100) if questions else 0
        
        attempt.answers = answers
        attempt.score = score
        attempt.completed_at = timezone.now()
        attempt.time_spent_minutes = int((timezone.now() - attempt.started_at).total_seconds() / 60)
        attempt.is_passed = score >= quiz.passing_score
        attempt.save()
        sync_student_progress(student)
        
        messages.success(request, f"Quiz submitted! Your score: {score}%")
        return redirect('crp:student_quiz')
    
    context = {
        'student': student,
        'quiz': quiz,
        'questions': questions,
        'attempt': attempt,
        'role': 'student',
    }
    return render(request, 'crp/student/student_quiz_take.html', context)

@role_required('student')
def student_assessments(request):
    """Student assessments list and details"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    assessments = eligible_assessments(student).order_by('due_date', 'week__week_number')
    
    # Assessment statistics
    submissions = AssessmentSubmission.objects.filter(student=student)
    submitted_count = submissions.filter(status__in=['submitted', 'marked', 'returned']).count()
    marked_submissions = list(
        submissions.filter(status__in=['marked', 'returned'], assessment__results_released=True)
        .exclude(marks_awarded__isnull=True)
    )
    average_mark = (
        int(sum((sub.marks_awarded / sub.assessment.max_marks) * 100 for sub in marked_submissions) / len(marked_submissions))
        if marked_submissions else 0
    )
    
    assess_stats = [
        {'label': 'Submitted', 'value': f'{submitted_count} / {assessments.count()}'},
        {'label': 'Awaiting marking', 'value': str(submissions.filter(status='submitted').count())},
        {'label': 'Average mark', 'value': f'{average_mark}%'},
        {'label': 'Due soon', 'value': str(assessments.filter(due_date__lte=timezone.now() + timedelta(days=7), due_date__gte=timezone.now()).count())},
    ]
    
    assess_rows = []
    for assessment in assessments:
        submission = submissions.filter(assessment=assessment).first()
        
        now = timezone.now()
        if submission and submission.status in ('marked', 'returned'):
            status = 'Marked'
        elif submission and submission.status == 'submitted':
            status = 'Awaiting Marking'
        elif submission and submission.status == 'draft':
            status = 'Draft Submission'
        elif assessment.due_date < now:
            status = 'Late'
        elif assessment.due_date <= now + timedelta(days=3):
            status = 'Due Soon'
        else:
            status = 'Upcoming'
        if submission and submission.status in ('marked', 'returned') and not assessment.results_released:
            status = 'Awaiting Marking'
        action_label = (
            'View Feedback' if submission and submission.status in ('marked', 'returned') and assessment.results_released
            else 'View Submission' if submission and submission.status == 'submitted'
            else 'Continue Draft' if submission and submission.status == 'draft'
            else 'Submit Work' if assessment.due_date >= now
            else 'View Assignment'
        )
        
        marks_label = (
            f'{submission.marks_awarded}/{assessment.max_marks}'
            if submission and assessment.results_released and submission.marks_awarded is not None
            else '—'
        )
        percentage = (
            round((submission.marks_awarded / assessment.max_marks) * 100, 1)
            if submission and submission.marks_awarded is not None and assessment.max_marks
            else None
        )
        
        assess_rows.append({
            'week': assessment.week.week_number,
            'title': assessment.title,
            'assessment_type': assessment.get_assessment_type_display(),
            'course': assessment.course_code,
            'meta': f"{assessment.course_code} · due {assessment.due_date.strftime('%d %b %Y, %H:%M')} · {assessment.max_marks} marks",
            'status': status,
            'status_label': status,
            'marks_label': marks_label,
            'percentage': percentage,
            'due_date': assessment.due_date,
            'weight': assessment.weight_percentage,
            'max_marks': assessment.max_marks,
            'resource_count': assessment.attachments.count(),
            'action_label': action_label,
            'assessment_id': assessment.id,
            'has_submission': submission is not None,
            'submission_id': submission.id if submission else None,
        })

    selected_filter = request.GET.get('filter', 'all')
    if selected_filter != 'all':
        assess_rows = [
            row for row in assess_rows
            if (
                selected_filter == 'upcoming' and row['status'] in ('Upcoming', 'Due Soon')
                or selected_filter == 'submitted' and row['status'] in ('Submitted', 'Awaiting Marking', 'Marked', 'Awaiting Marking')
                or selected_filter == 'awaiting' and row['status'] == 'Awaiting Marking'
                or selected_filter == 'marked' and row['status'] == 'Marked'
            )
        ]
    
    context = {
        'student': student,
        'assess_stats': assess_stats,
        'assess_rows': assess_rows,
        'selected_filter': selected_filter,
        'role': 'student',
    }
    return render(request, 'crp/student/student_assessments.html', context)

@role_required('student')
def student_assessment_detail(request, assessment_id):
    """Detailed view of a specific assessment"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    assessment = get_object_or_404(eligible_assessments(student), id=assessment_id)
    submission = AssessmentSubmission.objects.filter(
        student=student,
        assessment=assessment
    ).first()
    
    rubric_data = None
    if hasattr(assessment, 'rubric'):
        rubric = assessment.rubric
        criteria = rubric.criteria.all().order_by('order')
        
        rubric_criteria = []
        for criterion in criteria:
            rubric_criteria.append({
                'name': criterion.name,
                'max_marks': criterion.max_marks,
                'weight': criterion.weight_percentage,
                'description': criterion.description,
            })
        
        rubric_data = {
            'name': rubric.name,
            'description': rubric.description,
            'criteria': rubric_criteria,
        }
    
    context = {
        'student': student,
        'assessment': assessment,
        'submission': submission,
        'submission_percentage': (
            round((submission.marks_awarded / assessment.max_marks) * 100, 1)
            if submission and submission.marks_awarded is not None and assessment.max_marks
            else None
        ),
        'submitted_success': request.GET.get('submitted') == '1',
        'rubric': rubric_data,
        'attachments': assessment.attachments.all(),
        'role': 'student',
    }
    return render(request, 'crp/student/student_assessment_detail.html', context)

@role_required('student')
def student_assessment_submit(request, assessment_id):
    """Assessment submission interface"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    assessment = get_object_or_404(eligible_assessments(student), id=assessment_id)
    
    # Get or create submission
    submission, created = AssessmentSubmission.objects.get_or_create(
        student=student,
        assessment=assessment,
        defaults={'status': 'draft'}
    )
    
    rubric_data = None
    if hasattr(assessment, 'rubric'):
        rubric = assessment.rubric
        criteria = rubric.criteria.all().order_by('order')
        
        rubric_criteria = []
        for criterion in criteria:
            rubric_criteria.append({
                'id': criterion.id,
                'name': criterion.name,
                'max_marks': criterion.max_marks,
                'weight': criterion.weight_percentage,
                'description': criterion.description,
                'level_descriptions': criterion.level_descriptions,
            })
        
        rubric_data = {
            'name': rubric.name,
            'description': rubric.description,
            'criteria': rubric_criteria,
        }
    
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save_draft':
            submission.feedback = request.POST.get('comment', submission.feedback).strip()
            submission.save()
            messages.success(request, "Draft saved.")
            return redirect('crp:student_assessment_submit', assessment_id=assessment.id)
        
        # Handle file upload
        uploaded_file = request.FILES.get('submission_file')
        if uploaded_file and action == 'upload':
            extension = uploaded_file.name.rsplit('.', 1)[-1].lower() if '.' in uploaded_file.name else ''
            accepted_formats = {
                str(file_format).lower().lstrip('.')
                for file_format in (assessment.accepted_formats or [])
            }
            if accepted_formats and extension not in accepted_formats:
                messages.error(request, 'This file type is not accepted for the assessment.')
            elif uploaded_file.size <= 0:
                messages.error(request, 'Empty files cannot be uploaded.')
            elif uploaded_file.size > assessment.max_file_size_mb * 1024 * 1024:
                messages.error(request, f'Files must be {assessment.max_file_size_mb} MB or smaller.')
            elif submission.files.count() >= assessment.required_file_count:
                messages.error(request, f'You may upload up to {assessment.required_file_count} file(s) for this assessment.')
            else:
                SubmissionFile.objects.create(
                    submission=submission,
                    file=uploaded_file,
                    file_name=uploaded_file.name,
                    file_type=extension.upper(),
                    file_size=f"{uploaded_file.size / (1024*1024):.1f} MB"
                )
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': True})
                messages.success(request, f"File '{uploaded_file.name}' uploaded successfully")

        if action == 'delete_file':
            file_id = request.POST.get('file_id')
            submission_file = get_object_or_404(SubmissionFile, id=file_id, submission=submission)
            if submission.status in ('draft', 'submitted', 'marked', 'returned'):
                submission_file.file.delete(save=False)
                submission_file.delete()
                messages.success(request, 'File removed.')
        
        # Handle submission
        if action == 'submit':
            submission.feedback = request.POST.get('comment', submission.feedback).strip()
            if assessment.required_submission and submission.files.count() < assessment.required_file_count:
                messages.error(request, "Please upload at least one file before submitting.")
            else:
                submission.status = 'submitted'
                submission.submitted_at = timezone.now()
                submission.save()
                messages.success(request, "Assessment submitted successfully!")
                return redirect(f"{reverse('crp:student_assessment_detail', args=[assessment.id])}?submitted=1")
        
        if action == 'turnitin' and assessment.turnitin_enabled:
            messages.info(request, "Originality checking is not configured for this deployment.")
    
    # Submission facts
    sub_facts = [
        {'label': 'Weight', 'value': f'{assessment.weight_percentage}%'},
        {'label': 'Due', 'value': assessment.due_date.strftime('%d %b %Y')},
        {'label': 'Type', 'value': assessment.get_assessment_type_display()},
        {'label': 'Status', 'value': submission.get_status_display()},
    ]
    
    context = {
        'student': student,
        'assessment': assessment,
        'submission': submission,
        'rubric': rubric_data,
        'sub_facts': sub_facts,
        'files': submission.files.all(),
        'role': 'student',
    }
    return render(request, 'crp/student/student_assessment_submit.html', context)

# Student portal API endpoints for AJAX interactions
@role_required('student')
@require_POST
def toggle_material_progress(request):
    """Toggle material completion status"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'})
    
    payload = json.loads(request.body or '{}') if request.body else request.POST
    material_id = payload.get('material_id')
    material = get_object_or_404(LearningMaterial, id=material_id, week__in=eligible_weeks(student))
    week_progress = next(
        (row for row in sync_student_progress(student) if row.week_id == material.week_id),
        None,
    )
    if week_progress is None:
        return JsonResponse({'success': False, 'error': 'Week is not available'}, status=403)
    if week_progress.status == 'locked':
        return JsonResponse({'success': False, 'error': 'Week is locked'}, status=403)
    if week_progress.pk is None:
        week_progress.save()
    
    progress, created = MaterialProgress.objects.get_or_create(
        student=student,
        material=material,
        defaults={'completed': False}
    )
    
    progress.completed = not progress.completed
    if progress.completed:
        progress.completed_at = timezone.now()
    else:
        progress.completed_at = None
    progress.save()
    sync_student_progress(student)
    
    return JsonResponse({'success': True, 'completed': progress.completed})

@role_required('student')
@require_POST
def toggle_task_completion(request):
    """Toggle task completion status"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'})
    
    task_id = request.POST.get('task_id')
    task = get_object_or_404(StudentTask, id=task_id, student=student)
    
    task.completed = not task.completed
    if task.completed:
        task.completed_at = timezone.now()
    else:
        task.completed_at = None
    task.save()
    
    return JsonResponse({'success': True, 'completed': task.completed})

@role_required('student')
def student_tasks(request):
    """Student task management page with create/filter/edit/delete functionality."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    tasks = StudentTask.objects.filter(student=student).order_by('completed', 'due_date', '-created_at')

    priority = request.GET.get('priority', 'all')
    status = request.GET.get('status', 'all')
    if priority and priority != 'all':
        tasks = tasks.filter(priority=priority)
    if status and status != 'all':
        tasks = tasks.filter(completed=(status == 'completed'))

    if request.method == 'POST':
        action = request.POST.get('action', 'create')
        if action == 'create':
            title = (request.POST.get('title') or '').strip()
            if not title:
                messages.error(request, 'Task title is required.')
                return render(request, 'crp/student/student_tasks.html', {'student': student, 'tasks': tasks, 'priority': priority, 'status': status, 'role': 'student'})
            StudentTask.objects.create(
                student=student,
                title=title,
                description=request.POST.get('description', ''),
                priority=request.POST.get('priority', 'medium'),
                due_date=request.POST.get('due_date') or None,
                tag=request.POST.get('tag', 'Personal'),
                created_by='Student',
            )
            messages.success(request, 'Task created successfully.')
            tasks = StudentTask.objects.filter(student=student).order_by('completed', 'due_date', '-created_at')
            if priority and priority != 'all':
                tasks = tasks.filter(priority=priority)
            if status and status != 'all':
                tasks = tasks.filter(completed=(status == 'completed'))
            context = {
                'student': student,
                'tasks': tasks,
                'priority': priority,
                'status': status,
                'role': 'student',
            }
            return render(request, 'crp/student/student_tasks.html', context)

    context = {
        'student': student,
        'tasks': tasks,
        'priority': priority,
        'status': status,
        'role': 'student',
    }
    return render(request, 'crp/student/student_tasks.html', context)

@role_required('student')
def student_task_edit(request, task_id):
    """Edit an existing student task."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    task = get_object_or_404(StudentTask, id=task_id, student=student)
    if request.method == 'POST':
        task.title = (request.POST.get('title') or '').strip() or task.title
        task.description = request.POST.get('description', task.description)
        task.priority = request.POST.get('priority', task.priority)
        task.due_date = request.POST.get('due_date') or None
        task.tag = request.POST.get('tag', task.tag)
        task.save()
        messages.success(request, 'Task updated successfully.')
        return redirect('crp:student_tasks')

    context = {'student': student, 'task': task, 'role': 'student'}
    return render(request, 'crp/student/student_task_edit.html', context)

@role_required('student')
@require_POST
def student_task_delete(request, task_id):
    """Delete a student's task."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    task = get_object_or_404(StudentTask, id=task_id, student=student)
    task.delete()
    messages.success(request, 'Task deleted successfully.')
    return redirect('crp:student_tasks')

@role_required('student')
def student_messages(request):
    """List student-trainer message threads."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    related_trainers = User.objects.filter(
        Q(instructor_profile__assigned_courses__registrations__student=request.user, instructor_profile__assigned_courses__registrations__status__in=('approved', 'completed'))
        | Q(instructor_profile__courses__registrations__student=request.user, instructor_profile__courses__registrations__status__in=('approved', 'completed')),
        instructor_profile__isnull=False, is_active=True,
    ).distinct()

    if request.method == 'POST':
        trainer = get_object_or_404(
            related_trainers,
            id=request.POST.get('trainer_id'),
        )
        title = (request.POST.get('title') or '').strip() or 'New conversation'
        content = (request.POST.get('content') or '').strip()
        thread, _ = StudentMessageThread.objects.get_or_create(
            student=student,
            trainer=trainer,
            defaults={'title': title},
        )
        if content:
            StudentMessage.objects.create(
                thread=thread,
                sender=request.user,
                recipient=trainer,
                content=content,
            )
            thread.save(update_fields=['updated_at'])
            create_notification(
                trainer, f'New message from {request.user.get_full_name() or request.user.username}',
                content[:200], reverse('crp:trainer_messages'), 'message',
            )
        return redirect('crp:student_message_thread', thread_id=thread.id)

    threads = StudentMessageThread.objects.filter(student=student).order_by('-updated_at')
    thread_rows = []
    for thread in threads:
        preview_message = thread.messages.order_by('sent_at').first()
        thread_rows.append({
            'id': thread.id,
            'trainer_name': thread.trainer.get_full_name() or thread.trainer.username,
            'title': thread.title or 'Conversation',
            'last_message': preview_message.content if preview_message else 'No messages yet',
            'last_sent': preview_message.sent_at.strftime('%d %b %H:%M') if preview_message else '',
            'unread_count': thread.messages.filter(recipient=request.user, is_read=False).count(),
        })

    context = {
        'student': student,
        'threads': thread_rows,
        'trainers': related_trainers.order_by('first_name', 'last_name'),
        'role': 'student',
    }
    return render(request, 'crp/student/student_messages.html', context)

@role_required('student')
def student_message_thread(request, thread_id):
    """View a single conversation thread and allow replies."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    thread = get_object_or_404(StudentMessageThread, id=thread_id, student=student)
    if request.method == 'POST':
        if 'mark_read' in request.POST:
            unread = thread.messages.filter(recipient=request.user, is_read=False)
            for msg in unread:
                msg.is_read = True
                msg.read_at = timezone.now()
                msg.save()
            return JsonResponse({'success': True})
        content = (request.POST.get('content') or '').strip()
        if content:
            StudentMessage.objects.create(
                thread=thread,
                sender=request.user,
                recipient=thread.trainer,
                content=content,
                is_read=False,
            )
            thread.save(update_fields=['updated_at'])
            create_notification(
                thread.trainer, f'New message from {request.user.get_full_name() or request.user.username}',
                content[:200], reverse('crp:trainer_messages'), 'message',
            )
            messages.success(request, 'Message sent successfully.')
            return redirect('crp:student_message_thread', thread_id=thread.id)

    unread = thread.messages.filter(recipient=request.user, is_read=False)
    for msg in unread:
        msg.is_read = True
        msg.read_at = timezone.now()
        msg.save()

    messages_list = list(thread.messages.select_related('sender', 'recipient').all())
    context = {'student': student, 'thread': thread, 'messages': messages_list, 'role': 'student'}
    return render(request, 'crp/student/student_message_thread.html', context)

@role_required('student')
@require_POST
def student_message_send(request, thread_id):
    """Send a message in a thread."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'})

    thread = get_object_or_404(StudentMessageThread, id=thread_id, student=student)
    content = (request.POST.get('content') or '').strip()
    if not content:
        return JsonResponse({'success': False, 'error': 'Message content is required'})

    StudentMessage.objects.create(
        thread=thread,
        sender=request.user,
        recipient=thread.trainer,
        content=content,
        is_read=False,
    )
    create_notification(
        thread.trainer, f'New message from {request.user.get_full_name() or request.user.username}',
        content[:200], reverse('crp:trainer_messages'), 'message',
    )
    return redirect('crp:student_message_thread', thread_id=thread.id)

@role_required('student')
def student_notes(request):
    """Display trainer notes visible to the student."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    notes = StudentNote.objects.filter(student=student, is_published=True).order_by('-created_at')
    for note in notes.filter(is_read=False):
        note.is_read = True
        note.read_at = timezone.now()
        note.save(update_fields=['is_read', 'read_at'])

    context = {'student': student, 'notes': notes, 'role': 'student'}
    return render(request, 'crp/student/student_notes.html', context)

@role_required('student')
def student_calendar(request):
    """Student calendar with agenda and event creation."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    events = Event.objects.filter(student=student).order_by('date', 'time')
    live_sessions = LiveSession.objects.filter(
        is_published=True, is_archived=False,
        starts_at__gte=timezone.now(),
    ).filter(
        Q(program__isnull=True) | Q(program_id=student.cohort_relation.program_id if student.cohort_relation_id else None),
        Q(cohort__isnull=True) | Q(cohort_id=student.cohort_relation_id),
    ).order_by('starts_at')
    if not Registration.objects.filter(
        student=student.user, status__in=('approved', 'completed'),
    ).exists():
        live_sessions = live_sessions.none()
    if request.method == 'POST':
        action = request.POST.get('action', 'create')
        if action == 'create':
            title = (request.POST.get('title') or '').strip()
            if not title:
                messages.error(request, 'Event title is required.')
                return render(request, 'crp/student/student_calendar.html', {'student': student, 'events': events, 'live_sessions': live_sessions, 'agenda': events[:10], 'role': 'student'})
            Event.objects.create(
                student=student,
                title=title,
                description=request.POST.get('description', ''),
                event_type=request.POST.get('event_type', 'other'),
                date=request.POST.get('date') or timezone.now().date(),
                time=request.POST.get('time') or None,
                location=request.POST.get('location', ''),
            )
            messages.success(request, 'Event created successfully.')
            events = Event.objects.filter(student=student).order_by('date', 'time')
            agenda = list(events[:10])
            context = {'student': student, 'events': events, 'live_sessions': live_sessions, 'agenda': agenda, 'role': 'student'}
            return render(request, 'crp/student/student_calendar.html', context)

    agenda = list(events[:10])
    context = {'student': student, 'events': events, 'live_sessions': live_sessions, 'agenda': agenda, 'role': 'student'}
    return render(request, 'crp/student/student_calendar.html', context)

@role_required('student')
def student_calendar_event_edit(request, event_id):
    """Edit an event on the student calendar."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    event = get_object_or_404(Event, id=event_id, student=student)
    if request.method == 'POST':
        event.title = (request.POST.get('title') or '').strip() or event.title
        event.description = request.POST.get('description', event.description)
        event.event_type = request.POST.get('event_type', event.event_type)
        event.date = request.POST.get('date') or event.date
        event.time = request.POST.get('time') or event.time
        event.location = request.POST.get('location', event.location)
        event.save()
        messages.success(request, 'Event updated successfully.')
        return redirect('crp:student_calendar')

    context = {'student': student, 'event': event, 'role': 'student'}
    return render(request, 'crp/student/student_calendar_event_edit.html', context)


@role_required('student')
def student_live_sessions(request):
    """Show published live sessions eligible for the authenticated student."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    program_id = student.cohort_relation.program_id if student.cohort_relation_id else None
    has_approved_course = Registration.objects.filter(
        student=student.user, status__in=('approved', 'completed'),
    ).exists()
    sessions = LiveSession.objects.filter(
        is_published=True,
        is_archived=False,
        starts_at__gte=timezone.now(),
    ).filter(
        Q(program__isnull=True) | Q(program_id=program_id),
        Q(cohort__isnull=True) | Q(cohort_id=student.cohort_relation_id),
    ).order_by('starts_at')
    if not has_approved_course:
        sessions = sessions.none()
    return render(request, 'crp/student/student_live_sessions.html', {
        'student': student,
        'sessions': sessions,
        'role': 'student',
    })


@role_required('student')
def student_attendance(request):
    """Show attendance records and calculated percentage for the current student."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')
    records = AttendanceRecord.objects.filter(student=student).select_related(
        'schedule__course',
    )
    total = records.count()
    attended = records.filter(status__in=('present', 'late', 'excused')).count()
    percentage = round(attended * 100 / total) if total else 0
    return render(request, 'crp/student/student_attendance.html', {
        'student': student, 'records': records, 'attendance_percentage': percentage, 'role': 'student',
    })


@role_required('student')
def student_announcements(request):
    """Show published announcements available to students."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    program_id = student.cohort_relation.program_id if student.cohort_relation_id else None
    announcements = Announcement.objects.filter(published=True).filter(
        Q(program__isnull=True) | Q(program_id=program_id),
        Q(cohort__isnull=True) | Q(cohort_id=student.cohort_relation_id),
    ).order_by('-created_at')
    return render(request, 'crp/student/student_announcements.html', {
        'student': student,
        'announcements': announcements,
        'role': 'student',
    })


@role_required('student')
def student_requests(request):
    """Create and track support requests for the authenticated student only."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    eligible_assessments = eligible_assessments_for_student(student)
    if request.method == 'POST':
        subject = (request.POST.get('subject') or '').strip()
        description = (request.POST.get('description') or '').strip()
        if not subject or not description:
            messages.error(request, 'Subject and description are required.')
        else:
            assessment = get_object_or_404(
                eligible_assessments, id=request.POST.get('assessment_id')
            ) if request.POST.get('assessment_id') else None
            support_request = StudentRequest.objects.create(
                student=student,
                assessment=assessment,
                request_type=request.POST.get('request_type', 'other'),
                subject=subject,
                description=description,
                requested_date=request.POST.get('requested_date') or None,
            )
            trainer_ids = Instructor.objects.filter(
                Q(courses__registrations__student=student.user, courses__registrations__status__in=('approved', 'completed'))
                | Q(assigned_courses__registrations__student=student.user, assigned_courses__registrations__status__in=('approved', 'completed'))
            ).values_list('user_id', flat=True).distinct()
            for trainer_id in trainer_ids:
                create_notification(
                    User.objects.get(id=trainer_id),
                    'New student support request',
                    support_request.subject,
                    reverse('crp:trainer_reference_module', kwargs={'module': 'requests'}),
                    'request',
                )
            messages.success(request, 'Support request submitted.')
            return redirect('crp:student_requests')

    return render(request, 'crp/student/student_requests.html', {
        'student': student,
        'requests': StudentRequest.objects.filter(student=student),
        'eligible_assessments': eligible_assessments,
        'role': 'student',
    })


@role_required('student', 'trainer', 'admin')
def notifications(request):
    notifications_qs = Notification.objects.filter(user=request.user)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'mark_all_read':
            notifications_qs.filter(is_read=False).update(is_read=True, read_at=timezone.now())
        elif action == 'mark_read':
            notification = get_object_or_404(notifications_qs, id=request.POST.get('notification_id'))
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=['is_read', 'read_at'])
        return redirect('crp:portal_notifications')
    role = get_user_role(request.user)
    template = {
        'student': 'crp/student/student_notifications.html',
        'trainer': 'crp/trainer/trainer_notifications.html',
        'admin': 'crp/admin/admin_notifications.html',
    }[role]
    return render(request, template, {
        'notifications': notifications_qs,
        'role': role,
    })


@role_required('student', 'trainer', 'admin')
def support_tickets(request):
    role = get_user_role(request.user)
    if role == 'admin':
        tickets = SupportTicket.objects.all()
    elif role == 'student':
        tickets = SupportTicket.objects.filter(created_by=request.user)
    else:
        student_ids = _trainer_students(request.user).values_list('user_id', flat=True)
        tickets = SupportTicket.objects.filter(
            Q(created_by=request.user) | Q(created_by_id__in=student_ids)
        )
    if request.method == 'POST':
        action = request.POST.get('action', 'create')
        if action == 'create':
            subject = request.POST.get('subject', '').strip()
            description = request.POST.get('description', '').strip()
            if subject and description:
                ticket = SupportTicket.objects.create(
                    created_by=request.user, subject=subject, description=description,
                    category=request.POST.get('category', 'general'),
                    priority=request.POST.get('priority', 'normal'),
                )
                messages.success(request, 'Support ticket created.')
                return redirect('crp:support_tickets')
            messages.error(request, 'Subject and description are required.')
        elif role == 'admin':
            ticket = get_object_or_404(tickets, id=request.POST.get('ticket_id'))
            ticket.status = request.POST.get('status', ticket.status)
            ticket.priority = request.POST.get('priority', ticket.priority)
            ticket.assigned_to_id = request.POST.get('assigned_to') or None
            ticket.save(update_fields=['status', 'priority', 'assigned_to', 'updated_at'])
            content = request.POST.get('comment', '').strip()
            if content:
                SupportTicketComment.objects.create(ticket=ticket, author=request.user, content=content)
            messages.success(request, 'Support ticket updated.')
            return redirect('crp:support_tickets')
    return render(request, 'crp/support_tickets.html', {
        'tickets': tickets.select_related('created_by', 'assigned_to').prefetch_related('comments__author'),
        'role': role, 'admin_users': User.objects.filter(is_active=True).order_by('username') if role == 'admin' else [],
        'ticket_status_choices': SupportTicket.STATUS_CHOICES,
    })

@role_required('student')
def student_groups(request):
    """Display study groups and group membership for the student."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    groups = StudentGroup.objects.filter(
        Q(cohort__isnull=True) | Q(cohort_id=student.cohort_relation_id)
    ).order_by('name')
    my_group_ids = set(StudentGroupMember.objects.filter(student=student).values_list('group_id', flat=True))
    group_rows = []
    for group in groups:
        member_count = group.members.count()
        group_rows.append({
            'id': group.id,
            'name': group.name,
            'description': group.description,
            'member_count': member_count,
            'meeting_day': group.meeting_day or 'Flexible',
            'meeting_time': group.meeting_time.strftime('%H:%M') if group.meeting_time else 'TBD',
            'is_member': group.id in my_group_ids,
        })

    context = {'student': student, 'groups': group_rows, 'role': 'student'}
    return render(request, 'crp/student/student_groups.html', context)

@role_required('student')
def student_group_detail(request, group_id):
    """Student group detail page showing members and coordination details."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    group = get_object_or_404(
        StudentGroup,
        Q(cohort__isnull=True) | Q(cohort_id=student.cohort_relation_id),
        id=group_id,
    )
    members = StudentGroupMember.objects.filter(group=group).select_related('student__user').order_by('role', 'student__user__last_name')
    is_member = StudentGroupMember.objects.filter(group=group, student=student).exists()
    context = {'student': student, 'group': group, 'members': members, 'is_member': is_member, 'role': 'student'}
    return render(request, 'crp/student/student_group_detail.html', context)

@role_required('student')
@require_POST
def student_group_join(request, group_id):
    """Join a group as a student."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'})

    group = get_object_or_404(
        StudentGroup,
        Q(cohort__isnull=True) | Q(cohort_id=student.cohort_relation_id),
        id=group_id,
    )
    StudentGroupMember.objects.get_or_create(student=student, group=group, defaults={'role': 'member'})
    messages.success(request, f'You joined {group.name}.')
    return redirect('crp:student_group_detail', group_id=group.id)

@role_required('student')
@require_POST
def student_group_leave(request, group_id):
    """Leave a group."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'})

    group = get_object_or_404(
        StudentGroup,
        Q(cohort__isnull=True) | Q(cohort_id=student.cohort_relation_id),
        id=group_id,
    )
    StudentGroupMember.objects.filter(student=student, group=group).delete()
    messages.success(request, f'You left {group.name}.')
    return redirect('crp:student_groups')

@role_required('student')
def student_community(request):
    """Student community feed with announcements and student posts."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    program_id = student.cohort_relation.program_id if student.cohort_relation_id else None
    announcements = Announcement.objects.filter(
        published=True,
    ).filter(
        Q(program__isnull=True) | Q(program_id=program_id),
        Q(cohort__isnull=True) | Q(cohort_id=student.cohort_relation_id),
    ).order_by('-created_at')[:10]
    posts = StudentCommunityPost.objects.select_related('student__user', 'author_user').order_by('-created_at')

    if request.method == 'POST' and request.POST.get('action') == 'create_post':
        title = (request.POST.get('title') or '').strip()
        content = (request.POST.get('content') or '').strip()
        if not title or not content:
            messages.error(request, 'Post title and content are required.')
            return render(request, 'crp/student/student_community.html', {
                'student': student,
                'announcements': announcements,
                'posts': posts,
                'role': 'student',
            })
        StudentCommunityPost.objects.create(
            student=student,
            author_user=request.user,
            title=title,
            content=content,
        )
        messages.success(request, 'Post created successfully.')
        posts = StudentCommunityPost.objects.select_related('student__user', 'author_user').order_by('-created_at')

    context = {'student': student, 'announcements': announcements, 'posts': posts, 'role': 'student'}
    return render(request, 'crp/student/student_community.html', context)

@role_required('student')
def student_community_post_detail(request, post_id):
    """Display one community post with comments."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    post = get_object_or_404(StudentCommunityPost.objects.select_related('student__user', 'author_user'), id=post_id)

    if request.method == 'POST':
        comment = (request.POST.get('comment') or '').strip()
        if comment:
            StudentCommunityComment.objects.create(
                post=post,
                author=request.user,
                content=comment,
            )
            messages.success(request, 'Comment added successfully.')

    comments = StudentCommunityComment.objects.filter(post=post).select_related('author').order_by('created_at')
    context = {
        'student': student,
        'post': post,
        'comments': comments,
        'role': 'student',
    }
    return render(request, 'crp/student/student_community_post_detail.html', context)

@role_required('student')
def student_community_post_edit(request, post_id):
    """Edit a student's own community post."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    post = get_object_or_404(StudentCommunityPost, id=post_id)
    if post.student_id != student.id:
        return HttpResponseForbidden("You are not allowed to edit another student's post.")
    if request.method == 'POST':
        post.title = (request.POST.get('title') or '').strip() or post.title
        post.content = (request.POST.get('content') or '').strip() or post.content
        post.save()
        messages.success(request, 'Post updated successfully.')
        return redirect('crp:student_community')

    context = {'student': student, 'post': post, 'role': 'student'}
    return render(request, 'crp/student/student_community_post_edit.html', context)

@role_required('student')
@require_POST
def student_community_post_delete(request, post_id):
    """Delete a student's own community post."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    post = get_object_or_404(StudentCommunityPost, id=post_id)
    if post.student_id != student.id:
        return HttpResponseForbidden("You are not allowed to delete another student's post.")
    post.delete()
    messages.success(request, 'Post deleted successfully.')
    return redirect('crp:student_community')

@role_required('student')
@require_POST
def student_community_post_like(request, post_id):
    """Like a community post."""
    post = get_object_or_404(StudentCommunityPost, id=post_id)
    post.like_count += 1
    post.save(update_fields=['like_count', 'updated_at'])
    return JsonResponse({'success': True, 'like_count': post.like_count})

@role_required('student')
def student_settings(request):
    """Allow a student to manage their basic profile and portal preferences."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    preferences, _ = StudentPreference.objects.get_or_create(student=student)

    if request.method == 'POST':
        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        if first_name:
            request.user.first_name = first_name
        if last_name:
            request.user.last_name = last_name
        request.user.save(update_fields=['first_name', 'last_name'])

        student.phone = (request.POST.get('phone') or '').strip() or student.phone
        student.specialisation = request.POST.get('specialisation') or student.specialisation
        student.save(update_fields=['phone', 'specialisation'])

        preferences.email_notifications = 'email_notifications' in request.POST
        preferences.sms_notifications = 'sms_notifications' in request.POST
        preferences.community_digest = 'community_digest' in request.POST
        preferences.profile_visibility = request.POST.get('profile_visibility') or preferences.profile_visibility
        preferences.dashboard_theme = request.POST.get('dashboard_theme') or preferences.dashboard_theme
        preferences.save()

        messages.success(request, 'Settings updated successfully.')
        return redirect('crp:student_settings')

    context = {'student': student, 'preferences': preferences, 'user': request.user, 'role': 'student'}
    return render(request, 'crp/student/student_settings.html', context)

@role_required('student')
def student_settings_by_id(request, student_id):
    """Scope settings updates to the authorized student profile only."""
    try:
        current_student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    student = get_object_or_404(Student, id=student_id)
    if student.user_id != request.user.id:
        return HttpResponseForbidden('You are not allowed to edit another student\'s settings.')

    preferences, _ = StudentPreference.objects.get_or_create(student=student)
    if request.method == 'POST':
        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        if first_name:
            student.user.first_name = first_name
        if last_name:
            student.user.last_name = last_name
        student.user.save(update_fields=['first_name', 'last_name'])

        student.phone = (request.POST.get('phone') or '').strip() or student.phone
        student.specialisation = request.POST.get('specialisation') or student.specialisation
        student.save(update_fields=['phone', 'specialisation'])

        preferences.email_notifications = 'email_notifications' in request.POST
        preferences.sms_notifications = 'sms_notifications' in request.POST
        preferences.community_digest = 'community_digest' in request.POST
        preferences.profile_visibility = request.POST.get('profile_visibility') or preferences.profile_visibility
        preferences.dashboard_theme = request.POST.get('dashboard_theme') or preferences.dashboard_theme
        preferences.save()

        messages.success(request, 'Settings updated successfully.')
        return redirect('crp:student_settings')

    context = {'student': student, 'preferences': preferences, 'user': student.user, 'role': 'student'}
    return render(request, 'crp/student/student_settings.html', context)

# Career Section Views - Phase 2B
@role_required('admin')
def admin_job_sources(request):
    """Review configured external job sources and recent sync history."""
    if request.method == 'POST':
        if request.POST.get('action') == 'save_source':
            name = (request.POST.get('name') or '').strip()
            provider = (request.POST.get('provider') or 'adzuna').strip()
            country = (request.POST.get('country') or '').strip().lower()
            try:
                results_per_page = int(request.POST.get('results_per_page', '50'))
            except ValueError:
                messages.error(request, 'Results per page must be a number from 1 to 100.')
                return redirect('crp:admin_job_sources')
            if (
                not name or provider not in dict(JobSource.PROVIDER_CHOICES)
                or len(country) != 2 or not country.isascii() or not country.isalpha()
                or not 1 <= results_per_page <= 100
            ):
                messages.error(request, 'Enter a name, valid provider/country, and 1–100 results per page.')
                return redirect('crp:admin_job_sources')

            source_id = request.POST.get('source_id')
            source = get_object_or_404(JobSource, pk=source_id) if source_id else JobSource()
            if JobSource.objects.filter(name=name).exclude(pk=source.pk).exists():
                messages.error(request, f'A job source named "{name}" already exists.')
                return redirect('crp:admin_job_sources')
            source.name = name
            source.provider = provider
            source.country = country
            source.search_query = (request.POST.get('search_query') or '').strip()[:200]
            source.results_per_page = results_per_page
            source.is_enabled = 'is_enabled' in request.POST
            try:
                source.save()
            except ValidationError as exc:
                messages.error(request, f'Could not save source: {exc}')
            else:
                messages.success(request, f'Job source "{source.name}" saved.')
            return redirect('crp:admin_job_sources')

        source_id = request.POST.get('source_id')
        sources = JobSource.objects.filter(is_enabled=True)
        if source_id:
            sources = sources.filter(pk=source_id)
        if not sources.exists():
            messages.error(request, 'No enabled job source matched the requested sync.')
            return redirect('crp:admin_job_sources')
        had_error = False
        for source in sources:
            try:
                run = sync_job_source(source)
            except Exception as exc:
                had_error = True
                messages.error(request, f'{source.name} sync failed: {exc}')
            else:
                messages.success(
                    request,
                    f'{source.name}: {run.jobs_created} new and {run.jobs_updated} updated jobs.',
                )
        if had_error:
            messages.warning(request, 'One or more provider syncs failed; see the run history below.')
        return redirect('crp:admin_job_sources')

    return render(request, 'crp/admin/job_sources.html', {
        'sources': JobSource.objects.annotate(job_count=Count('jobs')).order_by('name'),
        'sync_runs': JobSyncRun.objects.select_related('source')[:20],
        'role': 'admin',
    })


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def cron_sync_jobs(request):
    """Vercel cron entry point protected by a constant-time bearer-token check."""
    expected_token = settings.JOB_CRON_SECRET
    supplied_token = request.headers.get('Authorization', '')
    expected_header = f'Bearer {expected_token}'
    if not expected_token or not hmac.compare_digest(supplied_token, 'Bearer ' + expected_token):
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    results = []
    errors = []
    for source in JobSource.objects.filter(is_enabled=True).order_by('pk'):
        try:
            run = sync_job_source(source)
        except Exception as exc:
            errors.append({'source': source.name, 'error': str(exc)})
        else:
            results.append({
                'source': source.name,
                'jobs_seen': run.jobs_seen,
                'jobs_created': run.jobs_created,
                'jobs_updated': run.jobs_updated,
            })
    return JsonResponse(
        {'results': results, 'errors': errors},
        status=502 if errors else 200,
    )


@role_required('student')
def student_jobs(request, recommendations=False):
    """Student job matching and application tracking"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    # Get search and filter parameters
    job_query = request.GET.get('q', '')
    job_field = request.GET.get('field', 'all').lower()
    
    preferences, _ = StudentPreference.objects.get_or_create(student=student)
    jobs = JobListing.objects.filter(is_active=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()),
    )
    
    # Apply field filter (SQLite doesn't support JSON contains, use alternative)
    if job_field and job_field != 'all':
        # Use simpler filtering that works with SQLite
        filtered_jobs = []
        for job in jobs:
            if job_field in job.fields:
                filtered_jobs.append(job)
        jobs = JobListing.objects.filter(id__in=[job.id for job in filtered_jobs])
    
    # Apply search filter
    if job_query:
        jobs = jobs.filter(
            Q(title__icontains=job_query) |
            Q(company__icontains=job_query) |
            Q(skills__icontains=job_query)
        )
    
    jobs = list(jobs.select_related('source').order_by('-posted_date'))
    
    # Get student's job applications
    applications = JobApplication.objects.filter(student=student)
    saved_jobs = set(applications.filter(status='saved').values_list('job_id', flat=True))
    applied_jobs = set(applications.filter(status='applied').values_list('job_id', flat=True))
    
    # Get student's resume skills for matching display
    student_skills = []
    try:
        resume = student.resume
        student_skills = [skill.lower() for skill in resume.skills]
    except Resume.DoesNotExist:
        pass
    
    # Compute matches per student rather than relying on a shared listing score.
    scored_jobs = [
        (job, recommendation_score(student, job, preferences, student_skills))
        for job in jobs
    ]
    if recommendations:
        scored_jobs.sort(key=lambda row: (row[1], row[0].posted_date), reverse=True)
        scored_jobs = [row for row in scored_jobs if row[1] > 0]
    else:
        scored_jobs.sort(key=lambda row: (row[1], row[0].posted_date), reverse=True)

    # Prepare job data
    job_rows = []
    for job, match in scored_jobs:
        is_saved = job.id in saved_jobs
        is_applied = job.id in applied_jobs
        
        # Determine status label
        if is_applied:
            status_label = 'Applied'
            status_style = 'background: var(--color-accent); color: var(--color-bg);'
        elif is_saved:
            status_label = 'Saved'
            status_style = 'background: color-mix(in srgb, var(--color-text) 9%, transparent); color: inherit;'
        else:
            status_label = job.fields[0] if job.fields else 'New'
            status_style = 'background: color-mix(in srgb, var(--color-text) 9%, transparent); color: inherit;'
        
        # Skills matching
        job_skills = job.skills if job.skills else []
        matching_skills = [skill for skill in job_skills if skill.lower() in student_skills]
        
        job_rows.append({
            'id': job.id,
            'title': job.title,
            'company': job.company,
            'location': job.location,
            'salary': job.salary,
            'match': match,
            'posted': job.posted_date.strftime('%d %b %Y'),
            'expires_at': job.expires_at,
            'status_label': status_label,
            'status_style': status_style,
            'is_saved': is_saved,
            'is_applied': is_applied,
            'skills': job_skills,
            'matching_skills': matching_skills,
            'source_name': job.source.name if job.source_id else 'SAHE',
            'apply_url': job.apply_url,
        })
    
    # Field filter options
    field_filters = ['all', 'ai', 'data', 'cybersecurity', 'pm', 'accounting', 'hospitality']
    
    context = {
        'student': student,
        'job_query': job_query,
        'job_field': job_field,
        'field_filters': field_filters,
        'job_rows': job_rows,
        'total_jobs': len(job_rows),
        'recommendations': recommendations,
        'recommended_jobs': job_rows[:6],
        'role': 'student',
    }
    return render(request, 'crp/student/student_jobs.html', context)


@role_required('student')
def student_job_applications(request, status=None):
    """Show this student's saved jobs or application tracking list."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    applications = JobApplication.objects.filter(student=student).select_related(
        'job', 'job__source',
    )
    if status:
        applications = applications.filter(status=status)
    return render(request, 'crp/student/student_applications.html', {
        'student': student,
        'applications': applications,
        'page_title': 'Saved jobs' if status == 'saved' else 'My applications',
        'role': 'student',
    })


@role_required('student')
def student_job_preferences(request):
    """Update the student's job matching preferences."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, 'Student profile not found.')
        return redirect('crp:dashboard')

    preferences, _ = StudentPreference.objects.get_or_create(student=student)
    if request.method == 'POST':
        preferences.job_keywords = [
            value.strip()[:80] for value in request.POST.get('job_keywords', '').split(',')
            if value.strip()
        ][:20]
        preferences.job_locations = [
            value.strip()[:100] for value in request.POST.get('job_locations', '').split(',')
            if value.strip()
        ][:20]
        preferences.job_remote_only = 'job_remote_only' in request.POST
        preferences.save(update_fields=[
            'job_keywords', 'job_locations', 'job_remote_only', 'updated_at',
        ])
        messages.success(request, 'Job preferences saved.')
        return redirect('crp:student_job_preferences')

    return render(request, 'crp/student/student_job_preferences.html', {
        'student': student,
        'preferences': preferences,
        'role': 'student',
    })


def job_detail_slug(job):
    return slugify(job.title)


@role_required('student')
def student_job_detail(request, job_slug):
    """Detailed view of a specific job"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    visible_jobs = JobListing.objects.filter(is_active=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    )
    if job_slug.isdigit():
        job = get_object_or_404(visible_jobs, id=int(job_slug))
    else:
        job = next(
            (listing for listing in visible_jobs if job_detail_slug(listing) == job_slug),
            None,
        )
        if job is None:
            raise Http404

    # Get student's application status
    application = JobApplication.objects.filter(student=student, job=job).first()
    
    # Get student's resume skills for gap analysis
    student_skills = []
    try:
        resume = student.resume
        student_skills = [skill.lower() for skill in resume.skills]
    except Resume.DoesNotExist:
        pass
    
    # Skills gap analysis
    job_skills = job.skills if job.skills else []
    matching_skills = [skill for skill in job_skills if skill.lower() in student_skills]
    missing_skills = [skill for skill in job_skills if skill.lower() not in student_skills]
    
    # Prepare skill display data
    job_skills_display = []
    for skill in job_skills:
        is_matching = skill.lower() in student_skills
        job_skills_display.append({
            'label': skill,
            'is_matching': is_matching,
            'style': f'font-size: 11px; padding: 3px 10px; border: 1px solid {"var(--color-accent)" if is_matching else "var(--color-divider)"}; color: {"var(--color-accent)" if is_matching else "inherit"};'
        })
    
    context = {
        'student': student,
        'job': job,
        'application': application,
        'job_skills_display': job_skills_display,
        'matching_skills': matching_skills,
        'missing_skills': missing_skills,
        'gap_note': f'Highlighted skills are already on your resume — add the rest to lift your match.' if missing_skills else 'All required skills are on your resume!',
        'apply_label': 'Interest recorded' if application and application.status == 'applied' else 'Record application',
        'save_label': 'Saved ✓' if application and application.status == 'saved' else 'Save for later',
        'linkedin_url': f"{reverse('crp:student_linkedin')}?job_id={job.id}",
        'role': 'student',
    }
    return render(request, 'crp/student/student_job_detail.html', context)

@role_required('student')
@require_POST
def student_save_job(request, job_id):
    """Save a job for later"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    job = get_object_or_404(JobListing, id=job_id)
    
    application, created = JobApplication.objects.get_or_create(
        student=student,
        job=job,
        defaults={'status': 'saved'}
    )
    
    if created:
        messages.success(request, f"Job '{job.title}' saved successfully")
    else:
        if application.status == 'saved':
            application.delete()
            messages.info(request, f"Job '{job.title}' removed from saved")
        elif application.status == 'applied':
            messages.info(request, 'Applied jobs cannot be moved back to saved.')
        else:
            application.status = 'saved'
            application.save()
            messages.success(request, f"Job '{job.title}' saved successfully")
    
    return redirect('crp:student_job_detail', job_slug=job_detail_slug(job))

@role_required('student')
@require_POST
def student_apply_job(request, job_id):
    """Apply to a job"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    job = get_object_or_404(JobListing, id=job_id)
    if not job.is_active or (job.expires_at and job.expires_at <= timezone.now()):
        messages.error(request, 'This job is no longer accepting applications.')
        return redirect('crp:student_job_detail', job_slug=job_detail_slug(job))
    
    application, created = JobApplication.objects.get_or_create(
        student=student,
        job=job,
        defaults={'status': 'applied', 'applied_at': timezone.now()}
    )
    
    if created:
        messages.success(request, f"Application link opened for {job.company}.")
    else:
        if application.status != 'applied':
            application.status = 'applied'
            application.applied_at = timezone.now()
            application.save()
            messages.success(request, f"Application link opened for {job.company}.")
        else:
            messages.info(request, f"You have already applied to {job.company}")
    
    if job.apply_url:
        return redirect(job.apply_url)
    return redirect('crp:student_job_detail', job_slug=job_detail_slug(job))

@role_required('student')
def student_resume(request):
    """Student resume builder and AI review"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    # Get or create resume
    resume, created = Resume.objects.get_or_create(
        student=student,
        defaults={
            'contact_email': student.user.email,
            'completeness_score': 0
        }
    )
    
    # Get resume experience and education
    experience = resume.experience.all().order_by('-is_current', '-start_date')
    education = resume.education.all().order_by('-is_current', '-end_date')
    
    visible_jobs = JobListing.objects.filter(is_active=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    ).select_related('source').order_by('-posted_date')
    selected_job_id = request.GET.get('job_id')
    selected_job = visible_jobs.filter(id=selected_job_id).first() if selected_job_id else None
    review = analyze_resume(resume, selected_job)
    completeness_items = {
        'headline': bool(resume.headline),
        'summary': bool(resume.summary),
        'skills': len(resume.skills) >= 5,
        'experience': experience.count() >= 1,
        'education': education.count() >= 1,
        'contact': bool(resume.contact_phone),
    }
    completed_items = sum(1 for item in completeness_items.values() if item)
    completeness_score = int((completed_items / len(completeness_items)) * 100)
    ai_score = review['overall_score']
    ai_feedback = review['scores']
    resume.completeness_score = completeness_score
    resume.ai_score = ai_score
    resume.ai_feedback = {'scores': ai_feedback, 'recommendations': review['recommendations']}
    resume.save()
    
    context = {
        'student': student,
        'resume': resume,
        'experience': experience,
        'education': education,
        'completeness_score': completeness_score,
        'ai_score': ai_score,
        'ai_feedback': ai_feedback,
        'review_recommendations': review['recommendations'],
        'review': review,
        'visible_jobs': visible_jobs,
        'selected_job': selected_job,
        'completeness_items': completeness_items,
        'is_tailoring': False,
        'role': 'student',
    }
    return render(request, 'crp/student/student_resume.html', context)

@role_required('student')
def student_export_resume(request):
    """Export resume as markdown"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    resume = get_object_or_404(Resume, student=student)
    experience = resume.experience.all()
    education = resume.education.all()
    
    # Generate markdown content
    md_content = f"# {student.user.get_full_name()}\n"
    if resume.headline:
        md_content += f"{resume.headline}\n\n"
    
    if resume.contact_email:
        md_content += f"**Email:** {resume.contact_email}\n"
    if resume.contact_phone:
        md_content += f"**Phone:** {resume.contact_phone}\n"
    if resume.contact_location:
        md_content += f"**Location:** {resume.contact_location}\n"
    md_content += "\n"
    
    if resume.summary:
        md_content += "## Summary\n"
        md_content += f"{resume.summary}\n\n"
    
    if experience.exists():
        md_content += "## Experience\n"
        for exp in experience:
            md_content += f"### {exp.role} — {exp.company}\n"
            dates = f"{exp.start_date.strftime('%b %Y')} — {'Present' if exp.is_current else exp.end_date.strftime('%b %Y')}"
            md_content += f"{dates}\n"
            for bullet in exp.bullets:
                md_content += f"- {bullet}\n"
            md_content += "\n"
    
    if education.exists():
        md_content += "## Education\n"
        for edu in education:
            md_content += f"### {edu.degree}\n"
            dates = f"{edu.start_date.strftime('%b %Y')} — {'Present' if edu.is_current else edu.end_date.strftime('%b %Y')}"
            md_content += f"{edu.institution} — {dates}\n"
            if edu.details:
                md_content += f"{edu.details}\n"
            md_content += "\n"
    
    if resume.skills:
        md_content += "## Skills\n"
        md_content += ", ".join(resume.skills) + "\n"
    
    response = HttpResponse(md_content, content_type='text/markdown')
    response['Content-Disposition'] = f'attachment; filename="{student.user.get_full_name().replace(" ", "_")}_resume.md"'
    return response

@role_required('student')
def student_tailor_resume(request, job_id):
    """Review a deterministic, student-owned tailored resume draft."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    job = get_object_or_404(JobListing, id=job_id)
    
    # The source is always the authenticated student's resume.
    resume, created = Resume.objects.get_or_create(
        student=student,
        defaults={
            'contact_email': student.user.email,
            'completeness_score': 0
        }
    )
    
    source_skills = list(resume.skills or [])
    requirements = extract_job_requirements(job)
    requirement_terms = {normalize_requirement(term) for term in requirements}
    job_text = ' '.join([job.title or '', job.description or ''] + [str(s) for s in requirements])
    job_terms = {normalize_requirement(term) for term in job_text.split() if len(normalize_requirement(term)) > 2}
    matching_skills = [
        skill for skill in source_skills
        if normalize_requirement(skill) in requirement_terms
    ]
    remaining_skills = [skill for skill in source_skills if skill not in matching_skills]
    ordered_experience = sorted(
        resume.experience.all(), key=lambda exp: (
            -sum(1 for word in job_terms if word in normalize_requirement(
                ' '.join([exp.role, exp.company] + list(exp.bullets or []))
            )),
            -int(exp.is_current), exp.order,
        ),
    )
    experience_data = [
        {'role': exp.role, 'company': exp.company, 'location': exp.location,
         'start_date': exp.start_date.isoformat(), 'end_date': exp.end_date.isoformat() if exp.end_date else '',
         'is_current': exp.is_current, 'bullets': list(exp.bullets or [])}
        for exp in ordered_experience
    ]
    education_data = [
        {'degree': edu.degree, 'institution': edu.institution, 'location': edu.location,
         'start_date': edu.start_date.isoformat(), 'end_date': edu.end_date.isoformat() if edu.end_date else '',
         'is_current': edu.is_current, 'details': edu.details}
        for edu in resume.education.all()
    ]
    source_skill_terms = {normalize_requirement(skill) for skill in source_skills}
    missing_skills = [
        skill for skill in requirements
        if normalize_requirement(skill) not in source_skill_terms
    ]
    requirements_available = bool(requirements)
    analysis = {
        'job_title': job.title,
        'requirements_available': requirements_available,
        'matched_skills': matching_skills,
        'missing_requirements': missing_skills,
        'matched_job_terms': sorted({
            term for term in job_terms
            if any(term in normalize_requirement(str(value)) for value in source_skills)
        }),
        'recommendations': [
            f"Review evidence for: {', '.join(missing_skills)}." if missing_skills else (
                'Your existing skills cover the listed requirements.'
                if requirements_available else
                'No reliable structured requirements were available. Review the job description before tailoring.'
            ),
            'Only existing resume content is included; add evidence in the source resume before tailoring again.',
        ],
    }
    draft = {
        'headline': resume.headline,
        'summary': resume.summary,
        'skills': matching_skills + remaining_skills,
        'experience': experience_data,
        'education': education_data,
    }
    if request.method == 'POST':
        latest = TailoredResume.objects.filter(student=student, job=job, source_resume=resume).order_by('-version').first()
        version = (latest.version + 1) if latest else 1
        tailored = TailoredResume.objects.create(
            student=student, job=job, source_resume=resume, version=version,
            headline=draft['headline'], summary=draft['summary'], skills=draft['skills'],
            contact_email=resume.contact_email, contact_phone=resume.contact_phone,
            contact_location=resume.contact_location,
            experience=draft['experience'], education=draft['education'], analysis=analysis,
        )
        return redirect('crp:student_tailored_resume', tailored_id=tailored.id)
    return render(request, 'crp/student/tailored_resume.html', {
        'student': student, 'job': job, 'resume': resume, 'draft': draft, 'analysis': analysis,
        'is_saved': False, 'role': 'student',
    })

@role_required('student')
def student_tailored_resume(request, tailored_id):
    student = get_object_or_404(Student, user=request.user)
    tailored = get_object_or_404(TailoredResume.objects.select_related('job', 'source_resume'), id=tailored_id, student=student)
    if request.method == 'POST':
        tailored.headline = request.POST.get('headline', '').strip()
        tailored.summary = request.POST.get('summary', '').strip()
        tailored.skills = [
            skill.strip() for skill in request.POST.get('skills', '').split(',')
            if skill.strip()
        ]
        tailored.contact_email = request.POST.get('contact_email', '').strip()
        tailored.contact_phone = request.POST.get('contact_phone', '').strip()
        tailored.contact_location = request.POST.get('contact_location', '').strip()
        tailored.save(update_fields=[
            'headline', 'summary', 'skills', 'contact_email', 'contact_phone',
            'contact_location', 'updated_at',
        ])
        messages.success(request, 'Tailored resume saved.')
        return redirect('crp:student_tailored_resume', tailored_id=tailored.id)
    return render(request, 'crp/student/tailored_resume.html', {
        'student': student, 'job': tailored.job, 'tailored': tailored, 'draft': tailored,
        'analysis': tailored.analysis, 'is_saved': True, 'role': 'student',
    })

@role_required('student')
def student_export_tailored_resume(request, tailored_id):
    student = get_object_or_404(Student, user=request.user)
    tailored = get_object_or_404(TailoredResume, id=tailored_id, student=student)
    lines = [f"# {student.user.get_full_name()}", tailored.headline, '']
    contact = ' · '.join(value for value in (
        tailored.contact_email, tailored.contact_phone, tailored.contact_location,
    ) if value)
    if contact:
        lines += [contact, '']
    if tailored.summary: lines += ['## Summary', tailored.summary, '']
    if tailored.skills: lines += ['## Skills', ', '.join(tailored.skills), '']
    if tailored.experience:
        lines += ['## Experience']
        for exp in tailored.experience:
            lines += [f"### {exp['role']} — {exp['company']}"]
            lines += [f"- {bullet}" for bullet in exp.get('bullets', [])]
        lines.append('')
    if tailored.education:
        lines += ['## Education'] + [f"### {edu['degree']} — {edu['institution']}" for edu in tailored.education]
    response = HttpResponse('\n'.join(lines), content_type='text/markdown')
    response['Content-Disposition'] = f'attachment; filename="{student.user.get_full_name().replace(" ", "_")}_{tailored.job.id}_tailored.md"'
    return response


@role_required('student')
def student_export_tailored_resume_pdf(request, tailored_id):
    student = get_object_or_404(Student, user=request.user)
    tailored = get_object_or_404(TailoredResume, id=tailored_id, student=student)
    content = generate_resume_pdf(
        student.user.get_full_name(),
        {
            'headline': tailored.headline,
            'summary': tailored.summary,
            'skills': tailored.skills,
            'contact_email': tailored.contact_email,
            'contact_phone': tailored.contact_phone,
            'contact_location': tailored.contact_location,
            'experience': tailored.experience,
            'education': tailored.education,
        },
        title=f'{tailored.job.title} resume',
    )
    if content is None:
        messages.error(request, 'PDF export is unavailable in this installation.')
        return redirect('crp:student_tailored_resume', tailored_id=tailored.id)
    response = HttpResponse(content, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="{student.user.get_full_name().replace(" ", "_")}_'
        f'{tailored.job.id}_tailored.pdf"'
    )
    return response

@role_required('student')
@require_POST
def resume_add_skill(request):
    """Add a skill to resume"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'}, status=400)
    
    skill = request.POST.get('skill', '').strip()
    if not skill:
        return JsonResponse({'success': False, 'error': 'Skill cannot be empty'}, status=400)
    
    resume, created = Resume.objects.get_or_create(
        student=student,
        defaults={
            'contact_email': student.user.email,
            'completeness_score': 0
        }
    )
    
    if skill not in resume.skills:
        resume.skills.append(skill)
        resume.save()
    
    return JsonResponse({'success': True, 'skills': resume.skills})

@role_required('student')
@require_POST
def resume_remove_skill(request):
    """Remove a skill from resume"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'}, status=400)
    
    skill = request.POST.get('skill', '').strip()
    if not skill:
        return JsonResponse({'success': False, 'error': 'Skill cannot be empty'}, status=400)
    
    resume = get_object_or_404(Resume, student=student)
    
    if skill in resume.skills:
        resume.skills.remove(skill)
        resume.save()
    
    return JsonResponse({'success': True, 'skills': resume.skills})

@role_required('student')
@require_POST
def resume_autosave(request):
    """Autosave resume fields"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'}, status=400)
    
    resume, created = Resume.objects.get_or_create(
        student=student,
        defaults={
            'contact_email': student.user.email,
            'completeness_score': 0
        }
    )
    
    # Update fields from POST data
    if 'headline' in request.POST:
        resume.headline = request.POST.get('headline', '')
    if 'summary' in request.POST:
        resume.summary = request.POST.get('summary', '')
    if 'email' in request.POST:
        resume.contact_email = request.POST.get('email', '')
    if 'phone' in request.POST:
        resume.contact_phone = request.POST.get('phone', '')
    if 'location' in request.POST:
        resume.contact_location = request.POST.get('location', '')
    
    # Recalculate completeness score
    experience = resume.experience.all()
    education = resume.education.all()
    
    completeness_items = {
        'headline': bool(resume.headline),
        'summary': bool(resume.summary),
        'skills': len(resume.skills) >= 5,
        'experience': experience.count() >= 1,
        'education': education.count() >= 1,
        'contact': bool(resume.contact_phone),
    }
    
    completed_items = sum(1 for item in completeness_items.values() if item)
    resume.completeness_score = int((completed_items / len(completeness_items)) * 100)
    
    resume.save()
    
    return JsonResponse({'success': True, 'completeness_score': resume.completeness_score})

@role_required('student')
@require_POST
def resume_add_experience(request):
    """Add experience entry to resume"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'}, status=400)
    
    resume = get_object_or_404(Resume, student=student)
    
    # Parse dates
    start_date_str = request.POST.get('start_date', '')
    end_date_str = request.POST.get('end_date', '')
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid date format'}, status=400)
    
    experience = ResumeExperience.objects.create(
        resume=resume,
        role=request.POST.get('role', ''),
        company=request.POST.get('company', ''),
        location=request.POST.get('location', ''),
        start_date=start_date,
        end_date=end_date,
        is_current=request.POST.get('is_current', 'off') == 'on',
        bullets=request.POST.getlist('bullets[]'),
        order=resume.experience.count()
    )
    
    return JsonResponse({'success': True, 'experience_id': experience.id})

@role_required('student')
@require_POST
def resume_edit_experience(request, exp_id):
    """Edit experience entry"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'}, status=400)
    
    resume = get_object_or_404(Resume, student=student)
    experience = get_object_or_404(ResumeExperience, id=exp_id, resume=resume)
    
    # Parse dates
    start_date_str = request.POST.get('start_date', '')
    end_date_str = request.POST.get('end_date', '')
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid date format'}, status=400)
    
    experience.role = request.POST.get('role', '')
    experience.company = request.POST.get('company', '')
    experience.location = request.POST.get('location', '')
    experience.start_date = start_date
    experience.end_date = end_date
    experience.is_current = request.POST.get('is_current', 'off') == 'on'
    experience.bullets = request.POST.getlist('bullets[]')
    experience.save()
    
    return JsonResponse({'success': True})

@role_required('student')
@require_POST
def resume_delete_experience(request, exp_id):
    """Delete experience entry"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'}, status=400)
    
    resume = get_object_or_404(Resume, student=student)
    experience = get_object_or_404(ResumeExperience, id=exp_id, resume=resume)
    experience.delete()
    
    return JsonResponse({'success': True})

@role_required('student')
@require_POST
def resume_add_bullet(request, exp_id):
    """Add bullet to experience"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'}, status=400)
    
    resume = get_object_or_404(Resume, student=student)
    experience = get_object_or_404(ResumeExperience, id=exp_id, resume=resume)
    
    bullet = request.POST.get('bullet', '').strip()
    if bullet:
        experience.bullets.append(bullet)
        experience.save()
    
    return JsonResponse({'success': True, 'bullets': experience.bullets})

@role_required('student')
@require_POST
def resume_edit_bullet(request, exp_id, bullet_index):
    """Edit bullet in experience"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'}, status=400)
    
    resume = get_object_or_404(Resume, student=student)
    experience = get_object_or_404(ResumeExperience, id=exp_id, resume=resume)
    
    bullet_index = int(bullet_index)
    if 0 <= bullet_index < len(experience.bullets):
        new_bullet = request.POST.get('bullet', '').strip()
        experience.bullets[bullet_index] = new_bullet
        experience.save()
    
    return JsonResponse({'success': True, 'bullets': experience.bullets})

@role_required('student')
@require_POST
def resume_delete_bullet(request, exp_id, bullet_index):
    """Delete bullet from experience"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'}, status=400)
    
    resume = get_object_or_404(Resume, student=student)
    experience = get_object_or_404(ResumeExperience, id=exp_id, resume=resume)
    
    bullet_index = int(bullet_index)
    if 0 <= bullet_index < len(experience.bullets):
        experience.bullets.pop(bullet_index)
        experience.save()
    
    return JsonResponse({'success': True, 'bullets': experience.bullets})

@role_required('student')
@require_POST
def resume_add_education(request):
    """Add education entry to resume"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'}, status=400)
    
    resume = get_object_or_404(Resume, student=student)
    
    # Parse dates
    start_date_str = request.POST.get('start_date', '')
    end_date_str = request.POST.get('end_date', '')
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid date format'}, status=400)
    
    education = ResumeEducation.objects.create(
        resume=resume,
        degree=request.POST.get('degree', ''),
        institution=request.POST.get('institution', ''),
        location=request.POST.get('location', ''),
        start_date=start_date,
        end_date=end_date,
        is_current=request.POST.get('is_current', 'off') == 'on',
        gpa=request.POST.get('gpa', ''),
        details=request.POST.get('details', ''),
        order=resume.education.count()
    )
    
    return JsonResponse({'success': True, 'education_id': education.id})

@role_required('student')
@require_POST
def resume_edit_education(request, edu_id):
    """Edit education entry"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'}, status=400)
    
    resume = get_object_or_404(Resume, student=student)
    education = get_object_or_404(ResumeEducation, id=edu_id, resume=resume)
    
    # Parse dates
    start_date_str = request.POST.get('start_date', '')
    end_date_str = request.POST.get('end_date', '')
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
    except ValueError:
        return JsonResponse({'success': False, 'error': 'Invalid date format'}, status=400)
    
    education.degree = request.POST.get('degree', '')
    education.institution = request.POST.get('institution', '')
    education.location = request.POST.get('location', '')
    education.start_date = start_date
    education.end_date = end_date
    education.is_current = request.POST.get('is_current', 'off') == 'on'
    education.gpa = request.POST.get('gpa', '')
    education.details = request.POST.get('details', '')
    education.save()
    
    return JsonResponse({'success': True})

@role_required('student')
@require_POST
def resume_delete_education(request, edu_id):
    """Delete education entry"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'}, status=400)
    
    resume = get_object_or_404(Resume, student=student)
    education = get_object_or_404(ResumeEducation, id=edu_id, resume=resume)
    education.delete()
    
    return JsonResponse({'success': True})

@role_required('student')
@require_POST
def resume_rerun_ai(request):
    """Analyze the authenticated student's Resume deterministically."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student profile not found'}, status=400)
    
    resume = get_object_or_404(Resume, student=student)
    
    selected_job_id = request.POST.get('job_id')
    job = JobListing.objects.filter(
        is_active=True,
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    ).filter(id=selected_job_id).first() if selected_job_id else None
    review = analyze_resume(resume, job)
    experience = resume.experience.all()
    education = resume.education.all()
    
    completeness_items = {
        'headline': bool(resume.headline),
        'summary': bool(resume.summary),
        'skills': len(resume.skills) >= 5,
        'experience': experience.count() >= 1,
        'education': education.count() >= 1,
        'contact': bool(resume.contact_phone),
    }
    
    completed_items = sum(1 for item in completeness_items.values() if item)
    completeness_score = int((completed_items / len(completeness_items)) * 100)
    
    ai_score = review['overall_score']
    ai_feedback = review['scores']
    resume.completeness_score = completeness_score
    resume.ai_score = ai_score
    resume.ai_feedback = {'scores': ai_feedback, 'recommendations': review['recommendations']}
    resume.save()
    
    return JsonResponse({
        'success': True,
        'ai_score': ai_score,
        'completeness_score': completeness_score,
        'ai_feedback': ai_feedback,
        'recommendations': review['recommendations'],
        'review': review,
    })

@role_required('student')
def student_interview(request):
    """Student mock interview landing page"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    # Get all active interview sets
    interview_sets = InterviewSet.objects.filter(is_active=True)
    
    # Get student's interview history
    attempts = InterviewAttempt.objects.filter(student=student, is_completed=True).order_by('-started_at')
    
    # Calculate statistics
    total_attempts = attempts.count()
    if total_attempts > 0:
        avg_score = sum(attempt.total_score for attempt in attempts) / total_attempts
    else:
        avg_score = 0
    
    total_questions = InterviewQuestion.objects.filter(interview_set__in=interview_sets).count()
    
    next_live = Event.objects.filter(
        student=student,
        event_type='interview',
        date__gte=timezone.localdate(),
        is_completed=False,
    ).order_by('date', 'time').first()
    iv_stats = [
        {'label': 'Sessions run', 'value': str(total_attempts)},
        {'label': 'Average self-rating', 'value': f'{avg_score:.1f}' if total_attempts else '—'},
        {'label': 'Question bank', 'value': str(total_questions)},
        {'label': 'Next live mock', 'value': next_live.date.strftime('%d %b') if next_live else '—'},
    ]
    
    # Prepare interview sets
    iv_sets = []
    for interview_set in interview_sets:
        question_count = interview_set.questions.count()
        iv_sets.append({
            'id': interview_set.id,
            'name': interview_set.name,
            'desc': interview_set.description,
            'meta': f'{question_count} questions · {interview_set.time_limit_minutes} min',
            'category': interview_set.get_category_display(),
        })
    
    # Prepare history
    iv_history = []
    for attempt in attempts[:6]:  # Last 6 attempts
        iv_history.append({
            'name': attempt.interview_set.name,
            'when': attempt.started_at.strftime('%d %b %Y'),
            'answered': len(attempt.answers),
            'score': f'{attempt.total_score}/5',
        })
    
    context = {
        'student': student,
        'iv_stats': iv_stats,
        'iv_sets': iv_sets,
        'iv_history': iv_history,
        'has_history': len(iv_history) > 0,
        'role': 'student',
    }
    return render(request, 'crp/student/student_interview.html', context)

@role_required('student')
def student_start_interview(request, set_id):
    """Start a mock interview session"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    interview_set = get_object_or_404(InterviewSet, id=set_id)
    
    # Create new interview attempt
    attempt = InterviewAttempt.objects.create(
        student=student,
        interview_set=interview_set,
        answers=[]
    )
    
    messages.success(request, f"Started {interview_set.name} - Good luck!")
    return redirect('crp:student_interview_session', attempt_id=attempt.id)

@role_required('student')
def student_interview_session(request, attempt_id):
    """Active interview session"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    attempt = get_object_or_404(InterviewAttempt, id=attempt_id, student=student)
    
    if attempt.is_completed:
        messages.info(request, "This interview session is already completed.")
        return redirect('crp:student_interview')
    
    questions = attempt.interview_set.questions.all().order_by('order')
    
    # Handle POST requests for answer submission
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'submit_answer':
            question_id = request.POST.get('question_id')
            answer_text = request.POST.get('answer', '')
            self_rating = request.POST.get('rating', 3)
            
            question = questions.filter(id=question_id).first()
            if question:
                # Add answer to answers list
                answers = attempt.answers if isinstance(attempt.answers, list) else []
                answers.append({
                    'question_id': question_id,
                    'question_text': question.question_text,
                    'answer': answer_text,
                    'rating': int(self_rating),
                    'word_count': len(answer_text.split()) if answer_text else 0
                })
                attempt.answers = answers
                attempt.save()
                
                # Check if all questions answered
                if len(answers) >= questions.count():
                    # Complete the interview
                    total_score = sum(a['rating'] for a in answers) / len(answers) if answers else 0
                    attempt.total_score = total_score
                    attempt.completed_at = timezone.now()
                    attempt.time_spent_minutes = int((timezone.now() - attempt.started_at).total_seconds() / 60)
                    attempt.is_completed = True
                    
                    # Generate deterministic feedback
                    avg_words = sum(a['word_count'] for a in answers) / len(answers) if answers else 0
                    feedback = []
                    
                    if avg_words < 90:
                        feedback.append(f"Your answers average {avg_words} words — short for an interview. Add the Result step with a number in every story.")
                    else:
                        feedback.append(f"Answer length averaged {avg_words} words, right in the target band for a strong spoken answer.")
                    
                    lowest_rated = min(answers, key=lambda x: x['rating']) if answers else None
                    if lowest_rated:
                        feedback.append(f"Your lowest self-rating was on \"{lowest_rated['question_text'][:50]}…\". Rehearse that one twice before the live mock.")
                    
                    feedback.append("Structure check: name the Situation in one sentence, then spend two-thirds of the answer on Action and Result.")
                    
                    attempt.feedback = feedback
                    attempt.save()
                    
                    messages.success(request, f"Interview completed! Your score: {total_score:.1f}/5")
                    return redirect('crp:student_interview')
        
        return redirect('crp:student_interview_session', attempt_id=attempt_id)
    
    # Get current question index
    current_answers = attempt.answers if isinstance(attempt.answers, list) else []
    current_index = len(current_answers)
    
    if current_index >= questions.count():
        messages.info(request, "All questions completed.")
        return redirect('crp:student_interview')
    
    current_question = questions[current_index]
    
    # Calculate remaining time (deterministic)
    total_time = attempt.interview_set.time_limit_minutes * 60
    elapsed = int((timezone.now() - attempt.started_at).total_seconds())
    remaining = max(0, total_time - elapsed)
    
    # Calculate progress percentage in view
    progress_percentage = int((current_index / questions.count() * 100)) if questions.count() > 0 else 0
    
    # Format timer display
    minutes = remaining // 60
    seconds = remaining % 60
    timer_display = f"{minutes}:{seconds:02d}"
    
    # Determine if time warning
    is_time_warning = remaining < 60
    
    # Calculate display index (1-based)
    current_index_display = current_index + 1
    
    # Determine if this is the last question
    is_last_question = current_index == questions.count() - 1
    
    context = {
        'student': student,
        'attempt': attempt,
        'interview_set': attempt.interview_set,
        'current_question': current_question,
        'current_index': current_index,
        'current_index_display': current_index_display,
        'is_last_question': is_last_question,
        'total_questions': questions.count(),
        'remaining_time': remaining,
        'progress_percentage': progress_percentage,
        'timer_display': timer_display,
        'is_time_warning': is_time_warning,
        'role': 'student',
    }
    return render(request, 'crp/student/student_interview_session.html', context)

@role_required('student')
def student_linkedin(request):
    """Student LinkedIn profile coach, scoped to the authenticated student."""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    linkedin, _ = LinkedInProfile.objects.get_or_create(student=student)
    resume = Resume.objects.filter(student=student).first()
    data = profile_data(student, resume)
    selected_job_id = request.POST.get('selected_job_id') or request.GET.get('job_id')
    visible_jobs = JobListing.objects.filter(is_active=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    ).select_related('source').order_by('-posted_date')
    selected_job = visible_jobs.filter(id=selected_job_id).first() if selected_job_id else None

    if request.method == 'POST':
        form = LinkedInProfileForm(request.POST)
        if form.is_valid():
            linkedin.headline = form.cleaned_data['headline']
            linkedin.about = form.cleaned_data['about']
            linkedin.save(update_fields=['headline', 'about', 'updated_at'])
            if resume is not None:
                resume.linkedin_url = form.cleaned_data['linkedin_url']
                resume.save(update_fields=['linkedin_url', 'last_updated'])
            elif form.cleaned_data['linkedin_url']:
                messages.error(request, 'Create your Resume before saving a LinkedIn URL.')
                return redirect('crp:student_linkedin')
            messages.success(request, 'LinkedIn profile updated.')
            target = reverse('crp:student_linkedin')
            if selected_job:
                target = f'{target}?job_id={selected_job.id}'
            return redirect(target)
    else:
        form = LinkedInProfileForm(initial={
            'headline': linkedin.headline,
            'about': linkedin.about,
            'linkedin_url': resume.linkedin_url if resume else '',
        })

    li_items = completeness_items(student, linkedin, resume, data)
    completed_points = sum(item['pts'] for item in li_items if item['done'])
    total_points = sum(item['pts'] for item in li_items)
    completeness_score = int((completed_points / total_points) * 100) if total_points > 0 else 0

    linkedin.completeness_score = completeness_score
    if completeness_score >= 85:
        linkedin.forecast_level = 'high'
    elif completeness_score >= 60:
        linkedin.forecast_level = 'moderate'
    else:
        linkedin.forecast_level = 'low'
    
    linkedin.completeness_items = {item['key']: item['done'] for item in li_items}
    linkedin.save(update_fields=['completeness_items', 'completeness_score', 'forecast_level', 'updated_at'])
    headline_suggestion = build_headline(student, data)
    about_suggestion = build_about(student, resume, data)
    job_analysis = None
    job_headline_suggestion = None
    job_about_suggestion = None
    if selected_job:
        job_analysis = job_profile_analysis(selected_job, linkedin, resume, data)
        job_analysis['job'] = selected_job
        job_analysis['match_percentage'] = (
            recommendation_score(student, selected_job, skills=data['skills'])
            if selected_job.skills else None
        )
        if job_analysis['has_reliable_requirements']:
            job_headline_suggestion = build_job_headline(student, data, selected_job, job_analysis)
            job_about_suggestion = build_job_about(student, resume, data, job_analysis)
        else:
            job_headline_suggestion = build_job_headline(student, data, selected_job, job_analysis)
            job_about_suggestion = build_about(student, resume, data)
    
    context = {
        'student': student,
        'linkedin': linkedin,
        'li_items': li_items,
        'completeness_score': completeness_score,
        'headline': linkedin.headline,
        'about': linkedin.about,
        'headline_suggestion': headline_suggestion,
        'about_suggestion': about_suggestion,
        'resume': resume,
        'education': data['education'],
        'experience': data['experience'],
        'skills': data['skills'],
        'form': form,
        'forecast': linkedin.get_forecast_level_display(),
        'forecast_note': 'Your profile is ready for review.' if completeness_score >= 85 else 'Complete the remaining profile items to improve your presentation.',
        'recommendations': profile_recommendations(linkedin, resume, data),
        'visible_jobs': visible_jobs,
        'selected_job': selected_job,
        'job_analysis': job_analysis,
        'job_headline_suggestion': job_headline_suggestion,
        'job_about_suggestion': job_about_suggestion,
        'job_detail_url': reverse('crp:student_job_detail', args=[job_detail_slug(selected_job)]) if selected_job else '',
        'tailor_url': reverse('crp:student_tailor_resume', args=[selected_job.id]) if selected_job else '',
        'apply_url': reverse('crp:student_apply_job', args=[selected_job.id]) if selected_job else '',
        'role': 'student',
    }
    return render(request, 'crp/student/student_linkedin.html', context)

@role_required('student')
def student_achievements(request):
    """Student achievements, badges, and leaderboard"""
    try:
        student = request.user.student_profile
    except Student.DoesNotExist:
        messages.error(request, "Student profile not found.")
        return redirect('crp:dashboard')
    
    evaluate_student_badges(student)
    if student.cohort:
        refresh_cohort_leaderboard(student.cohort)

    # Get student's earned badges
    earned_badges = StudentBadge.objects.filter(student=student, is_displayed=True).select_related('badge')
    earned_badge_ids = set(earned_badges.values_list('badge_id', flat=True))
    
    # Get all available badges
    all_badges = Badge.objects.filter(is_active=True)
    
    # Prepare badge rows
    badge_rows = []
    for badge in all_badges:
        is_earned = badge.id in earned_badge_ids
        badge_rows.append({
            'id': badge.id,
            'name': badge.name,
            'description': badge.description,
            'week': badge.week_earned,
            'points': badge.points,
            'color': badge.color,
            'is_earned': is_earned,
            'mark': '★' if is_earned else str(badge.week_earned) if badge.week_earned else '',
        })
    
    current_streak = calculate_current_streak(student)
    
    # Generate 21-day streak display
    streak_days = []
    for i in range(21):
        day_num = i + 1
        is_active = i < current_streak
        streak_days.append({
            'day': day_num,
            'is_active': is_active,
            'title': f'Day {day_num} — {"active" if is_active else "missed"}',
        })
    
    # Get leaderboard for student's cohort
    leaderboard = Leaderboard.objects.filter(cohort=student.cohort).order_by('rank') if student.cohort else Leaderboard.objects.none()
    
    # Prepare leaderboard data
    leaderboard_data = []
    for entry in leaderboard:
        is_current_user = entry.student_id == student.id
        leaderboard_data.append({
            'rank': entry.rank,
            'name': f"{entry.student.user.get_full_name()} (you)" if is_current_user else entry.student.user.get_full_name(),
            'spec': entry.student.get_specialisation_display(),
            'streak': entry.streak_days,
            'score': f"{entry.quiz_average}%",
            'is_current_user': is_current_user,
        })
    
    # Achievement statistics
    ach_stats = [
        {'label': 'Badges earned', 'value': f'{len(earned_badges)} / {all_badges.count()}'},
        {'label': 'Current streak', 'value': f'{current_streak} days' if current_streak else '—'},
        {'label': 'Cohort rank',         'value': f"{leaderboard.filter(student=student).first().rank if leaderboard.filter(student=student).exists() else 'No cohort assigned'} of {leaderboard.count()}" if student.cohort else 'No cohort assigned'},
        {'label': 'Points', 'value': str(calculate_student_points(student))},
    ]
    
    context = {
        'student': student,
        'ach_stats': ach_stats,
        'badge_rows': badge_rows,
        'streak_days': streak_days,
        'streak_note': (
            f'{current_streak}-day active streak based on recorded activity.'
            if current_streak else
            'Complete a learning item, quiz, or assessment to start your streak.'
        ),
        'leaderboard': leaderboard_data,
        'cohort': student.cohort,
        'role': 'student',
    }
    return render(request, 'crp/student/student_achievements.html', context)
