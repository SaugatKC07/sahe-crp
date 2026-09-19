import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Course, LearningMaterial, LearningWeek


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix='crp-material-tests-')


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
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
