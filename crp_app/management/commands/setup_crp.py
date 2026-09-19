from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import time, date, timedelta
from django.contrib.auth.models import User
from crp_app.models import Department, Instructor, Room, TimeSlot, Course, Schedule, Announcement


class Command(BaseCommand):
    help = 'Set up initial data for the Course Registration Portal'

    def handle(self, *args, **options):
        self.stdout.write('Setting up CRP initial data...')

        # Create Departments
        departments_data = [
            {'code': 'CS', 'name': 'Computer Science', 'description': 'Department of Computer Science and Technology'},
            {'code': 'BUS', 'name': 'Business', 'description': 'School of Business and Management'},
            {'code': 'ENG', 'name': 'Engineering', 'description': 'Faculty of Engineering'},
            {'code': 'ART', 'name': 'Arts', 'description': 'Faculty of Arts and Humanities'},
            {'code': 'SCI', 'name': 'Science', 'description': 'Faculty of Science'},
        ]

        departments = {}
        for dept_data in departments_data:
            dept, created = Department.objects.get_or_create(
                code=dept_data['code'],
                defaults=dept_data
            )
            departments[dept.code] = dept
            if created:
                self.stdout.write(f'Created department: {dept.name}')
            else:
                self.stdout.write(f'Department already exists: {dept.name}')

        # Create Time Slots
        time_slots_data = [
            {'name': 'Morning 1', 'start_time': time(8, 0), 'end_time': time(9, 30)},
            {'name': 'Morning 2', 'start_time': time(10, 0), 'end_time': time(11, 30)},
            {'name': 'Afternoon 1', 'start_time': time(12, 0), 'end_time': time(13, 30)},
            {'name': 'Afternoon 2', 'start_time': time(14, 0), 'end_time': time(15, 30)},
            {'name': 'Evening', 'start_time': time(16, 0), 'end_time': time(17, 30)},
        ]

        time_slots = {}
        for slot_data in time_slots_data:
            slot, created = TimeSlot.objects.get_or_create(
                name=slot_data['name'],
                defaults=slot_data
            )
            time_slots[slot.name] = slot
            if created:
                self.stdout.write(f'Created time slot: {slot.name}')
            else:
                self.stdout.write(f'Time slot already exists: {slot.name}')

        # Create Rooms
        rooms_data = [
            {'name': '101', 'building': 'Main Building', 'floor': 1, 'capacity': 50, 'room_type': 'lecture', 'equipment': 'Projector, Whiteboard'},
            {'name': '102', 'building': 'Main Building', 'floor': 1, 'capacity': 40, 'room_type': 'lecture', 'equipment': 'Projector, Whiteboard'},
            {'name': '201', 'building': 'Science Block', 'floor': 2, 'capacity': 30, 'room_type': 'lab', 'equipment': 'Computers, Projector'},
            {'name': '202', 'building': 'Science Block', 'floor': 2, 'capacity': 30, 'room_type': 'lab', 'equipment': 'Computers, Projector'},
            {'name': '301', 'building': 'Arts Center', 'floor': 3, 'capacity': 25, 'room_type': 'seminar', 'equipment': 'Whiteboard, TV'},
            {'name': 'Online', 'building': 'Virtual', 'floor': 0, 'capacity': 100, 'room_type': 'online', 'equipment': 'Zoom, Teams'},
        ]

        rooms = {}
        for room_data in rooms_data:
            room, created = Room.objects.get_or_create(
                name=room_data['name'],
                building=room_data['building'],
                defaults=room_data
            )
            rooms[f"{room.building}-{room.name}"] = room
            if created:
                self.stdout.write(f'Created room: {room.building} - {room.name}')
            else:
                self.stdout.write(f'Room already exists: {room.building} - {room.name}')

        # Create sample instructors if users exist
        users = User.objects.filter(is_staff=True)[:5]  # Get some staff users
        instructors = []
        for i, user in enumerate(users, 1):
            instructor, created = Instructor.objects.get_or_create(
                user=user,
                defaults={
                    'employee_id': f'EMP{i:03d}',
                    'department': departments['CS'],
                    'status': 'active',
                    'specialization': 'Computer Science',
                    'qualification': 'PhD'
                }
            )
            instructors.append(instructor)
            if created:
                self.stdout.write(f'Created instructor: {user.get_full_name()}')
            else:
                self.stdout.write(f'Instructor already exists: {user.get_full_name()}')

        # Create sample courses
        start_date = date.today() + timedelta(days=30)
        end_date = start_date + timedelta(days=90)

        courses_data = [
            {
                'code': 'CS101',
                'name': 'Introduction to Programming',
                'description': 'Fundamental concepts of programming using Python. Covers variables, control structures, functions, and basic data structures.',
                'credits': 3,
                'level': 'certificate',
                'department': departments['CS'],
                'max_capacity': 30,
                'instructor': instructors[0] if instructors else None,
                'start_date': start_date,
                'end_date': end_date,
                'status': 'active'
            },
            {
                'code': 'CS201',
                'name': 'Data Structures and Algorithms',
                'description': 'Advanced programming concepts including arrays, linked lists, trees, graphs, and algorithm analysis.',
                'credits': 4,
                'level': 'diploma',
                'department': departments['CS'],
                'max_capacity': 25,
                'instructor': instructors[1] if len(instructors) > 1 else None,
                'start_date': start_date,
                'end_date': end_date,
                'status': 'active'
            },
            {
                'code': 'BUS101',
                'name': 'Introduction to Business',
                'description': 'Overview of business concepts including management, marketing, finance, and entrepreneurship.',
                'credits': 3,
                'level': 'certificate',
                'department': departments['BUS'],
                'max_capacity': 40,
                'instructor': instructors[2] if len(instructors) > 2 else None,
                'start_date': start_date,
                'end_date': end_date,
                'status': 'active'
            },
            {
                'code': 'ENG101',
                'name': 'Engineering Fundamentals',
                'description': 'Introduction to engineering principles, mathematics, and physical sciences.',
                'credits': 4,
                'level': 'diploma',
                'department': departments['ENG'],
                'max_capacity': 35,
                'instructor': instructors[3] if len(instructors) > 3 else None,
                'start_date': start_date,
                'end_date': end_date,
                'status': 'active'
            },
            {
                'code': 'ART101',
                'name': 'Digital Media Arts',
                'description': 'Introduction to digital art, graphic design, and multimedia production.',
                'credits': 3,
                'level': 'certificate',
                'department': departments['ART'],
                'max_capacity': 25,
                'instructor': instructors[4] if len(instructors) > 4 else None,
                'start_date': start_date,
                'end_date': end_date,
                'status': 'active'
            },
        ]

        courses = {}
        for course_data in courses_data:
            course, created = Course.objects.get_or_create(
                code=course_data['code'],
                defaults=course_data
            )
            courses[course.code] = course
            if created:
                self.stdout.write(f'Created course: {course.code} - {course.name}')
            else:
                self.stdout.write(f'Course already exists: {course.code} - {course.name}')

        # Create schedules for courses
        schedules_data = [
            {'course': courses['CS101'], 'day': 'monday', 'time_slot': time_slots['Morning 1'], 'room': rooms['Main Building-101'], 'instructor': instructors[0] if instructors else None, 'semester': 'Fall 2026'},
            {'course': courses['CS101'], 'day': 'wednesday', 'time_slot': time_slots['Morning 1'], 'room': rooms['Main Building-101'], 'instructor': instructors[0] if instructors else None, 'semester': 'Fall 2026'},
            {'course': courses['CS201'], 'day': 'tuesday', 'time_slot': time_slots['Afternoon 1'], 'room': rooms['Science Block-201'], 'instructor': instructors[1] if len(instructors) > 1 else None, 'semester': 'Fall 2026'},
            {'course': courses['CS201'], 'day': 'thursday', 'time_slot': time_slots['Afternoon 1'], 'room': rooms['Science Block-201'], 'instructor': instructors[1] if len(instructors) > 1 else None, 'semester': 'Fall 2026'},
            {'course': courses['BUS101'], 'day': 'monday', 'time_slot': time_slots['Morning 2'], 'room': rooms['Main Building-102'], 'instructor': instructors[2] if len(instructors) > 2 else None, 'semester': 'Fall 2026'},
            {'course': courses['BUS101'], 'day': 'friday', 'time_slot': time_slots['Morning 2'], 'room': rooms['Main Building-102'], 'instructor': instructors[2] if len(instructors) > 2 else None, 'semester': 'Fall 2026'},
        ]

        for schedule_data in schedules_data:
            schedule, created = Schedule.objects.get_or_create(
                course=schedule_data['course'],
                day=schedule_data['day'],
                time_slot=schedule_data['time_slot'],
                room=schedule_data['room'],
                semester=schedule_data['semester'],
                defaults={
                    'course': schedule_data['course'],
                    'day': schedule_data['day'],
                    'time_slot': schedule_data['time_slot'],
                    'room': schedule_data['room'],
                    'instructor': schedule_data['instructor'],
                    'semester': schedule_data['semester']
                }
            )
            if created:
                self.stdout.write(f'Created schedule: {schedule.course.code} - {schedule.get_day_display()}')
            else:
                self.stdout.write(f'Schedule already exists: {schedule.course.code} - {schedule.get_day_display()}')

        # Create sample announcements
        announcements_data = [
            {
                'title': 'Welcome to Fall 2026 Semester',
                'content': 'We are excited to welcome you to the Fall 2026 semester! Course registration is now open. Please review the course catalog and register for your desired courses before the deadline.',
                'priority': 'high',
                'published': True,
                'author': users[0] if users else None
            },
            {
                'title': 'New Course Added: Introduction to AI',
                'content': 'We are pleased to announce a new course: Introduction to Artificial Intelligence. This course will cover machine learning, neural networks, and practical AI applications.',
                'priority': 'normal',
                'published': True,
                'author': users[0] if users else None,
                'course': courses['CS101']
            },
            {
                'title': 'System Maintenance Notice',
                'content': 'The CRP system will undergo scheduled maintenance on Saturday from 2:00 AM to 4:00 AM. During this time, the system will be unavailable.',
                'priority': 'low',
                'published': True,
                'author': users[0] if users else None
            },
        ]

        for announcement_data in announcements_data:
            announcement, created = Announcement.objects.get_or_create(
                title=announcement_data['title'],
                defaults=announcement_data
            )
            if created:
                self.stdout.write(f'Created announcement: {announcement.title}')
            else:
                self.stdout.write(f'Announcement already exists: {announcement.title}')

        self.stdout.write(self.style.SUCCESS('CRP initial data setup completed successfully!'))
        self.stdout.write('You can now access the CRP portal at /crp/')
