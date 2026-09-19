"""Trainer/admin content-management actions for the student learning portal."""
from datetime import datetime
import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .decorators import get_user_role, role_required
from .material_uploads import validate_material_upload
from .models import (
    Assessment, AssessmentSubmission, Cohort, LearningMaterial, LearningWeek,
    Program, Quiz, QuizQuestion, QuizOption, Rubric, RubricCriterion, Course, Student,
    Notification,
)


def _trainer_course_codes(user):
    instructor = getattr(user, 'instructor_profile', None)
    if not instructor:
        return []
    return list(Course.objects.filter(
        Q(instructor=instructor) | Q(trainers=instructor)
    ).values_list('code', flat=True).distinct())


def _trainer_weeks(user):
    codes = _trainer_course_codes(user)
    assigned_courses = Course.objects.filter(
        Q(instructor=user.instructor_profile) | Q(trainers=user.instructor_profile)
    )
    cohort_ids = list(Cohort.objects.filter(
        students__user__registrations__course__in=assigned_courses,
        students__user__registrations__status__in=('approved', 'completed'),
    ).values_list('id', flat=True)) if getattr(user, 'instructor_profile', None) else []
    return LearningWeek.objects.filter(
        Q(assessments__course_code__in=codes)
        | Q(program__cohorts__id__in=cohort_ids),
    ).distinct()


def _can_manage_week(request, week):
    return get_user_role(request.user) == 'admin'


def _can_manage_assignment_week(user, week):
    return bool(
        get_user_role(user) == 'trainer'
        and week.course_id
        and week.course.code in _trainer_course_codes(user)
    )


def _can_manage_assessment(user, assessment):
    """Return whether a user may operate on an assessment in their scope."""
    role = get_user_role(user)
    if role == 'admin':
        return True
    return (
        role == 'trainer'
        and assessment.week_id
        and _can_manage_assignment_week(user, assessment.week)
        and assessment.course_code == assessment.week.course.code
    )


def _trainer_cohort_ids(user):
    instructor = getattr(user, 'instructor_profile', None)
    if not instructor:
        return []
    assigned_courses = Course.objects.filter(
        Q(instructor=instructor) | Q(trainers=instructor)
    )
    return list(Cohort.objects.filter(
        students__user__registrations__course__in=assigned_courses,
        students__user__registrations__status__in=('approved', 'completed'),
    ).values_list('id', flat=True))


@role_required('admin')
def content_management(request):
    """Small, database-backed index for the content-management foundation."""
    if get_user_role(request.user) != 'admin':
        return redirect('crp:trainer_assessments')
    weeks = LearningWeek.objects.all()
    assessments = Assessment.objects.all()
    context = {
        'programs': Program.objects.prefetch_related('cohorts'),
        'weeks': weeks.prefetch_related('materials', 'quiz'),
        'assessments': assessments.select_related('week', 'program', 'cohort'),
        'materials': LearningMaterial.objects.filter(week__in=weeks).select_related('week'),
        'quizzes': Quiz.objects.filter(week__in=weeks).select_related('week'),
        'rubrics': Rubric.objects.filter(assessment__in=assessments).prefetch_related('criteria'),
        'material_types': LearningMaterial.MATERIAL_TYPES,
    }
    return render(request, 'crp/trainer/content_management.html', context)


@role_required('admin')
def program_save(request, program_id=None):
    if get_user_role(request.user) != 'admin':
        return redirect('crp:dashboard')
    if request.method != 'POST':
        return redirect('crp:content_management')
    program = get_object_or_404(Program, pk=program_id) if program_id else Program()
    program.name = request.POST.get('name', '').strip()
    program.description = request.POST.get('description', '').strip()
    program.is_active = request.POST.get('is_active', 'on') == 'on'
    if program.name:
        program.save()
    return redirect('crp:content_management')


@role_required('admin')
def program_delete(request, program_id):
    if get_user_role(request.user) != 'admin':
        return redirect('crp:dashboard')
    if request.method == 'POST':
        get_object_or_404(Program, pk=program_id).delete()
    return redirect('crp:content_management')


@role_required('admin')
def cohort_save(request, cohort_id=None):
    if get_user_role(request.user) != 'admin':
        return redirect('crp:dashboard')
    if request.method != 'POST':
        return redirect('crp:content_management')
    program = get_object_or_404(Program, pk=request.POST.get('program'))
    cohort = get_object_or_404(Cohort, pk=cohort_id) if cohort_id else Cohort(program=program)
    cohort.program = program
    cohort.name = request.POST.get('name', '').strip()
    cohort.start_date = request.POST.get('start_date') or None
    cohort.end_date = request.POST.get('end_date') or None
    cohort.is_active = request.POST.get('is_active', 'on') == 'on'
    if cohort.name:
        cohort.save()
    return redirect('crp:content_management')


@role_required('admin')
def cohort_delete(request, cohort_id):
    if get_user_role(request.user) != 'admin':
        return redirect('crp:dashboard')
    if request.method == 'POST':
        get_object_or_404(Cohort, pk=cohort_id).delete()
    return redirect('crp:content_management')


@role_required('admin')
def week_save(request, week_id=None):
    if request.method != 'POST':
        return redirect('crp:content_management')
    week = get_object_or_404(LearningWeek, pk=week_id) if week_id else LearningWeek()
    course_id = request.POST.get('course')
    if course_id:
        week.course = get_object_or_404(Course, pk=course_id)
    week.week_number = int(request.POST.get('week_number') or 1)
    week.title = request.POST.get('title', '').strip()
    week.description = request.POST.get('description', '').strip()
    week.learning_objectives = request.POST.get('learning_objectives', '').strip()
    week.topics = [value.strip() for value in request.POST.get('topics', '').split(',') if value.strip()]
    release_value = request.POST.get('release_date')
    week.release_date = timezone.make_aware(datetime.fromisoformat(release_value)) if release_value else None
    week.completion_requirements = request.POST.get('completion_requirements', '').strip()
    week.require_materials = request.POST.get('require_materials') == 'on'
    week.require_quiz = request.POST.get('require_quiz') == 'on'
    week.require_assessment = request.POST.get('require_assessment') == 'on'
    week.is_published = request.POST.get('is_published') == 'on'
    week.program_id = request.POST.get('program') or None
    week.is_archived = request.POST.get('is_archived') == 'on'
    if week.title:
        week.save()
    return redirect('crp:content_management')


@role_required('admin')
def week_delete(request, week_id):
    if request.method == 'POST':
        get_object_or_404(LearningWeek, pk=week_id).delete()
    return redirect('crp:content_management')


@role_required('admin')
def quiz_delete(request, quiz_id):
    if request.method == 'POST':
        quiz = get_object_or_404(Quiz.objects.select_related('week'), pk=quiz_id)
        if _can_manage_week(request, quiz.week):
            quiz.delete()
    return redirect('crp:content_management')


@role_required('admin')
def quiz_question_delete(request, question_id):
    if request.method == 'POST':
        question = get_object_or_404(QuizQuestion.objects.select_related('quiz__week'), pk=question_id)
        if _can_manage_week(request, question.quiz.week):
            question.delete()
    return redirect('crp:content_management')


@role_required('admin')
def quiz_option_delete(request, option_id):
    if request.method == 'POST':
        option = get_object_or_404(QuizOption.objects.select_related('question__quiz__week'), pk=option_id)
        if _can_manage_week(request, option.question.quiz.week):
            option.delete()
    return redirect('crp:content_management')


@role_required('admin')
def quiz_question_save(request, question_id=None, quiz_id=None):
    if request.method != 'POST':
        return redirect('crp:content_management')
    question = get_object_or_404(QuizQuestion.objects.select_related('quiz__week'), pk=question_id) if question_id else QuizQuestion(quiz=get_object_or_404(Quiz.objects.select_related('week'), pk=quiz_id))
    if _can_manage_week(request, question.quiz.week):
        question.question_text = request.POST.get('question_text', '').strip()
        question.difficulty = request.POST.get('difficulty', 'medium')
        question.explanation = request.POST.get('explanation', '').strip()
        question.order = int(request.POST.get('order') or question.order or 0)
        if question.question_text:
            question.save()
    return redirect('crp:content_management')


@role_required('admin')
def quiz_option_save(request, option_id=None, question_id=None):
    if request.method != 'POST':
        return redirect('crp:content_management')
    option = get_object_or_404(QuizOption.objects.select_related('question__quiz__week'), pk=option_id) if option_id else QuizOption(question=get_object_or_404(QuizQuestion.objects.select_related('quiz__week'), pk=question_id))
    if _can_manage_week(request, option.question.quiz.week):
        option.option_text = request.POST.get('option_text', '').strip()
        option.is_correct = request.POST.get('is_correct') == 'on'
        option.order = int(request.POST.get('order') or option.order or 0)
        if option.option_text:
            option.save()
    return redirect('crp:content_management')


@role_required('admin', 'trainer')
def rubric_criterion_save(request, criterion_id=None, assessment_id=None):
    if request.method != 'POST':
        return redirect('crp:content_management')
    if criterion_id:
        criterion = get_object_or_404(RubricCriterion.objects.select_related('rubric__assessment__week'), pk=criterion_id)
        rubric = criterion.rubric
    else:
        assessment = get_object_or_404(Assessment.objects.select_related('week'), pk=assessment_id)
        rubric = get_object_or_404(Rubric, assessment=assessment)
        criterion = RubricCriterion(rubric=rubric)
    if get_user_role(request.user) == 'admin' or _can_manage_week(request, rubric.assessment.week):
        criterion.name = request.POST.get('name', '').strip()
        criterion.description = request.POST.get('description', '').strip()
        criterion.max_marks = int(request.POST.get('max_marks') or 1)
        criterion.weight_percentage = request.POST.get('weight_percentage') or 0
        raw_levels = request.POST.get('level_descriptions', '').strip()
        criterion.level_descriptions = json.loads(raw_levels) if raw_levels else {}
        criterion.order = int(request.POST.get('order') or criterion.order or 0)
        if criterion.name:
            criterion.save()
    return redirect('crp:content_management')


@role_required('admin', 'trainer')
def rubric_criterion_delete(request, criterion_id):
    if request.method == 'POST':
        criterion = get_object_or_404(RubricCriterion.objects.select_related('rubric__assessment__week'), pk=criterion_id)
        if get_user_role(request.user) == 'admin' or _can_manage_week(request, criterion.rubric.assessment.week):
            criterion.delete()
    return redirect('crp:content_management')


@role_required('admin', 'trainer')
def rubric_save(request, assessment_id):
    if request.method != 'POST':
        return redirect('crp:content_management')
    assessment = get_object_or_404(Assessment.objects.select_related('week'), pk=assessment_id)
    if get_user_role(request.user) != 'admin' and not _can_manage_week(request, assessment.week):
        return redirect('crp:content_management')
    rubric, _ = Rubric.objects.update_or_create(
        assessment=assessment,
        defaults={'name': request.POST.get('name', '').strip(), 'description': request.POST.get('description', '').strip()},
    )
    criterion = request.POST.get('criterion_name', '').strip()
    if criterion:
        RubricCriterion.objects.create(
            rubric=rubric, name=criterion, description=request.POST.get('criterion_description', '').strip(),
            max_marks=int(request.POST.get('criterion_max_marks') or 1),
            weight_percentage=request.POST.get('criterion_weight') or 0, order=rubric.criteria.count(),
        )
    return redirect('crp:content_management')


@role_required('admin')
def material_create(request):
    if request.method != 'POST':
        return redirect('crp:content_management')
    week = get_object_or_404(LearningWeek, pk=request.POST.get('week'))
    if not _can_manage_week(request, week):
        return redirect('crp:content_management')
    cohort_id = request.POST.get('cohort') or None
    program_id = request.POST.get('program') or None
    if get_user_role(request.user) == 'trainer' and (
        (cohort_id and int(cohort_id) not in _trainer_cohort_ids(request.user))
        or (program_id and not Cohort.objects.filter(
            id__in=_trainer_cohort_ids(request.user), program_id=program_id,
        ).exists())
    ):
        return redirect('crp:content_management')
    uploaded_file = request.FILES.get('file')
    material_type = request.POST.get('material_type', 'other')
    try:
        validate_material_upload(uploaded_file, material_type)
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect('crp:content_management')
    file_url = request.POST.get('file_url', '').strip()
    if not uploaded_file and not file_url:
        messages.error(request, 'Upload a PDF/video or provide a material URL.')
        return redirect('crp:content_management')
    material = LearningMaterial.objects.create(
        week=week,
        title=request.POST.get('title', '').strip(),
        material_type=material_type,
        file_url=file_url,
        file=uploaded_file,
        file_size=request.POST.get('file_size', '').strip(),
        duration=request.POST.get('duration', '').strip(),
        order=int(request.POST.get('order') or 0),
        program_id=program_id,
        cohort_id=cohort_id,
        is_published=request.POST.get('is_published') == 'on',
    )
    messages.success(request, f'Material "{material.title}" saved.')
    return redirect('crp:content_management')


@role_required('admin')
def material_publish(request, material_id):
    material = get_object_or_404(LearningMaterial, pk=material_id)
    if request.method == 'POST' and _can_manage_week(request, material.week):
        material.is_published = not material.is_published
        material.save(update_fields=['is_published', 'updated_at'])
    return redirect('crp:content_management')


@role_required('admin')
def quiz_create(request):
    if request.method != 'POST':
        return redirect('crp:content_management')
    week = get_object_or_404(LearningWeek, pk=request.POST.get('week'))
    if not _can_manage_week(request, week):
        return redirect('crp:content_management')
    quiz, _ = Quiz.objects.update_or_create(
        week=week,
        defaults={
            'title': request.POST.get('title', '').strip(),
            'description': request.POST.get('description', '').strip(),
            'question_count': int(request.POST.get('question_count') or 10),
            'time_limit_minutes': int(request.POST.get('time_limit_minutes') or 30),
            'passing_score': int(request.POST.get('passing_score') or 60),
            'program_id': request.POST.get('program') or None,
            'cohort_id': request.POST.get('cohort') or None,
        },
    )
    messages.success(request, f'Quiz "{quiz.title}" saved as a draft.')
    return redirect('crp:content_management')


@role_required('admin')
def quiz_publish(request, quiz_id):
    quiz = get_object_or_404(Quiz.objects.select_related('week'), pk=quiz_id)
    if request.method == 'POST' and _can_manage_week(request, quiz.week):
        quiz.is_published = not quiz.is_published
        quiz.save(update_fields=['is_published', 'updated_at'])
    return redirect('crp:content_management')


@role_required('admin')
def quiz_question_create(request, quiz_id):
    quiz = get_object_or_404(Quiz.objects.select_related('week'), pk=quiz_id)
    if request.method == 'POST' and _can_manage_week(request, quiz.week):
        question = QuizQuestion.objects.create(
            quiz=quiz,
            question_text=request.POST.get('question_text', '').strip(),
            difficulty=request.POST.get('difficulty', 'medium'),
            explanation=request.POST.get('explanation', '').strip(),
            order=quiz.questions.count(),
        )
        options = request.POST.getlist('option_text')
        correct = request.POST.get('correct_option')
        for index, text in enumerate(options):
            if text.strip():
                QuizOption.objects.create(
                    question=question, option_text=text.strip(), order=index,
                    is_correct=str(index) == str(correct),
                )
        messages.success(request, 'Question added to the question bank.')
    return redirect('crp:content_management')


@role_required('trainer')
def assessment_create(request):
    if request.method != 'POST':
        return redirect('crp:trainer_assessments')
    week = get_object_or_404(LearningWeek, pk=request.POST.get('week'))
    course_code = request.POST.get('course_code', '').strip()
    if not _can_manage_assignment_week(request.user, week) or course_code != week.course.code:
        messages.error(request, 'You can only create assignments for your assigned courses.')
        return redirect('crp:trainer_assessments')
    due_value = request.POST.get('due_date')
    due_date = timezone.make_aware(datetime.fromisoformat(due_value)) if due_value else timezone.now()
    assessment = Assessment.objects.create(
        week=week, course=week.course, title=request.POST.get('title', '').strip(),
        assessment_type=request.POST.get('assessment_type', 'assignment'),
        description=request.POST.get('description', '').strip(), course_code=course_code,
        max_marks=int(request.POST.get('max_marks') or 100),
        weight_percentage=int(request.POST.get('weight_percentage') or 10),
        due_date=due_date, accepted_formats=request.POST.getlist('accepted_formats'),
        instructions=request.POST.get('instructions', '').strip(),
        program_id=request.POST.get('program') or None, cohort_id=request.POST.get('cohort') or None,
    )
    messages.success(request, f'Assessment "{assessment.title}" saved as a draft.')
    return redirect('crp:trainer_assessments')


@role_required('admin', 'trainer')
def assessment_publish(request, assessment_id):
    assessment = get_object_or_404(Assessment.objects.select_related('week'), pk=assessment_id)
    allowed = _can_manage_assessment(request.user, assessment)
    if request.method == 'POST' and allowed:
        assessment.is_published = not assessment.is_published
        assessment.save(update_fields=['is_published', 'updated_at'])
        if assessment.is_published:
            for student in Student.objects.filter(
                user__registrations__course__code=assessment.course_code,
                user__registrations__status__in=('approved', 'completed'),
            ).select_related('user').distinct():
                Notification.objects.create(
                    user=student.user, title='New assignment published',
                    message=assessment.title,
                    target_url=f'/crp/student/assessments/{assessment.id}/',
                    category='assessment',
                )
    return redirect('crp:content_management')


@role_required('admin', 'trainer')
def assessment_archive(request, assessment_id):
    assessment = get_object_or_404(Assessment.objects.select_related('week'), pk=assessment_id)
    allowed = _can_manage_assessment(request.user, assessment)
    if request.method == 'POST' and allowed:
        assessment.is_archived = not assessment.is_archived
        assessment.save(update_fields=['is_archived', 'updated_at'])
    return redirect('crp:content_management')


@role_required('admin', 'trainer')
def assessment_release_results(request, assessment_id):
    assessment = get_object_or_404(Assessment.objects.select_related('week'), pk=assessment_id)
    allowed = _can_manage_assessment(request.user, assessment)
    if request.method == 'POST' and allowed:
        assessment.results_released = not assessment.results_released
        assessment.save(update_fields=['results_released', 'updated_at'])
        if assessment.results_released:
            for submission in AssessmentSubmission.objects.filter(assessment=assessment).select_related('student__user'):
                Notification.objects.create(
                    user=submission.student.user, title='Assessment results released',
                    message=assessment.title,
                    target_url=f'/crp/student/assessments/{assessment.id}/',
                    category='assessment',
                )
    return redirect('crp:content_management')


@role_required('admin', 'trainer')
def submission_mark(request, submission_id):
    submission = get_object_or_404(
        AssessmentSubmission.objects.select_related('assessment__week'),
        pk=submission_id,
    )
    allowed = _can_manage_assessment(request.user, submission.assessment)
    if request.method == 'POST' and allowed:
        marks = request.POST.get('marks_awarded')
        if marks not in (None, ''):
            submission.marks_awarded = min(max(int(marks), 0), submission.assessment.max_marks)
        submission.feedback = request.POST.get('feedback', '').strip()
        submission.status = 'marked'
        submission.marked_at = timezone.now()
        submission.save(update_fields=['marks_awarded', 'feedback', 'status', 'marked_at', 'updated_at'])
        Notification.objects.create(
            user=submission.student.user, title='Assignment feedback available',
            message=submission.assessment.title,
            target_url=f'/crp/student/assessments/{submission.assessment_id}/',
            category='assessment',
        )
        messages.success(request, 'Submission marked and feedback saved.')
    return redirect('crp:trainer_submission_detail', submission_id=submission.id)
