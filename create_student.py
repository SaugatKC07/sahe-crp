import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sahe_crp.settings')
django.setup()

from django.contrib.auth.models import User
from crp_app.models import Student
from django.utils import timezone
from datetime import timedelta

# Create a dummy student user
try:
    student = User.objects.create_user(
        username='teststudent',
        password='student123',
        email='teststudent@sahe.edu.au',
        first_name='Test',
        last_name='Student'
    )
    student.is_active = True
    student.save()
    Student.objects.get_or_create(
        user=student,
        defaults={
            'student_id': 'STU2026002',
            'specialisation': 'ai',
            'cohort': 'Q3 2026',
            'program_start_date': timezone.now().date() - timedelta(days=35),
            'program_end_date': timezone.now().date() + timedelta(days=21),
            'status': 'active',
            'attendance_percentage': 95,
            'employability_score': 72,
            'current_streak': 12,
        }
    )
    print("Student user created successfully!")
    print("Username: teststudent")
    print("Password: student123")
except Exception as e:
    print(f"Error creating student: {e}")
