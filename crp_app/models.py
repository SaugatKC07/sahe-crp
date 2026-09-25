from django.db import models
from django.contrib.auth.models import User, Group
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.text import slugify
from django.utils import timezone
import os

def get_image_upload_path(instance, filename):
    """Dynamic upload path based on whether S3/R2 is enabled"""
    if os.environ.get('USE_S3', 'False').lower() == 'true':
        # For S3/R2, use simpler path structure
        return f'images/{filename}'
    else:
        # For local storage, use structured path
        return f'uploads/images/{filename}'

class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to=get_image_upload_path, blank=True, null=True, help_text="Department logo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

    class Meta:
        ordering = ['code']

class Instructor(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='instructor_profile')
    employee_id = models.CharField(max_length=20, unique=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, related_name='instructors')
    phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('on_leave', 'On Leave'),
    ], default='active')
    specialization = models.CharField(max_length=200, blank=True)
    qualification = models.CharField(max_length=200, blank=True)
    profile_image = models.ImageField(upload_to=get_image_upload_path, blank=True, null=True, help_text="Instructor profile photo")
    bio = models.TextField(blank=True, help_text="Professional biography")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.employee_id})"

    class Meta:
        ordering = ['user__last_name', 'user__first_name']

class Room(models.Model):
    name = models.CharField(max_length=50, unique=True)
    building = models.CharField(max_length=100)
    floor = models.IntegerField(default=1)
    capacity = models.IntegerField(validators=[MinValueValidator(1)])
    room_type = models.CharField(max_length=50, choices=[
        ('lecture', 'Lecture Hall'),
        ('lab', 'Laboratory'),
        ('seminar', 'Seminar Room'),
        ('online', 'Online/Remote'),
    ], default='lecture')
    equipment = models.TextField(blank=True, help_text="List available equipment")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.building} - {self.name} (Cap: {self.capacity})"

    class Meta:
        ordering = ['building', 'name']

class TimeSlot(models.Model):
    name = models.CharField(max_length=50, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.start_time} - {self.end_time})"

    class Meta:
        ordering = ['start_time']

class Course(models.Model):
    LEVEL_CHOICES = [
        ('certificate', 'Certificate'),
        ('diploma', 'Diploma'),
        ('bachelor', 'Bachelor'),
        ('master', 'Master'),
        ('doctorate', 'Doctorate'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('full', 'Full'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
    ]

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True, null=True)
    description = models.TextField()
    credits = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, related_name='courses')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    max_capacity = models.IntegerField(default=30, validators=[MinValueValidator(1)])
    current_enrollment = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    prerequisites = models.ManyToManyField('self', symmetrical=False, blank=True, related_name='prerequisite_for')
    instructor = models.ForeignKey(Instructor, on_delete=models.SET_NULL, null=True, blank=True, related_name='courses')
    trainers = models.ManyToManyField(
        Instructor,
        blank=True,
        related_name='assigned_courses',
        help_text='Trainers assigned to this course.',
    )
    start_date = models.DateField()
    end_date = models.DateField()
    image = models.ImageField(upload_to=get_image_upload_path, blank=True, null=True, help_text="Course cover image")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or slugify(self.code)
            candidate = base_slug
            queryset = Course.objects.exclude(pk=self.pk) if self.pk else Course.objects.all()
            if queryset.filter(slug=candidate).exists():
                candidate = f"{base_slug}-{slugify(self.code)}"
            suffix = 2
            while queryset.filter(slug=candidate).exists():
                candidate = f"{base_slug}-{slugify(self.code)}-{suffix}"
                suffix += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def enroll_student(self, student):
        if self.current_enrollment < self.max_capacity and self.status == 'active':
            self.current_enrollment += 1
            if self.current_enrollment >= self.max_capacity:
                self.status = 'full'
            self.save()
            return True
        return False

    def remove_student(self):
        if self.current_enrollment > 0:
            self.current_enrollment -= 1
            if self.status == 'full' and self.current_enrollment < self.max_capacity:
                self.status = 'active'
            self.save()
            return True
        return False

    class Meta:
        ordering = ['code']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['status']),
            models.Index(fields=['level']),
        ]

class Schedule(models.Model):
    DAY_CHOICES = [
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
    ]

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='schedules')
    day = models.CharField(max_length=10, choices=DAY_CHOICES)
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.PROTECT)
    room = models.ForeignKey(Room, on_delete=models.PROTECT)
    instructor = models.ForeignKey(Instructor, on_delete=models.SET_NULL, null=True, related_name='schedules')
    semester = models.CharField(max_length=20, help_text="e.g., 'Fall 2025', 'Spring 2026'")
    is_recurring = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.course.code} - {self.get_day_display()} {self.time_slot}"

    class Meta:
        ordering = ['day', 'time_slot']
        unique_together = ['day', 'time_slot', 'room', 'semester']

class Registration(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
        ('completed', 'Completed'),
    ]
    WORKFLOW_CHOICES = [
        ('submitted', 'Submitted'),
        ('in_review', 'In Review'),
        ('documents_required', 'Documents Required'),
        ('conditional_offer', 'Conditional Offer'),
        ('unconditional_offer', 'Unconditional Offer'),
        ('offer_sent', 'Offer Sent'),
        ('offer_accepted', 'Offer Accepted'),
        ('pending_finance', 'Pending Finance'),
        ('finance_cleared', 'Finance Cleared'),
        ('enrolled', 'Enrolled'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
    ]

    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='registrations')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='registrations')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    workflow_status = models.CharField(max_length=30, choices=WORKFLOW_CHOICES, default='submitted')
    semester = models.CharField(max_length=20)
    registration_date = models.DateTimeField(auto_now_add=True)
    approval_date = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_registrations')
    grade = models.CharField(max_length=5, blank=True, null=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def approve(self, approver):
        if self.status == 'pending':
            self.status = 'approved'
            self.approval_date = timezone.now()
            self.approved_by = approver
            self.course.enroll_student(self.student)
            self.save()
            return True
        return False

    def reject(self, approver, reason=''):
        if self.status == 'pending':
            self.status = 'rejected'
            self.approval_date = timezone.now()
            self.approved_by = approver
            self.notes = reason
            self.save()
            return True
        return False

    def withdraw(self):
        if self.status in ['approved', 'pending']:
            was_approved = self.status == 'approved'
            self.status = 'withdrawn'
            if was_approved:
                self.course.remove_student()
            self.save()
            return True
        return False

    def __str__(self):
        return f"{self.student.email} - {self.course.code} ({self.status})"

    class Meta:
        ordering = ['-registration_date']
        unique_together = ['student', 'course', 'semester']
        indexes = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['course', 'status']),
            models.Index(fields=['semester']),
        ]

class ApplicationDocument(models.Model):
    STATUS_CHOICES = [
        ('required', 'Required'),
        ('requested', 'Requested'),
        ('received', 'Received'),
        ('missing', 'Missing'),
        ('rejected', 'Rejected'),
        ('replacement_requested', 'Replacement Requested'),
        ('verified', 'Verified'),
    ]

    registration = models.ForeignKey(Registration, on_delete=models.CASCADE, related_name='documents')
    document_name = models.CharField(max_length=200)
    document_type = models.CharField(max_length=50, default='identity', blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='required')
    notes = models.TextField(blank=True)
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='document_requests')
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_documents')
    requested_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-requested_at']
        indexes = [models.Index(fields=['registration', 'status'])]

    def __str__(self):
        return f"{self.document_name} - {self.registration_id}"


class ApplicationContract(models.Model):
    TYPE_CHOICES = [
        ('conditional', 'Conditional Offer'),
        ('unconditional', 'Unconditional Offer'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('unsigned', 'Unsigned'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
    ]

    registration = models.ForeignKey(Registration, on_delete=models.CASCADE, related_name='contracts')
    contract_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default='conditional')
    title = models.CharField(max_length=200)
    contract_text = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='generated_contracts')
    sent_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_contracts')
    sent_at = models.DateTimeField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='accepted_contracts')
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['registration', 'contract_type']

    def __str__(self):
        return f"{self.registration.student.email} - {self.contract_type} ({self.status})"


class Waitlist(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='waitlists')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='waitlists')
    semester = models.CharField(max_length=20)
    position = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    notified = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.student.email} - {self.course.code} (Position: {self.position})"

    class Meta:
        ordering = ['position']
        unique_together = ['student', 'course', 'semester']

class Announcement(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='announcements', null=True, blank=True)
    program = models.ForeignKey('Program', on_delete=models.SET_NULL, null=True, blank=True, related_name='announcements')
    cohort = models.ForeignKey('Cohort', on_delete=models.SET_NULL, null=True, blank=True, related_name='announcements')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='announcements')
    priority = models.CharField(max_length=20, choices=[
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ], default='normal')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.title} ({self.get_priority_display()})"

    class Meta:
        ordering = ['-created_at']


class Notification(models.Model):
    """Persisted, user-specific portal notification."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='crp_notifications')
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    target_url = models.CharField(max_length=500, blank=True)
    category = models.CharField(max_length=40, default='general')
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        return f'{self.user.username}: {self.title}'


# Finance Department Models
class FinanceProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='finance_profile')
    employee_id = models.CharField(max_length=20, unique=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, related_name='finance_staff')
    phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('on_leave', 'On Leave'),
    ], default='active')
    specialization = models.CharField(max_length=200, blank=True, help_text="e.g., Accounts, Billing, Payroll")
    qualification = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.employee_id})"

    class Meta:
        ordering = ['user__last_name', 'user__first_name']

class Invoice(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('partial', 'Partial'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
    ]
    
    invoice_number = models.CharField(max_length=50, unique=True)
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invoices')
    registration = models.ForeignKey(Registration, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_invoices')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"INV-{self.invoice_number}"

    class Meta:
        ordering = ['-created_at']

class Payment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('card', 'Card'),
        ('bank_transfer', 'Bank Transfer'),
        ('cash', 'Cash'),
        ('invoice', 'Invoice'),
        ('other', 'Other'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments')
    application = models.ForeignKey(Registration, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField(default=timezone.now)
    payment_method = models.CharField(max_length=30, choices=PAYMENT_METHOD_CHOICES, default='card')
    transaction_reference = models.CharField(max_length=80, blank=True, default='')
    notes = models.TextField(blank=True)
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='processed_payments')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-payment_date', '-created_at']

    def __str__(self):
        return f"Payment {self.transaction_reference or self.id} - {self.amount}"

# Marketing Department Models
class MarketingProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='marketing_profile')
    employee_id = models.CharField(max_length=20, unique=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, related_name='marketing_staff')
    phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('on_leave', 'On Leave'),
    ], default='active')
    specialization = models.CharField(max_length=200, blank=True, help_text="e.g., Digital Marketing, Events, Content")
    qualification = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.employee_id})"

    class Meta:
        ordering = ['user__last_name', 'user__first_name']

class Campaign(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    name = models.CharField(max_length=200)
    description = models.TextField()
    start_date = models.DateField()
    end_date = models.DateField()
    budget = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    target_audience = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='campaigns')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name}"

    class Meta:
        ordering = ['-created_at']

class CampaignMetrics(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='metrics')
    impressions = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    conversions = models.IntegerField(default=0)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    recorded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.campaign.name} - {self.recorded_at}"

    class Meta:
        ordering = ['-recorded_at']

# Image/Document Management Model
class UploadedImage(models.Model):
    """Centralized model for managing uploaded images and documents"""
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to=get_image_upload_path)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='uploaded_images')
    category = models.CharField(max_length=50, choices=[
        ('course', 'Course Image'),
        ('instructor', 'Instructor Photo'),
        ('department', 'Department Logo'),
        ('announcement', 'Announcement Image'),
        ('document', 'Document'),
        ('other', 'Other'),
    ], default='other')
    alt_text = models.CharField(max_length=200, blank=True, help_text="Alternative text for accessibility")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.category})"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['category']),
            models.Index(fields=['uploaded_by']),
        ]

# Student Portal Models - Phase 2A
class Student(models.Model):
    """Extended student profile linked to User"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='student_profile')
    student_id = models.CharField(max_length=20, unique=True)
    specialisation = models.CharField(max_length=100, choices=[
        ('ai', 'Artificial Intelligence'),
        ('cybersecurity', 'Cybersecurity'),
        ('data_analytics', 'Data Analytics'),
        ('project_management', 'Project Management'),
        ('information_systems', 'Information Systems'),
    ], default='ai')
    phone = models.CharField(max_length=20, blank=True)
    cohort = models.CharField(max_length=50, help_text="e.g., Q3 2026")
    cohort_relation = models.ForeignKey('Cohort', on_delete=models.SET_NULL, null=True, blank=True, related_name='students')
    program_start_date = models.DateField()
    program_end_date = models.DateField()
    status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('graduated', 'Graduated'),
        ('suspended', 'Suspended'),
    ], default='active')
    attendance_percentage = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    employability_score = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    current_streak = models.IntegerField(default=0, help_text="Current day streak of activity")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.student_id})"

    class Meta:
        ordering = ['user__last_name', 'user__first_name']
        indexes = [
            models.Index(fields=['student_id']),
            models.Index(fields=['cohort']),
            models.Index(fields=['status']),
        ]

class LearningWeek(models.Model):
    """Weekly curriculum structure"""
    week_number = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='learning_weeks',
    )
    program = models.ForeignKey('Program', on_delete=models.CASCADE, null=True, blank=True, related_name='learning_weeks')
    title = models.CharField(max_length=200)
    description = models.TextField()
    topics = models.JSONField(default=list, help_text="List of topic tags")
    learning_objectives = models.TextField(blank=True)
    release_date = models.DateTimeField(null=True, blank=True)
    completion_requirements = models.TextField(blank=True)
    require_materials = models.BooleanField(default=False)
    require_quiz = models.BooleanField(default=False)
    require_assessment = models.BooleanField(default=False)
    is_published = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=[
        ('locked', 'Locked'),
        ('current', 'Current'),
        ('done', 'Done'),
    ], default='locked')
    is_archived = models.BooleanField(default=False)
    unlocks_after_week = models.IntegerField(null=True, blank=True, help_text="Week number that must be completed first")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Week {self.week_number}: {self.title}"

    class Meta:
        ordering = ['week_number']
        constraints = [
            models.UniqueConstraint(
                fields=['course', 'week_number'],
                name='unique_course_learning_week',
            ),
        ]


class Program(models.Model):
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Cohort(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='cohorts')
    name = models.CharField(max_length=100)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ['program', 'name']
        ordering = ['-start_date', 'name']

    def __str__(self):
        return f"{self.program.name} - {self.name}"


class StudentWeekProgress(models.Model):
    STATUS_CHOICES = [
        ('locked', 'Locked'),
        ('available', 'Available'),
        ('in_progress', 'In progress'),
        ('completed', 'Completed'),
    ]
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='week_progress')
    week = models.ForeignKey(LearningWeek, on_delete=models.CASCADE, related_name='student_progress')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='locked')
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['student', 'week']
        ordering = ['week__week_number']

class LearningMaterial(models.Model):
    """Individual learning materials within weeks"""
    MATERIAL_TYPES = [
        ('slides', 'Slide Deck'),
        ('pdf', 'PDF Document'),
        ('video', 'Video Recording'),
        ('workbook', 'Workbook'),
        ('link', 'External Link'),
        ('other', 'Other'),
    ]

    week = models.ForeignKey(LearningWeek, on_delete=models.CASCADE, related_name='materials')
    title = models.CharField(max_length=200)
    material_type = models.CharField(max_length=20, choices=MATERIAL_TYPES)
    file_url = models.URLField(blank=True, help_text="URL to the material file")
    file = models.FileField(
        upload_to='learning_materials/%Y/%m/',
        blank=True,
        null=True,
        help_text='Uploaded PDF or video file',
    )
    file_size = models.CharField(max_length=50, blank=True, help_text="e.g., '4.1 MB', '52 min'")
    duration = models.CharField(max_length=50, blank=True, help_text="For videos, e.g., '52 min'")
    order = models.IntegerField(default=0, help_text="Display order within the week")
    program = models.ForeignKey('Program', on_delete=models.SET_NULL, null=True, blank=True, related_name='materials')
    cohort = models.ForeignKey('Cohort', on_delete=models.SET_NULL, null=True, blank=True, related_name='materials')
    is_published = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.week.title})"

    @property
    def resource_url(self):
        """Prefer a managed upload while retaining support for external URLs."""
        if self.file:
            return self.file.url
        return self.file_url

    class Meta:
        ordering = ['week', 'order']

class MaterialProgress(models.Model):
    """Track student progress on individual materials"""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='material_progress')
    material = models.ForeignKey(LearningMaterial, on_delete=models.CASCADE, related_name='progress')
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.student.user.username} - {self.material.title}"

    class Meta:
        unique_together = ['student', 'material']
        indexes = [
            models.Index(fields=['student', 'completed']),
        ]

class Quiz(models.Model):
    """Quiz definitions for each week"""
    week = models.OneToOneField(LearningWeek, on_delete=models.CASCADE, related_name='quiz')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    question_count = models.IntegerField(default=10, validators=[MinValueValidator(1)])
    time_limit_minutes = models.IntegerField(default=30, help_text="Time limit in minutes")
    passing_score = models.IntegerField(default=60, validators=[MinValueValidator(0), MaxValueValidator(100)])
    program = models.ForeignKey('Program', on_delete=models.SET_NULL, null=True, blank=True, related_name='quizzes')
    cohort = models.ForeignKey('Cohort', on_delete=models.SET_NULL, null=True, blank=True, related_name='quizzes')
    is_adaptive = models.BooleanField(default=True, help_text="Difficulty adapts to answers")
    is_published = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} (Week {self.week.week_number})"

    class Meta:
        ordering = ['week']

class QuizQuestion(models.Model):
    """Individual quiz questions"""
    DIFFICULTY_CHOICES = [
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard'),
    ]

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default='medium')
    explanation = models.TextField(blank=True, help_text="Explanation shown after answering")
    order = models.IntegerField(default=0)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Q{self.order + 1}: {self.question_text[:50]}..."

    class Meta:
        ordering = ['quiz', 'order']

class QuizOption(models.Model):
    """Multiple choice options for quiz questions"""
    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE, related_name='options')
    option_text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)
    order = models.IntegerField(default=0, help_text="Display order (A, B, C, D)")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{chr(65 + self.order)}: {self.option_text[:30]}..."

    class Meta:
        ordering = ['question', 'order']

class QuizAttempt(models.Model):
    """Student quiz attempts"""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='quiz_attempts')
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='attempts')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    score = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    time_spent_minutes = models.IntegerField(null=True, blank=True)
    answers = models.JSONField(default=dict, help_text="Store question answers and correctness")
    question_ids = models.JSONField(default=list, help_text="Question snapshot used for this attempt")
    option_snapshots = models.JSONField(default=dict, help_text="Exact option text/order/correctness used for this attempt")
    is_passed = models.BooleanField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.user.username} - {self.quiz.title} ({self.score or 'In Progress'}%)"

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['student', 'quiz']),
            models.Index(fields=['student', '-started_at']),
        ]

class Assessment(models.Model):
    """Assessment definitions"""
    ASSESSMENT_TYPES = [
        ('assignment', 'Assignment'),
        ('project', 'Project'),
        ('presentation', 'Presentation'),
        ('exam', 'Exam'),
        ('quiz', 'Quiz'),
    ]

    week = models.ForeignKey(LearningWeek, on_delete=models.CASCADE, related_name='assessments')
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='assessments',
    )
    title = models.CharField(max_length=200)
    assessment_type = models.CharField(max_length=20, choices=ASSESSMENT_TYPES)
    description = models.TextField()
    course_code = models.CharField(max_length=20, help_text="e.g., 'CRP101'")
    max_marks = models.IntegerField(default=100, validators=[MinValueValidator(1)])
    weight_percentage = models.IntegerField(default=10, validators=[MinValueValidator(1), MaxValueValidator(100)])
    due_date = models.DateTimeField()
    accepted_formats = models.JSONField(default=list, help_text="List of accepted file formats")
    turnitin_enabled = models.BooleanField(default=False, help_text="Enable Turnitin plagiarism check")
    instructions = models.TextField(blank=True)
    is_published = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    results_released = models.BooleanField(default=False)
    required_submission = models.BooleanField(default=True)
    required_file_count = models.PositiveIntegerField(default=1)
    max_file_size_mb = models.PositiveIntegerField(default=500)
    program = models.ForeignKey('Program', on_delete=models.SET_NULL, null=True, blank=True, related_name='assessments')
    cohort = models.ForeignKey('Cohort', on_delete=models.SET_NULL, null=True, blank=True, related_name='assessments')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.course_code})"

    class Meta:
        ordering = ['week', 'due_date']
        indexes = [
            models.Index(fields=['week', 'due_date']),
        ]

class Rubric(models.Model):
    """Assessment rubric with criteria"""
    assessment = models.OneToOneField(Assessment, on_delete=models.CASCADE, related_name='rubric')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} for {self.assessment.title}"

class RubricCriterion(models.Model):
    """Individual rubric criteria"""
    rubric = models.ForeignKey(Rubric, on_delete=models.CASCADE, related_name='criteria')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    max_marks = models.IntegerField(validators=[MinValueValidator(1)])
    weight_percentage = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)])
    order = models.IntegerField(default=0)
    level_descriptions = models.JSONField(default=dict, help_text="Descriptions for each achievement level")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.max_marks} marks)"

    class Meta:
        ordering = ['rubric', 'order']

class AssessmentSubmission(models.Model):
    """Student assessment submissions"""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('marked', 'Marked'),
        ('returned', 'Returned'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='submissions')
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='submissions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    submitted_at = models.DateTimeField(null=True, blank=True)
    marked_at = models.DateTimeField(null=True, blank=True)
    marks_awarded = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    feedback = models.TextField(blank=True)
    turnitin_similarity = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    ai_detection_score = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    marker_comments = models.JSONField(default=dict, help_text="Comments per rubric criterion")
    is_late = models.BooleanField(default=False)
    extension_granted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.student.user.username} - {self.assessment.title} ({self.status})"

    class Meta:
        ordering = ['-submitted_at']
        unique_together = ['student', 'assessment']
        indexes = [
            models.Index(fields=['student', 'status']),
            models.Index(fields=['assessment', 'status']),
        ]

class SubmissionFile(models.Model):
    """Files attached to assessment submissions"""
    submission = models.ForeignKey(AssessmentSubmission, on_delete=models.CASCADE, related_name='files')
    file = models.FileField(upload_to='submissions/%Y/%m/')
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50, help_text="e.g., 'PDF', 'Word', 'Video'")
    file_size = models.CharField(max_length=50, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.file_name} ({self.submission})"

    class Meta:
        ordering = ['-uploaded_at']

class StudentTask(models.Model):
    """Personal tasks for students"""
    PRIORITY_CHOICES = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='tasks')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    tag = models.CharField(max_length=50, blank=True, help_text="e.g., 'Personal', 'Academic', 'Career'")
    created_by = models.CharField(max_length=100, default='Self', help_text="Who created the task")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.student.user.username})"

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['student', 'completed']),
            models.Index(fields=['student', 'due_date']),
        ]


class AttendanceRecord(models.Model):
    """Trainer-entered attendance for a student and scheduled teaching session."""
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('late', 'Late'),
        ('absent', 'Absent'),
        ('excused', 'Excused'),
    ]
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='attendance_records')
    schedule = models.ForeignKey('Schedule', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='attendance_records')
    session_date = models.DateField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='present')
    notes = models.CharField(max_length=500, blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='attendance_records')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-session_date', 'student__user__last_name']
        constraints = [
            models.UniqueConstraint(fields=['student', 'schedule', 'session_date'],
                                    name='unique_student_schedule_attendance'),
        ]

class Event(models.Model):
    """Calendar events for students"""
    EVENT_TYPES = [
        ('class', 'Class'),
        ('workshop', 'Workshop'),
        ('deadline', 'Deadline'),
        ('appointment', 'Appointment'),
        ('coaching', 'Career Coaching'),
        ('interview', 'Mock Interview'),
        ('other', 'Other'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='events')
    title = models.CharField(max_length=200)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    description = models.TextField(blank=True)
    date = models.DateField()
    time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} on {self.date}"

    class Meta:
        ordering = ['date', 'time']
        indexes = [
            models.Index(fields=['student', 'date']),
        ]


class LiveSession(models.Model):
    """Published live teaching/coaching session targeted to a program or cohort."""
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    program = models.ForeignKey('Program', on_delete=models.CASCADE, null=True, blank=True, related_name='live_sessions')
    cohort = models.ForeignKey('Cohort', on_delete=models.CASCADE, null=True, blank=True, related_name='live_sessions')
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    meeting_url = models.URLField(blank=True)
    recording_url = models.URLField(blank=True)
    is_published = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['starts_at']


class StudentRequest(models.Model):
    """Student support request and its trainer/admin response state."""
    REQUEST_TYPES = [
        ('academic', 'Academic support'),
        ('technical', 'Technical support'),
        ('career', 'Career support'),
        ('wellbeing', 'Wellbeing support'),
        ('other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_progress', 'In progress'),
        ('resolved', 'Resolved'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='requests')
    assessment = models.ForeignKey(
        'Assessment', on_delete=models.SET_NULL, null=True, blank=True, related_name='extension_requests',
    )
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPES, default='other')
    subject = models.CharField(max_length=200)
    description = models.TextField()
    requested_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    response = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

class StudentMessageThread(models.Model):
    """A student-trainer conversation thread."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='message_threads')
    trainer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='student_conversation_threads')
    title = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = ['student', 'trainer']

    def __str__(self):
        return f"{self.student.user.username} <> {self.trainer.username}"

class StudentMessage(models.Model):
    """Message in a student-trainer conversation."""
    thread = models.ForeignKey(StudentMessageThread, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_student_messages')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_student_messages')
    content = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['sent_at']

    def __str__(self):
        return f"{self.sender.username} -> {self.recipient.username}: {self.content[:40]}"

class StudentNote(models.Model):
    """Trainer notes that should be visible to the student."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='notes')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='student_notes')
    title = models.CharField(max_length=200)
    content = models.TextField()
    is_published = models.BooleanField(default=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student.user.username}: {self.title}"

class StudentGroup(models.Model):
    """Study and coordination groups for students."""
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    cohort = models.ForeignKey('Cohort', on_delete=models.SET_NULL, null=True, blank=True, related_name='student_groups')
    meeting_day = models.CharField(max_length=50, blank=True)
    meeting_time = models.TimeField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

class StudentGroupMember(models.Model):
    """Student membership in a group."""
    group = models.ForeignKey(StudentGroup, on_delete=models.CASCADE, related_name='members')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='group_memberships')
    role = models.CharField(max_length=50, default='member')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['group', 'student']
        ordering = ['role', 'student__user__last_name']

    def __str__(self):
        return f"{self.student.user.username} in {self.group.name} ({self.role})"


class SupportTicket(models.Model):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('in_progress', 'In progress'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]
    PRIORITY_CHOICES = [('low', 'Low'), ('normal', 'Normal'), ('high', 'High'), ('urgent', 'Urgent')]
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='support_tickets')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_support_tickets')
    subject = models.CharField(max_length=200)
    category = models.CharField(max_length=50, default='general')
    description = models.TextField()
    priority = models.CharField(max_length=12, choices=PRIORITY_CHOICES, default='normal')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class SupportTicketComment(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='support_ticket_comments')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class SuccessStory(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    student = models.ForeignKey(Student, on_delete=models.SET_NULL, null=True, blank=True, related_name='success_stories')
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True, related_name='success_stories')
    outcome_type = models.CharField(max_length=80, blank=True)
    employer = models.CharField(max_length=160, blank=True)
    role = models.CharField(max_length=160, blank=True)
    is_published = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_featured', '-created_at']

class StudentCommunityPost(models.Model):
    """Student community posts in the student portal."""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='community_posts')
    author_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='student_community_posts')
    title = models.CharField(max_length=200)
    content = models.TextField()
    like_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.author_user.username}: {self.title}"

class StudentCommunityComment(models.Model):
    """Comments on student community posts."""
    post = models.ForeignKey(StudentCommunityPost, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='student_community_comments')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.author.username} on {self.post.title}"

class StudentPreference(models.Model):
    """Student-facing preferences for the portal experience."""
    student = models.OneToOneField(Student, on_delete=models.CASCADE, related_name='preferences')
    email_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=False)
    community_digest = models.BooleanField(default=True)
    profile_visibility = models.CharField(
        max_length=20,
        choices=[
            ('private', 'Private'),
            ('cohort', 'Cohort Only'),
            ('students', 'Student Network'),
            ('public', 'Public'),
        ],
        default='cohort',
    )
    dashboard_theme = models.CharField(
        max_length=10,
        choices=[('light', 'Light'), ('dark', 'Dark')],
        default='light',
    )
    job_keywords = models.JSONField(default=list, blank=True)
    job_locations = models.JSONField(default=list, blank=True)
    job_remote_only = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preferences for {self.student.user.username}"

# Career Section Models - Phase 2B
class JobSource(models.Model):
    """Configuration for an external job listing provider."""
    PROVIDER_CHOICES = [('adzuna', 'Adzuna')]

    name = models.CharField(max_length=100, unique=True)
    provider = models.CharField(max_length=30, choices=PROVIDER_CHOICES, default='adzuna')
    country = models.CharField(max_length=2, default='au')
    search_query = models.CharField(max_length=200, blank=True)
    results_per_page = models.PositiveSmallIntegerField(default=50)
    is_enabled = models.BooleanField(default=True)
    sync_interval_hours = models.PositiveSmallIntegerField(default=6)
    configuration = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.get_provider_display()})"


class JobSyncRun(models.Model):
    """Audit record for a provider sync attempt."""
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
    ]

    source = models.ForeignKey(JobSource, on_delete=models.CASCADE, related_name='sync_runs')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')
    jobs_seen = models.PositiveIntegerField(default=0)
    jobs_created = models.PositiveIntegerField(default=0)
    jobs_updated = models.PositiveIntegerField(default=0)
    jobs_expired = models.PositiveIntegerField(default=0)
    jobs_stale = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.source.name} sync {self.started_at:%Y-%m-%d %H:%M} ({self.status})"


class JobListing(models.Model):
    """Job listings for student matching"""
    FIELD_CHOICES = [
        ('ai', 'Artificial Intelligence'),
        ('data', 'Data Analytics'),
        ('cybersecurity', 'Cybersecurity'),
        ('pm', 'Project Management'),
        ('accounting', 'Accounting'),
        ('hospitality', 'Hospitality'),
    ]

    title = models.CharField(max_length=200)
    company = models.CharField(max_length=200)
    location = models.CharField(max_length=200)
    salary = models.CharField(max_length=100, help_text="e.g., '$75K–$95K'")
    salary_min = models.IntegerField(null=True, blank=True, help_text="Minimum salary in thousands")
    salary_max = models.IntegerField(null=True, blank=True, help_text="Maximum salary in thousands")
    job_type = models.CharField(max_length=50, choices=[
        ('full_time', 'Full Time'),
        ('part_time', 'Part Time'),
        ('contract', 'Contract'),
        ('internship', 'Internship'),
    ], default='full_time')
    fields = models.JSONField(default=list, help_text="List of field categories")
    skills = models.JSONField(default=list, help_text="List of required skills")
    description = models.TextField()
    match_percentage = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    posted_date = models.DateField()
    application_deadline = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    source = models.ForeignKey(
        JobSource, on_delete=models.SET_NULL, null=True, blank=True, related_name='jobs',
    )
    source_external_id = models.CharField(max_length=255, blank=True)
    apply_url = models.URLField(max_length=1000, blank=True)
    is_remote = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} at {self.company}"

    class Meta:
        ordering = ['-match_percentage', '-posted_date']
        indexes = [
            models.Index(fields=['fields']),
            models.Index(fields=['match_percentage']),
            models.Index(fields=['posted_date']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'source_external_id'],
                condition=~models.Q(source_external_id=''),
                name='unique_job_source_external_id',
            ),
        ]

class JobApplication(models.Model):
    """Student job applications"""
    STATUS_CHOICES = [
        ('saved', 'Saved'),
        ('applied', 'Applied'),
        ('interview', 'Interview'),
        ('offered', 'Offered'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
    ]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='job_applications')
    job = models.ForeignKey(JobListing, on_delete=models.CASCADE, related_name='applications')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='saved')
    applied_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.student.user.username} - {self.job.title} ({self.status})"

    class Meta:
        ordering = ['-created_at']
        unique_together = ['student', 'job']
        indexes = [
            models.Index(fields=['student', 'status']),
        ]

class Resume(models.Model):
    """Student resume data"""
    student = models.OneToOneField(Student, on_delete=models.CASCADE, related_name='resume')
    headline = models.CharField(max_length=200, blank=True)
    summary = models.TextField(blank=True)
    skills = models.JSONField(default=list, help_text="List of skills")
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    contact_location = models.CharField(max_length=200, blank=True)
    linkedin_url = models.URLField(blank=True)
    github_url = models.URLField(blank=True)
    portfolio_url = models.URLField(blank=True)
    ai_score = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    ai_feedback = models.JSONField(default=dict, help_text="AI review feedback")
    completeness_score = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Resume for {self.student.user.username}"

    class Meta:
        indexes = [
            models.Index(fields=['completeness_score']),
        ]

class ResumeExperience(models.Model):
    """Work experience entries in resume"""
    resume = models.ForeignKey(Resume, on_delete=models.CASCADE, related_name='experience')
    role = models.CharField(max_length=200)
    company = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    bullets = models.JSONField(default=list, help_text="List of achievement bullets")
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.role} at {self.company}"

    class Meta:
        ordering = ['-is_current', '-start_date', 'order']

class ResumeEducation(models.Model):
    """Education entries in resume"""
    resume = models.ForeignKey(Resume, on_delete=models.CASCADE, related_name='education')
    degree = models.CharField(max_length=200)
    institution = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    gpa = models.CharField(max_length=10, blank=True)
    details = models.CharField(max_length=200, blank=True, help_text="e.g., 'Honours', 'Dean's List'")
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.degree} from {self.institution}"

    class Meta:
        ordering = ['-is_current', '-end_date', 'order']

class InterviewSet(models.Model):
    """Mock interview question sets"""
    name = models.CharField(max_length=200)
    description = models.TextField()
    category = models.CharField(max_length=100, choices=[
        ('technical', 'Technical'),
        ('behavioral', 'Behavioral'),
        ('situational', 'Situational'),
        ('mixed', 'Mixed'),
    ], default='mixed')
    question_count = models.IntegerField(default=5, validators=[MinValueValidator(1)])
    time_limit_minutes = models.IntegerField(default=15, help_text="Total time for the interview")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.category})"

    class Meta:
        ordering = ['category', 'name']

class InterviewQuestion(models.Model):
    """Individual interview questions"""
    DIFFICULTY_CHOICES = [
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard'),
    ]

    interview_set = models.ForeignKey(InterviewSet, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default='medium')
    hint = models.TextField(blank=True, help_text="Coach hint for students")
    target_word_count = models.IntegerField(default=150, help_text="Target word count for answer")
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Q{self.order + 1}: {self.question_text[:50]}..."

    class Meta:
        ordering = ['interview_set', 'order']

class InterviewAttempt(models.Model):
    """Student mock interview attempts"""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='interview_attempts')
    interview_set = models.ForeignKey(InterviewSet, on_delete=models.CASCADE, related_name='attempts')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    total_score = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(5)])
    time_spent_minutes = models.IntegerField(null=True, blank=True)
    answers = models.JSONField(default=list, help_text="List of answer objects with ratings")
    feedback = models.JSONField(default=list, help_text="AI coach feedback")
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.user.username} - {self.interview_set.name} ({self.total_score or 'In Progress'})"

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['student', '-started_at']),
        ]

class LinkedInProfile(models.Model):
    """Student LinkedIn profile optimization tracking"""
    student = models.OneToOneField(Student, on_delete=models.CASCADE, related_name='linkedin_profile')
    completeness_items = models.JSONField(default=dict, help_text="Dictionary of completion items with boolean status")
    completeness_score = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    headline = models.CharField(max_length=200, blank=True)
    about = models.TextField(blank=True)
    forecast_level = models.CharField(max_length=20, choices=[
        ('low', 'Low'),
        ('moderate', 'Moderate'),
        ('high', 'High'),
    ], default='low')
    last_reviewed = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"LinkedIn profile for {self.student.user.username}"

    class Meta:
        indexes = [
            models.Index(fields=['completeness_score']),
        ]

class Badge(models.Model):
    """Achievement badges"""
    name = models.CharField(max_length=100)
    description = models.TextField()
    icon = models.CharField(max_length=50, blank=True, help_text="Icon identifier")
    color = models.CharField(max_length=20, default='#0f7a5a')
    week_earned = models.IntegerField(null=True, blank=True, help_text="Week when badge can be earned")
    points = models.IntegerField(default=10, help_text="Points awarded for this badge")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name}"

    class Meta:
        ordering = ['week_earned', 'name']

class StudentBadge(models.Model):
    """Student earned badges"""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='badges')
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE, related_name='student_badges')
    earned_at = models.DateTimeField(auto_now_add=True)
    is_displayed = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.student.user.username} - {self.badge.name}"

    class Meta:
        ordering = ['-earned_at']
        unique_together = ['student', 'badge']
        indexes = [
            models.Index(fields=['student', '-earned_at']),
        ]

class Streak(models.Model):
    """Student activity streaks"""
    student = models.OneToOneField(Student, on_delete=models.CASCADE, related_name='streak')
    current_streak = models.IntegerField(default=0, help_text="Current consecutive days")
    longest_streak = models.IntegerField(default=0, help_text="Longest consecutive days")
    last_activity_date = models.DateField(null=True, blank=True)
    streak_history = models.JSONField(default=list, help_text="List of daily activity records")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Streak for {self.student.user.username}: {self.current_streak} days"

    class Meta:
        indexes = [
            models.Index(fields=['current_streak']),
        ]

class Leaderboard(models.Model):
    """Cohort leaderboard tracking"""
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='leaderboard_entries')
    cohort = models.CharField(max_length=50, help_text="e.g., 'Q3 2026'")
    total_points = models.IntegerField(default=0)
    quiz_average = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    badges_count = models.IntegerField(default=0)
    streak_days = models.IntegerField(default=0)
    rank = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.student.user.username} - Rank {self.rank} ({self.cohort})"

    class Meta:
        ordering = ['cohort', 'rank']
        unique_together = ['student', 'cohort']
        indexes = [
            models.Index(fields=['cohort', 'rank']),
        ]
