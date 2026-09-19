from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from crp_app.models import Instructor, Department

class Command(BaseCommand):
    help = 'Create test users for CRP Phase 1 testing'

    def handle(self, *args, **options):
        # Create groups if they don't exist
        admissions_group, _ = Group.objects.get_or_create(name='Admissions Staff')
        student_services_group, _ = Group.objects.get_or_create(name='Student Services Staff')

        # Create or get Department for Instructor
        dept, _ = Department.objects.get_or_create(
            code='CRP',
            defaults={'name': 'Career Readiness Program', 'description': 'CRP Department'}
        )

        # Create Student user
        student, created = User.objects.get_or_create(
            username='crp_student',
            defaults={
                'email': 'student@sahe.edu.au',
                'first_name': 'Alex',
                'last_name': 'Chen',
                'is_active': True,
            }
        )
        if created:
            student.set_password('test123')
            student.save()
            self.stdout.write(self.style.SUCCESS('[OK] Created Student user: crp_student / test123'))
        else:
            self.stdout.write(self.style.WARNING('[SKIP] Student user already exists: crp_student'))

        # Create Trainer user
        trainer, created = User.objects.get_or_create(
            username='crp_trainer',
            defaults={
                'email': 'trainer@sahe.edu.au',
                'first_name': 'Sarah',
                'last_name': 'Johnson',
                'is_active': True,
            }
        )
        if created:
            trainer.set_password('test123')
            trainer.save()
            # Create Instructor profile
            Instructor.objects.create(
                user=trainer,
                employee_id='TR001',
                department=dept,
                status='active',
                specialization='Career Coaching',
                qualification='M.Ed'
            )
            self.stdout.write(self.style.SUCCESS('[OK] Created Trainer user: crp_trainer / test123'))
        else:
            self.stdout.write(self.style.WARNING('[SKIP] Trainer user already exists: crp_trainer'))

        # Create Admissions user
        admissions, created = User.objects.get_or_create(
            username='crp_admissions',
            defaults={
                'email': 'admissions@sahe.edu.au',
                'first_name': 'Emma',
                'last_name': 'Williams',
                'is_active': True,
                'is_staff': True,  # Staff member for admissions
            }
        )
        if created:
            admissions.set_password('test123')
            admissions.save()
            admissions.groups.add(admissions_group)
            self.stdout.write(self.style.SUCCESS('[OK] Created Admissions user: crp_admissions / test123'))
        else:
            self.stdout.write(self.style.WARNING('[SKIP] Admissions user already exists: crp_admissions'))

        # Create Admin user
        admin, created = User.objects.get_or_create(
            username='crp_admin',
            defaults={
                'email': 'admin@sahe.edu.au',
                'first_name': 'System',
                'last_name': 'Administrator',
                'is_active': True,
                'is_superuser': True,
                'is_staff': True,
            }
        )
        if created:
            admin.set_password('test123')
            admin.save()
            self.stdout.write(self.style.SUCCESS('[OK] Created Admin user: crp_admin / test123'))
        else:
            self.stdout.write(self.style.WARNING('[SKIP] Admin user already exists: crp_admin'))

        self.stdout.write(self.style.SUCCESS('\n=== Test Accounts Created ==='))
        self.stdout.write('Student:     crp_student / test123')
        self.stdout.write('Trainer:     crp_trainer / test123')
        self.stdout.write('Admissions:  crp_admissions / test123')
        self.stdout.write('Admin:       crp_admin / test123')
