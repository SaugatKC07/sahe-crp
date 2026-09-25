from django.contrib import admin
from .models import (
    Course, Registration, Schedule, Instructor, Room, TimeSlot,
    Department, Announcement, Waitlist,
    FinanceProfile, Invoice, MarketingProfile, Campaign, CampaignMetrics,
    UploadedImage, Program, Cohort, LearningWeek, LearningMaterial, Quiz, QuizQuestion,
    QuizOption,     Assessment, Rubric, RubricCriterion, AssessmentSubmission, SubmissionFile,
    LiveSession, StudentRequest, JobListing, JobApplication, JobSource, JobSyncRun
)

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'credits', 'level', 'status', 'created_at']
    list_filter = ['level', 'status', 'created_at']
    search_fields = ['code', 'name', 'description']

@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ['student', 'course', 'status', 'registration_date', 'semester']
    list_filter = ['status', 'semester', 'registration_date']
    search_fields = ['student__email', 'course__code', 'course__name']

@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ['course', 'day', 'time_slot', 'room', 'instructor']
    list_filter = ['day', 'time_slot', 'room']
    search_fields = ['course__code', 'instructor__user__first_name', 'instructor__user__last_name']

@admin.register(Instructor)
class InstructorAdmin(admin.ModelAdmin):
    list_display = ['user', 'employee_id', 'phone', 'department', 'status']
    list_filter = ['department', 'status']
    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'employee_id']

@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ['name', 'building', 'capacity', 'room_type']
    list_filter = ['building', 'room_type']
    search_fields = ['name', 'building']

@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ['name', 'start_time', 'end_time']
    search_fields = ['name']

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'description', 'created_at']
    search_fields = ['code', 'name']

@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ['title', 'priority', 'published', 'course', 'author', 'created_at']
    list_filter = ['priority', 'published', 'created_at']
    search_fields = ['title', 'content']

@admin.register(Waitlist)
class WaitlistAdmin(admin.ModelAdmin):
    list_display = ['student', 'course', 'semester', 'position', 'notified']
    list_filter = ['semester', 'notified']
    search_fields = ['student__email', 'course__code']

@admin.register(FinanceProfile)
class FinanceProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'employee_id', 'department', 'status', 'specialization']
    list_filter = ['department', 'status']
    search_fields = ['user__first_name', 'user__last_name', 'employee_id']

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'student', 'amount', 'due_date', 'status', 'created_at']
    list_filter = ['status', 'due_date', 'created_at']
    search_fields = ['invoice_number', 'student__email']

@admin.register(MarketingProfile)
class MarketingProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'employee_id', 'department', 'status', 'specialization']
    list_filter = ['department', 'status']
    search_fields = ['user__first_name', 'user__last_name', 'employee_id']

@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ['name', 'status', 'start_date', 'end_date', 'budget', 'created_by']
    list_filter = ['status', 'start_date', 'end_date']
    search_fields = ['name', 'description']

@admin.register(CampaignMetrics)
class CampaignMetricsAdmin(admin.ModelAdmin):
    list_display = ['campaign', 'impressions', 'clicks', 'conversions', 'cost', 'recorded_at']
    list_filter = ['recorded_at']
    search_fields = ['campaign__name']

@admin.register(UploadedImage)
class UploadedImageAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'uploaded_by', 'created_at']
    list_filter = ['category', 'created_at']
    search_fields = ['title', 'description', 'uploaded_by__email']
    readonly_fields = ['created_at', 'updated_at']


admin.site.register([
    Program, Cohort, LearningWeek, LearningMaterial, Quiz, QuizQuestion, QuizOption,
    Assessment, Rubric, RubricCriterion, AssessmentSubmission, SubmissionFile,
    LiveSession, StudentRequest,
])


@admin.register(JobSource)
class JobSourceAdmin(admin.ModelAdmin):
    list_display = ['name', 'provider', 'country', 'is_enabled', 'updated_at']
    list_filter = ['provider', 'country', 'is_enabled']
    search_fields = ['name', 'search_query']


@admin.register(JobSyncRun)
class JobSyncRunAdmin(admin.ModelAdmin):
    list_display = ['source', 'status', 'jobs_seen', 'jobs_created', 'jobs_updated', 'started_at']
    list_filter = ['status', 'source']
    readonly_fields = [
        'source', 'status', 'jobs_seen', 'jobs_created', 'jobs_updated',
        'error_message', 'started_at', 'finished_at',
    ]


admin.site.register(JobListing)
admin.site.register(JobApplication)
