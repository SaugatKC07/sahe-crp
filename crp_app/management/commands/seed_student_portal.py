"""
Seed data for Student Portal - Phase 2A
Creates realistic data for testing Student Dashboard, Learning, Quiz, Assessments, and Submission screens
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import datetime, timedelta
import random

from crp_app.models import (
    Student, LearningWeek, LearningMaterial, MaterialProgress,
    Quiz, QuizQuestion, QuizOption, QuizAttempt,
    Assessment, Rubric, RubricCriterion, AssessmentSubmission, SubmissionFile,
    StudentTask, Event
)


class Command(BaseCommand):
    help = 'Seed data for Student Portal Phase 2A functionality'

    def handle(self, *args, **options):
        self.stdout.write("Seeding Student Portal data...")

        # Get or create test student
        try:
            user = User.objects.get(username='crp_student')
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR("Test student user not found. Run create_crp_test_users first."))
            return

        # Create student profile
        student, created = Student.objects.get_or_create(
            user=user,
            defaults={
                'student_id': 'STU2026001',
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
        if created:
            self.stdout.write(f"Created student profile for {user.username}")
        else:
            self.stdout.write(f"Student profile already exists for {user.username}")

        # Create learning weeks
        weeks_data = [
            {
                'week_number': 1,
                'title': 'Foundations of AI',
                'description': 'Introduction to artificial intelligence concepts and history',
                'topics': ['AI History', 'Machine Learning Basics', 'Neural Networks'],
                'status': 'done',
                'unlocks_after_week': None,
            },
            {
                'week_number': 2,
                'title': 'Python for Data Science',
                'description': 'Python programming fundamentals for data analysis',
                'topics': ['Python Basics', 'NumPy', 'Pandas', 'Data Visualization'],
                'status': 'done',
                'unlocks_after_week': 1,
            },
            {
                'week_number': 3,
                'title': 'Machine Learning Algorithms',
                'description': 'Core ML algorithms and their applications',
                'topics': ['Regression', 'Classification', 'Clustering', 'Decision Trees'],
                'status': 'done',
                'unlocks_after_week': 2,
            },
            {
                'week_number': 4,
                'title': 'Deep Learning',
                'description': 'Neural networks and deep learning frameworks',
                'topics': ['Neural Networks', 'CNNs', 'RNNs', 'TensorFlow/PyTorch'],
                'status': 'done',
                'unlocks_after_week': 3,
            },
            {
                'week_number': 5,
                'title': 'Interview Mastery',
                'description': 'Technical interview preparation and practice',
                'topics': ['Technical Questions', 'System Design', 'Behavioral Interviews'],
                'status': 'current',
                'unlocks_after_week': 4,
            },
            {
                'week_number': 6,
                'title': 'MLOps Fundamentals',
                'description': 'Machine learning operations and deployment',
                'topics': ['Model Deployment', 'Monitoring', 'CI/CD for ML', 'Cloud ML'],
                'status': 'locked',
                'unlocks_after_week': 5,
            },
            {
                'week_number': 7,
                'title': 'AI Ethics and Governance',
                'description': 'Ethical considerations in AI development',
                'topics': ['AI Bias', 'Fairness', 'Privacy', 'Regulations'],
                'status': 'locked',
                'unlocks_after_week': 6,
            },
            {
                'week_number': 8,
                'title': 'Capstone Project',
                'description': 'Final project integrating all learned concepts',
                'topics': ['Project Planning', 'Implementation', 'Presentation', 'Documentation'],
                'status': 'locked',
                'unlocks_after_week': 7,
            },
        ]

        for week_data in weeks_data:
            week, created = LearningWeek.objects.get_or_create(
                week_number=week_data['week_number'],
                defaults=week_data
            )
            if created:
                self.stdout.write(f"Created Week {week.week_number}: {week.title}")

        # Create learning materials for weeks
        material_types = ['slides', 'pdf', 'video', 'workbook']
        for week in LearningWeek.objects.all():
            for i, material_type in enumerate(material_types):
                if week.status != 'locked':
                    material, created = LearningMaterial.objects.get_or_create(
                        week=week,
                        title=f"{week.title} - {material_type.capitalize()}",
                        defaults={
                            'material_type': material_type,
                            'file_url': f'/materials/week{week.week_number}/{material_type}.pdf',
                            'file_size': f"{random.randint(1, 10)}.{random.randint(1, 9)} MB" if material_type != 'video' else f"{random.randint(30, 90)} min",
                            'duration': f"{random.randint(30, 90)} min" if material_type == 'video' else '',
                            'order': i,
                        }
                    )
                    if created:
                        # Create progress for completed weeks
                        if week.status == 'done':
                            MaterialProgress.objects.get_or_create(
                                student=student,
                                material=material,
                                defaults={'completed': True, 'completed_at': timezone.now()}
                            )

        # Create quizzes for weeks
        for week in LearningWeek.objects.filter(status__in=['done', 'current']):
            quiz, created = Quiz.objects.get_or_create(
                week=week,
                defaults={
                    'title': f"Week {week.week_number} Quiz",
                    'description': f"Test your knowledge of {week.title}",
                    'question_count': 10,
                    'time_limit_minutes': 30,
                    'passing_score': 60,
                    'is_adaptive': True,
                }
            )
            if created:
                self.stdout.write(f"Created quiz for Week {week.week_number}")
                # Create sample questions
                difficulties = ['easy', 'medium', 'hard']
                for i in range(3):
                    question = QuizQuestion.objects.create(
                        quiz=quiz,
                        question_text=f"Sample question {i+1} about {week.title.lower()}",
                        difficulty=difficulties[i % 3],
                        explanation=f"Explanation for question {i+1}",
                        order=i
                    )
                    # Create options
                    correct_idx = random.randint(0, 3)
                    for j in range(4):
                        QuizOption.objects.create(
                            question=question,
                            option_text=f"Option {chr(65+j)} for question {i+1}",
                            is_correct=(j == correct_idx),
                            order=j
                        )

        # Create quiz attempts for completed weeks
        for week in LearningWeek.objects.filter(status='done'):
            quiz = week.quiz
            if quiz:
                score = random.randint(70, 95)
                QuizAttempt.objects.get_or_create(
                    student=student,
                    quiz=quiz,
                    defaults={
                        'completed_at': timezone.now() - timedelta(days=random.randint(1, 10)),
                        'score': score,
                        'time_spent_minutes': random.randint(15, 25),
                        'is_passed': score >= 60,
                    }
                )

        # Create assessments
        assessments_data = [
            {
                'week': LearningWeek.objects.get(week_number=4),
                'title': 'Deep Learning Implementation',
                'assessment_type': 'project',
                'description': 'Build and train a neural network for image classification',
                'course_code': 'CRP401',
                'max_marks': 100,
                'weight_percentage': 20,
                'due_date': timezone.now() - timedelta(days=5),
                'accepted_formats': ['PDF', 'Code', 'Video'],
                'turnitin_enabled': True,
            },
            {
                'week': LearningWeek.objects.get(week_number=5),
                'title': 'Technical Interview Simulation',
                'assessment_type': 'presentation',
                'description': 'Complete a mock technical interview with system design questions',
                'course_code': 'CRP501',
                'max_marks': 100,
                'weight_percentage': 15,
                'due_date': timezone.now() + timedelta(days=7),
                'accepted_formats': ['Video', 'Slides'],
                'turnitin_enabled': False,
            },
            {
                'week': LearningWeek.objects.get(week_number=6),
                'title': 'MLOps Pipeline Project',
                'assessment_type': 'project',
                'description': 'Design and implement a complete ML pipeline with monitoring',
                'course_code': 'CRP601',
                'max_marks': 100,
                'weight_percentage': 25,
                'due_date': timezone.now() + timedelta(days=14),
                'accepted_formats': ['PDF', 'Code', 'Link'],
                'turnitin_enabled': True,
            },
        ]

        for assess_data in assessments_data:
            assessment, created = Assessment.objects.get_or_create(
                week=assess_data['week'],
                title=assess_data['title'],
                defaults=assess_data
            )
            if created:
                self.stdout.write(f"Created assessment: {assessment.title}")
                # Create rubric
                rubric = Rubric.objects.create(
                    assessment=assessment,
                    name=f"{assessment.title} Rubric",
                    description="Standard assessment rubric"
                )
                # Create rubric criteria
                criteria_data = [
                    {'name': 'Technical Accuracy', 'max_marks': 30, 'weight_percentage': 30},
                    {'name': 'Code Quality', 'max_marks': 25, 'weight_percentage': 25},
                    {'name': 'Documentation', 'max_marks': 20, 'weight_percentage': 20},
                    {'name': 'Innovation', 'max_marks': 15, 'weight_percentage': 15},
                    {'name': 'Presentation', 'max_marks': 10, 'weight_percentage': 10},
                ]
                for crit_data in criteria_data:
                    RubricCriterion.objects.create(
                        rubric=rubric,
                        **crit_data,
                        description=f"Evaluation criteria for {crit_data['name'].lower()}",
                        order=len(rubric.criteria.all())
                    )

        # Create assessment submissions
        week4_assessment = Assessment.objects.filter(week__week_number=4).first()
        if week4_assessment:
            submission, created = AssessmentSubmission.objects.get_or_create(
                student=student,
                assessment=week4_assessment,
                defaults={
                    'status': 'marked',
                    'submitted_at': timezone.now() - timedelta(days=4),
                    'marked_at': timezone.now() - timedelta(days=2),
                    'marks_awarded': 84,
                    'feedback': 'Excellent implementation of CNN architecture. Good documentation and clear code structure. Consider adding more hyperparameter tuning in future iterations.',
                    'turnitin_similarity': 6,
                    'ai_detection_score': 4,
                    'is_late': False,
                }
            )
            if created:
                self.stdout.write(f"Created submission for {week4_assessment.title}")

        # Create student tasks
        tasks_data = [
            {'title': 'Complete Week 5 quiz', 'priority': 'high', 'tag': 'Academic'},
            {'title': 'Book mock interview session', 'priority': 'high', 'tag': 'Career'},
            {'title': 'Add Week 4 project to LinkedIn', 'priority': 'medium', 'tag': 'Career'},
            {'title': 'Review MLOps materials', 'priority': 'medium', 'tag': 'Academic'},
            {'title': 'Update resume keywords', 'priority': 'low', 'tag': 'Career'},
        ]
        for task_data in tasks_data:
            due_date = timezone.now().date() + timedelta(days=random.randint(1, 7))
            StudentTask.objects.get_or_create(
                student=student,
                title=task_data['title'],
                defaults={
                    'description': f'Task for {task_data["tag"]} activities',
                    'due_date': due_date,
                    'priority': task_data['priority'],
                    'tag': task_data['tag'],
                }
            )

        # Create events
        events_data = [
            {'title': 'Week 5 Live Class', 'event_type': 'class', 'date': timezone.now().date() + timedelta(days=2), 'time': '14:00'},
            {'title': 'Mock Interview Session', 'event_type': 'interview', 'date': timezone.now().date() + timedelta(days=4), 'time': '10:00'},
            {'title': 'Career Coaching', 'event_type': 'coaching', 'date': timezone.now().date() + timedelta(days=5), 'time': '11:00'},
            {'title': 'MLOps Workshop', 'event_type': 'workshop', 'date': timezone.now().date() + timedelta(days=7), 'time': '15:00'},
        ]
        for event_data in events_data:
            Event.objects.get_or_create(
                student=student,
                title=event_data['title'],
                defaults={
                    'event_type': event_data['event_type'],
                    'description': f'Scheduled {event_data["event_type"]} session',
                    'date': event_data['date'],
                    'time': event_data['time'],
                }
            )

        self.stdout.write(self.style.SUCCESS("Student Portal data seeded successfully!"))