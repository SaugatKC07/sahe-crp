from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta, date
from django.contrib.auth.models import User
from crp_app.models import (
    Student, JobListing, JobApplication, Resume, ResumeExperience, ResumeEducation,
    InterviewSet, InterviewQuestion, InterviewAttempt,
    LinkedInProfile, Badge, StudentBadge, Streak, Leaderboard
)
import random

class Command(BaseCommand):
    help = 'Seed Career section data for Phase 2B'

    def handle(self, *args, **options):
        self.stdout.write('Seeding Career section data...')
        
        # Get student user
        try:
            student_user = User.objects.get(username='crp_student')
            student = student_user.student_profile
        except User.DoesNotExist:
            self.stdout.write('Student user not found. Please create test users first.')
            return
        
        # Clear existing career data
        JobListing.objects.all().delete()
        JobApplication.objects.all().delete()
        InterviewSet.objects.all().delete()
        Badge.objects.all().delete()
        Leaderboard.objects.all().delete()
        
        # Seed Job Listings based on CRP reference
        job_listings = [
            {
                'title': 'Junior AI/ML Engineer',
                'company': 'Atlassian',
                'location': 'Sydney CBD, Hybrid',
                'salary': '$75K–$95K',
                'salary_min': 75,
                'salary_max': 95,
                'job_type': 'full_time',
                'fields': ['ai', 'data'],
                'skills': ['Python', 'Machine Learning', 'AWS', 'MLOps', 'TensorFlow', 'PyTorch'],
                'description': 'Join Atlassian\'s AI team to build intelligent collaboration tools. Work on cutting-edge ML models that enhance productivity for millions of users worldwide.',
                'match_percentage': 94,
                'posted_date': date.today() - timedelta(days=3),
            },
            {
                'title': 'Data Scientist',
                'company': 'Canva',
                'location': 'Sydney, Hybrid',
                'salary': '$80K–$100K',
                'salary_min': 80,
                'salary_max': 100,
                'job_type': 'full_time',
                'fields': ['data', 'ai'],
                'skills': ['Python', 'Data Analysis', 'SQL', 'Statistics', 'Machine Learning', 'Visualization'],
                'description': 'Help millions of people design anything and publish anywhere. Work on data-driven product improvements and user insights.',
                'match_percentage': 88,
                'posted_date': date.today() - timedelta(days=7),
            },
            {
                'title': 'Cybersecurity Analyst',
                'company': 'Australian Signals Directorate',
                'location': 'Canberra, On-site',
                'salary': '$70K–$90K',
                'salary_min': 70,
                'salary_max': 90,
                'job_type': 'full_time',
                'fields': ['cybersecurity'],
                'skills': ['Network Security', 'Penetration Testing', 'Risk Assessment', 'Compliance', 'Incident Response'],
                'description': 'Protect Australia\'s critical infrastructure and government systems. Work on national cybersecurity initiatives.',
                'match_percentage': 76,
                'posted_date': date.today() - timedelta(days=5),
            },
            {
                'title': 'Project Manager',
                'company': 'Telstra',
                'location': 'Melbourne, Hybrid',
                'salary': '$85K–$110K',
                'salary_min': 85,
                'salary_max': 110,
                'job_type': 'full_time',
                'fields': ['pm'],
                'skills': ['Agile', 'Scrum', 'Stakeholder Management', 'Risk Management', 'Budgeting', 'JIRA'],
                'description': 'Lead transformation projects for Australia\'s leading telecommunications company. Drive digital innovation and network modernization.',
                'match_percentage': 72,
                'posted_date': date.today() - timedelta(days=10),
            },
            {
                'title': 'Machine Learning Engineer',
                'company': 'Commonwealth Bank',
                'location': 'Sydney, Hybrid',
                'salary': '$90K–$120K',
                'salary_min': 90,
                'salary_max': 120,
                'job_type': 'full_time',
                'fields': ['ai', 'data'],
                'skills': ['Python', 'Machine Learning', 'Banking Domain', 'Model Deployment', 'A/B Testing', 'Cloud'],
                'description': 'Build ML models that power personalized banking experiences, fraud detection, and risk assessment for millions of customers.',
                'match_percentage': 91,
                'posted_date': date.today() - timedelta(days=2),
            },
            {
                'title': 'Data Analyst',
                'company': 'Woolworths Group',
                'location': 'Sydney, Hybrid',
                'salary': '$65K–$85K',
                'salary_min': 65,
                'salary_max': 85,
                'job_type': 'full_time',
                'fields': ['data'],
                'skills': ['SQL', 'Excel', 'Tableau', 'Power BI', 'Data Warehousing', 'Analytics'],
                'description': 'Transform retail data into actionable insights. Support supply chain optimization and customer experience improvements.',
                'match_percentage': 82,
                'posted_date': date.today() - timedelta(days=6),
            },
        ]
        
        for job_data in job_listings:
            JobListing.objects.create(**job_data)
        
        self.stdout.write(f'Created {len(job_listings)} job listings')
        
        # Seed Resume data
        resume, created = Resume.objects.get_or_create(
            student=student,
            defaults={
                'headline': 'AI/ML Engineer | Python Expert | Data Science Enthusiast',
                'summary': 'Passionate AI/ML engineer with strong Python skills and experience in machine learning projects. Eager to apply technical skills to solve real-world problems and contribute to innovative AI solutions.',
                'skills': ['Python', 'Machine Learning', 'TensorFlow', 'PyTorch', 'AWS', 'SQL', 'Data Analysis', 'Deep Learning'],
                'contact_email': student.user.email,
                'contact_phone': '+61 412 908 771',
                'contact_location': 'Sydney, NSW',
                'completeness_score': 75,
                'ai_score': 78,
            }
        )
        
        if created:
            # Add experience
            ResumeExperience.objects.create(
                resume=resume,
                role='Machine Learning Intern',
                company='Tech Startup XYZ',
                location='Sydney',
                start_date=date.today() - timedelta(days=180),
                is_current=True,
                bullets=[
                    'Developed and deployed ML models for customer churn prediction',
                    'Improved model accuracy by 15% through feature engineering',
                    'Collaborated with data team to build data pipelines',
                    'Presented findings to stakeholders and influenced product decisions'
                ]
            )
            
            # Add education
            ResumeEducation.objects.create(
                resume=resume,
                degree='Bachelor of Information Technology',
                institution='SAHE Sydney',
                location='Sydney',
                start_date=date.today() - timedelta(days=365),
                is_current=True,
                gpa='3.8/4.0',
                details='Specialisation in Artificial Intelligence'
            )
        
        self.stdout.write('Created/updated resume data')
        
        # Seed Interview Sets
        interview_sets = [
            {
                'name': 'Technical Interview Practice',
                'description': 'Focus on technical questions related to AI, ML, and programming',
                'category': 'technical',
                'question_count': 5,
                'time_limit_minutes': 15,
            },
            {
                'name': 'Behavioral Interview Practice',
                'description': 'Practice situational and behavioral questions using STAR method',
                'category': 'behavioral',
                'question_count': 5,
                'time_limit_minutes': 20,
            },
            {
                'name': 'Mixed Interview Practice',
                'description': 'Combined technical and behavioral questions for comprehensive preparation',
                'category': 'mixed',
                'question_count': 5,
                'time_limit_minutes': 20,
            },
        ]
        
        for set_data in interview_sets:
            interview_set = InterviewSet.objects.create(**set_data)
            
            # Add questions based on category
            if interview_set.category == 'technical':
                questions = [
                    {
                        'question_text': 'Explain the difference between supervised and unsupervised learning. Give examples of when you would use each.',
                        'difficulty': 'medium',
                        'hint': 'Think about labeled vs unlabeled data and common use cases',
                        'target_word_count': 150,
                    },
                    {
                        'question_text': 'How would you handle overfitting in a machine learning model?',
                        'difficulty': 'hard',
                        'hint': 'Consider regularization, cross-validation, and data augmentation',
                        'target_word_count': 150,
                    },
                    {
                        'question_text': 'Describe your experience with deep learning frameworks like TensorFlow or PyTorch.',
                        'difficulty': 'medium',
                        'hint': 'Mention specific projects and techniques you\'ve used',
                        'target_word_count': 150,
                    },
                    {
                        'question_text': 'How do you evaluate the performance of a machine learning model?',
                        'difficulty': 'medium',
                        'hint': 'Discuss accuracy, precision, recall, F1-score, and domain-specific metrics',
                        'target_word_count': 150,
                    },
                    {
                        'question_text': 'Explain the concept of gradient descent and its role in training neural networks.',
                        'difficulty': 'hard',
                        'hint': 'Cover the optimization process and how it minimizes loss',
                        'target_word_count': 150,
                    },
                ]
            elif interview_set.category == 'behavioral':
                questions = [
                    {
                        'question_text': 'Tell me about a time you had to work with a difficult team member. How did you handle it?',
                        'difficulty': 'medium',
                        'hint': 'Use STAR method: Situation, Task, Action, Result',
                        'target_word_count': 150,
                    },
                    {
                        'question_text': 'Describe a project where you had to learn a new technology quickly.',
                        'difficulty': 'easy',
                        'hint': 'Focus on your learning process and problem-solving approach',
                        'target_word_count': 150,
                    },
                    {
                        'question_text': 'How do you prioritize tasks when working on multiple projects with tight deadlines?',
                        'difficulty': 'medium',
                        'hint': 'Discuss your time management and prioritization strategies',
                        'target_word_count': 150,
                    },
                    {
                        'question_text': 'Tell me about a time you made a mistake and how you handled it.',
                        'difficulty': 'medium',
                        'hint': 'Focus on accountability, learning, and improvement',
                        'target_word_count': 150,
                    },
                    {
                        'question_text': 'Why do you want to work in AI/ML?',
                        'difficulty': 'easy',
                        'hint': 'Connect your passion to the field and future goals',
                        'target_word_count': 150,
                    },
                ]
            else:  # mixed
                questions = [
                    {
                        'question_text': 'What machine learning project are you most proud of and why?',
                        'difficulty': 'medium',
                        'hint': 'Describe the technical challenges and your contributions',
                        'target_word_count': 150,
                    },
                    {
                        'question_text': 'How do you stay updated with the latest developments in AI and machine learning?',
                        'difficulty': 'easy',
                        'hint': 'Mention resources, communities, and learning habits',
                        'target_word_count': 150,
                    },
                    {
                        'question_text': 'Describe a situation where you had to explain a complex technical concept to a non-technical audience.',
                        'difficulty': 'medium',
                        'hint': 'Focus on communication skills and simplification',
                        'target_word_count': 150,
                    },
                    {
                        'question_text': 'What are your strengths and weaknesses as a data scientist?',
                        'difficulty': 'medium',
                        'hint': 'Be honest and focus on areas you\'re working to improve',
                        'target_word_count': 150,
                    },
                    {
                        'question_text': 'Where do you see yourself in 5 years in your AI/ML career?',
                        'difficulty': 'easy',
                        'hint': 'Connect your goals to the company and industry trends',
                        'target_word_count': 150,
                    },
                ]
            
            for i, q_data in enumerate(questions):
                InterviewQuestion.objects.create(
                    interview_set=interview_set,
                    order=i,
                    **q_data
                )
        
        self.stdout.write(f'Created {len(interview_sets)} interview sets with questions')
        
        # Seed LinkedIn Profile
        linkedin, created = LinkedInProfile.objects.get_or_create(
            student=student,
            defaults={
                'completeness_items': {
                    'photo': True,
                    'headline': True,
                    'about': True,
                    'education': True,
                    'skills': True,
                    'projects': False,
                    'recommendations': False,
                    'featured': False,
                },
                'completeness_score': 60,
                'headline': 'BIT Student (AI Specialisation) @ SAHE · Python · Machine Learning · AWS SageMaker',
                'about': 'AI and machine-learning student at SAHE Sydney, building document-intelligence systems in Python and deploying them on AWS. Currently completing the SAHE Career Ready Program and looking for a junior AI/ML engineering role from November 2026.',
                'forecast_level': 'moderate',
            }
        )
        
        self.stdout.write('Created/updated LinkedIn profile')
        
        # Seed Badges
        badges = [
            {
                'name': 'Quiz Champion',
                'description': 'Achieved 90%+ on weekly quizzes',
                'week_earned': 1,
                'points': 15,
                'color': '#0f7a5a',
            },
            {
                'name': 'Early Bird',
                'description': 'Completed first week materials on time',
                'week_earned': 1,
                'points': 10,
                'color': '#1e88e5',
            },
            {
                'name': 'Team Player',
                'description': 'Excellent collaboration in group projects',
                'week_earned': 2,
                'points': 15,
                'color': '#43a047',
            },
            {
                'name': 'Problem Solver',
                'description': 'Solved complex assessment challenges',
                'week_earned': 3,
                'points': 20,
                'color': '#fb8c00',
            },
            {
                'name': 'Quick Learner',
                'description': 'Mastered new skills ahead of schedule',
                'week_earned': 4,
                'points': 15,
                'color': '#e53935',
            },
            {
                'name': 'Perfect Attendance',
                'description': '100% attendance in live sessions',
                'week_earned': 5,
                'points': 20,
                'color': '#8e24aa',
            },
            {
                'name': 'Mentor Helper',
                'description': 'Assisted fellow students with learning',
                'week_earned': 6,
                'points': 15,
                'color': '#00acc1',
            },
            {
                'name': 'Innovation Award',
                'description': 'Creative solutions in project work',
                'week_earned': 7,
                'points': 25,
                'color': '#ff6f00',
            },
            {
                'name': 'Career Ready',
                'description': 'Completed all career development activities',
                'week_earned': 8,
                'points': 30,
                'color': '#2e7d32',
            },
        ]
        
        for badge_data in badges:
            Badge.objects.create(**badge_data)
        
        # Award some badges to the student
        earned_badges = [1, 2, 3, 5]  # Badge IDs to award
        for badge_id in earned_badges:
            try:
                badge = Badge.objects.get(id=badge_id)
                StudentBadge.objects.get_or_create(
                    student=student,
                    badge=badge
                )
            except Badge.DoesNotExist:
                pass
        
        self.stdout.write(f'Created {len(badges)} badges and awarded {len(earned_badges)} to student')
        
        # Seed Streak
        streak, created = Streak.objects.get_or_create(
            student=student,
            defaults={
                'current_streak': 12,
                'longest_streak': 15,
                'last_activity_date': date.today(),
                'streak_history': [True] * 12 + [False] * 9  # 12 active, 9 inactive
            }
        )
        
        self.stdout.write('Created/updated streak data')
        
        # Seed Leaderboard
        # Create mock cohort members
        cohort = student.cohort
        students = Student.objects.filter(cohort=cohort)
        
        leaderboard_data = []
        for i, st in enumerate(students, 1):
            # Generate some mock scores
            quiz_avg = random.randint(65, 95)
            badges_count = random.randint(2, 8)
            streak_days = random.randint(5, 20)
            total_points = quiz_avg + (badges_count * 10) + streak_days
            
            Leaderboard.objects.create(
                student=st,
                cohort=cohort,
                total_points=total_points,
                quiz_average=quiz_avg,
                badges_count=badges_count,
                streak_days=streak_days,
                rank=i
            )
        
        self.stdout.write(f'Created leaderboard with {students.count()} students')
        
        self.stdout.write(self.style.SUCCESS('Career section data seeded successfully!'))