from django.contrib.auth.models import User
from crp_app.models import Student
from django.conf import settings
import django
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sahe_crp.settings')
django.setup()

user = User.objects.filter(username='crp_student').first()
print(f'User exists: {user is not None}')
if user:
    print(f'User is active: {user.is_active}')
    print(f'Password check: {user.check_password("test123")}')
    print(f'User email: {user.email}')
    print(f'User is staff: {user.is_staff}')
    print(f'User is superuser: {user.is_superuser}')
    
    student = Student.objects.filter(user=user).first()
    print(f'Student profile exists: {student is not None}')
    if student:
        print(f'Student ID: {student.student_id}')
        print(f'Student status: {student.status}')
else:
    print('Creating user...')
    user = User.objects.create_user(
        username='crp_student',
        email='student@sahe.edu.au',
        password='test123',
        first_name='Alex',
        last_name='Student'
    )
    user.is_active = True
    user.save()
    print(f'User created: {user.username}')
    
    student = Student.objects.create(
        user=user,
        student_id='STU2026001',
        specialisation='ai',
        cohort='Q3 2026',
        program_start_date='2026-08-01',
        program_end_date='2026-09-24',
        status='active',
        attendance_percentage=95,
        employability_score=72,
        current_streak=12,
    )
    print(f'Student profile created')