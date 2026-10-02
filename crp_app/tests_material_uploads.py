import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Course, LearningMaterial, LearningWeek, Registration, Student


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix='crp-material-tests-')


@override_settings(
    MEDIA_ROOT=TEST_MEDIA_ROOT,
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class LearningMaterialUploadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.admin = User.objects.create_superuser('upload-admin', 'admin@example.com', 'password')
        today = timezone.localdate()
        self.course = Course.objects.create(
            code='UPLOAD101', name='Upload Course', description='Test', credits=3,
            level='certificate', status='active', start_date=today,
            end_date=today + timedelta(days=30),
        )
        self.week = LearningWeek.objects.create(
            course=self.course, week_number=1, title='Files', description='Files',
            is_published=True,
        )
        self.client.force_login(self.admin)

    def test_admin_can_upload_pdf_and_student_url_uses_storage(self):
        upload = SimpleUploadedFile('lesson.pdf', b'%PDF-1.4 test', content_type='application/pdf')
        response = self.client.post(
            reverse('crp:admin_course_detail', args=[self.course.id]),
            {
                'action': 'material_save', 'week_id': self.week.id,
                'title': 'Lesson PDF', 'material_type': 'pdf', 'is_published': 'on',
                'file': upload,
            },
        )

        self.assertEqual(response.status_code, 302)
        material = LearningMaterial.objects.get(title='Lesson PDF')
        self.assertTrue(material.file.name.endswith('.pdf'))
        self.assertEqual(material.resource_url, material.file.url)
        self.assertTrue(material.is_published)

    def test_mismatched_upload_is_rejected(self):
        upload = SimpleUploadedFile('unsafe.exe', b'not a video', content_type='application/octet-stream')
        response = self.client.post(
            reverse('crp:admin_course_detail', args=[self.course.id]),
            {
                'action': 'material_save', 'week_id': self.week.id,
                'title': 'Unsafe', 'material_type': 'video', 'file': upload,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(LearningMaterial.objects.filter(title='Unsafe').exists())

    def test_admin_can_upload_document_presentation_and_image(self):
        uploads = (
            ('Guide', 'document', 'guide.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
            ('Slides', 'presentation', 'slides.pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'),
            ('Diagram', 'image', 'diagram.png', 'image/png'),
        )
        for title, material_type, name, content_type in uploads:
            response = self.client.post(
                reverse('crp:admin_course_detail', args=[self.course.id]),
                {
                    'action': 'material_save', 'week_id': self.week.id,
                    'title': title, 'material_type': material_type,
                    'is_published': 'on',
                    'file': SimpleUploadedFile(name, b'valid content', content_type=content_type),
                },
            )
            self.assertEqual(response.status_code, 302)
        self.assertEqual(
            set(LearningMaterial.objects.values_list('material_type', flat=True)),
            {'document', 'presentation', 'image'},
        )

    def test_empty_and_oversized_uploads_are_rejected(self):
        empty_response = self.client.post(
            reverse('crp:admin_course_detail', args=[self.course.id]),
            {
                'action': 'material_save', 'week_id': self.week.id,
                'title': 'Empty', 'material_type': 'document',
                'file': SimpleUploadedFile('empty.txt', b'', content_type='text/plain'),
            },
        )
        self.assertEqual(empty_response.status_code, 302)
        self.assertFalse(LearningMaterial.objects.filter(title='Empty').exists())

        with self.settings(MAX_LEARNING_MATERIAL_UPLOAD_MB=1):
            oversized_response = self.client.post(
                reverse('crp:admin_course_detail', args=[self.course.id]),
                {
                    'action': 'material_save', 'week_id': self.week.id,
                    'title': 'Large', 'material_type': 'document',
                    'file': SimpleUploadedFile('large.txt', b'x' * (1024 * 1024 + 1), content_type='text/plain'),
                },
            )
        self.assertEqual(oversized_response.status_code, 302)
        self.assertFalse(LearningMaterial.objects.filter(title='Large').exists())

    def test_authorized_student_can_access_only_published_course_material(self):
        user = User.objects.create_user('material-student', password='password')
        student = Student.objects.create(
            user=user, student_id='MAT-STUDENT', cohort='QA',
            program_start_date=timezone.localdate(),
            program_end_date=timezone.localdate() + timedelta(days=30),
        )
        Registration.objects.create(
            student=user, course=self.course, semester='QA', status='approved',
        )
        material = LearningMaterial.objects.create(
            week=self.week, title='Student handout', material_type='document',
            file=SimpleUploadedFile('handout.txt', b'hello', content_type='text/plain'),
            is_published=True,
        )
        self.client.force_login(user)
        response = self.client.get(reverse('crp:student_material_resource', args=[material.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'hello')

        other_course = Course.objects.create(
            code='OTHER101', name='Other', description='Other', credits=3,
            level='certificate', status='active', start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
        )
        other_week = LearningWeek.objects.create(
            course=other_course, week_number=1, title='Other', description='Other',
            is_published=True,
        )
        private_material = LearningMaterial.objects.create(
            week=other_week, title='Private', material_type='document',
            file=SimpleUploadedFile('private.txt', b'private', content_type='text/plain'),
            is_published=True,
        )
        self.assertEqual(
            self.client.get(reverse('crp:student_material_resource', args=[private_material.id])).status_code,
            404,
        )

    def test_admin_can_replace_and_remove_resource_file(self):
        material = LearningMaterial.objects.create(
            week=self.week, title='Replace me', material_type='document',
            file=SimpleUploadedFile('old.txt', b'old', content_type='text/plain'),
        )
        response = self.client.post(
            reverse('crp:admin_course_detail', args=[self.course.id]),
            {
                'action': 'material_save', 'week_id': self.week.id,
                'material_id': material.id, 'title': 'Replaced',
                'material_type': 'document',
                'file': SimpleUploadedFile('new.txt', b'new', content_type='text/plain'),
            },
        )
        self.assertEqual(response.status_code, 302)
        material.refresh_from_db()
        self.assertTrue(material.file.name.endswith('new.txt'))
        response = self.client.post(
            reverse('crp:admin_course_detail', args=[self.course.id]),
            {
                'action': 'material_save', 'week_id': self.week.id,
                'material_id': material.id, 'title': 'No file',
                'material_type': 'link', 'file_url': 'https://example.com/resource',
                'remove_file': 'on',
            },
        )
        self.assertEqual(response.status_code, 302)
        material.refresh_from_db()
        self.assertFalse(material.file)
        self.assertEqual(material.file_url, 'https://example.com/resource')
