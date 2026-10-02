"""Validation shared by all CRP learning-material upload entry points."""

from pathlib import Path
from urllib.parse import urlparse
import os

from django.conf import settings
from django.core.exceptions import ValidationError


MATERIAL_UPLOAD_RULES = {
    'pdf': ({'.pdf'}, {'application/pdf', 'application/x-pdf', 'application/octet-stream'}),
    'document': (
        {'.doc', '.docx', '.txt'},
        {
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'text/plain',
            'application/octet-stream',
        },
    ),
    'presentation': (
        {'.ppt', '.pptx'},
        {
            'application/vnd.ms-powerpoint',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'application/octet-stream',
        },
    ),
    'spreadsheet': (
        {'.xls', '.xlsx', '.csv'},
        {
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'text/csv',
            'application/csv',
            'application/octet-stream',
        },
    ),
    'image': (
        {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'},
        {'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml'},
    ),
    'video': (
        {'.mp4', '.webm', '.mov'},
        {'video/mp4', 'video/webm', 'video/quicktime', 'application/octet-stream'},
    ),
    # These legacy choices remain valid for existing materials and map to the
    # corresponding modern upload rules.
    'slides': (
        {'.ppt', '.pptx'},
        {
            'application/vnd.ms-powerpoint',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'application/octet-stream',
        },
    ),
    'workbook': (
        {'.xls', '.xlsx', '.csv'},
        {
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'text/csv',
            'application/csv',
            'application/octet-stream',
        },
    ),
}
ASSESSMENT_RESOURCE_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.ppt', '.pptx',
    '.txt', '.zip', '.py', '.js', '.html', '.css', '.json',
}
ASSESSMENT_SUBMISSION_CONTENT_TYPES = {
    '.pdf': {'application/pdf', 'application/x-pdf', 'application/octet-stream'},
    '.doc': {'application/msword', 'application/octet-stream'},
    '.docx': {'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/octet-stream'},
    '.xls': {'application/vnd.ms-excel', 'application/octet-stream'},
    '.xlsx': {'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'application/octet-stream'},
    '.ppt': {'application/vnd.ms-powerpoint', 'application/octet-stream'},
    '.pptx': {'application/vnd.openxmlformats-officedocument.presentationml.presentation', 'application/octet-stream'},
    '.csv': {'text/csv', 'application/csv', 'application/vnd.ms-excel'},
    '.txt': {'text/plain'},
    '.zip': {'application/zip', 'application/x-zip-compressed', 'application/octet-stream'},
}


def validate_material_upload(upload, material_type):
    if upload is None:
        return

    if os.environ.get('VERCEL') and not getattr(settings, 'USE_S3', False):
        raise ValidationError(
            'Learning material uploads require persistent object storage in production.'
        )
    if not upload.name or any(character in upload.name for character in ('/', '\\', '\x00')):
        raise ValidationError('The uploaded filename is not valid.')
    if upload.size <= 0:
        raise ValidationError('Empty files cannot be uploaded.')

    extension = Path(upload.name).suffix.lower()
    content_type = (getattr(upload, 'content_type', '') or '').lower()
    max_mb = int(getattr(settings, 'MAX_LEARNING_MATERIAL_UPLOAD_MB', 250))
    if upload.size > max_mb * 1024 * 1024:
        raise ValidationError(f'The uploaded file must be {max_mb} MB or smaller.')

    rules = MATERIAL_UPLOAD_RULES.get(material_type)
    if not rules:
        raise ValidationError('This resource type does not support direct file uploads.')
    allowed_extensions, allowed_content_types = rules
    if extension not in allowed_extensions or (
        content_type and content_type not in allowed_content_types
    ):
        raise ValidationError('The uploaded file type does not match the selected resource type.')


def validate_material_url(value):
    """Only allow explicitly external HTTP(S) material links."""
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValidationError('Material links must use a valid HTTP or HTTPS URL.')


def validate_assessment_resource_upload(upload):
    """Validate trainer-provided assignment resources before storage."""
    if upload is None:
        return
    extension = Path(upload.name).suffix.lower()
    max_mb = int(getattr(settings, 'MAX_ASSESSMENT_RESOURCE_UPLOAD_MB', 50))
    if upload.size <= 0:
        raise ValidationError('Assignment resources cannot be empty.')
    if upload.size > max_mb * 1024 * 1024:
        raise ValidationError(f'Assignment resources must be {max_mb} MB or smaller.')
    if extension not in ASSESSMENT_RESOURCE_EXTENSIONS:
        raise ValidationError('This assignment resource file type is not allowed.')


def validate_assessment_submission_upload(upload, accepted_formats, max_size_mb):
    """Validate a student submission before it is written to configured storage."""
    if upload is None:
        raise ValidationError('Please choose a file to upload.')
    extension = Path(upload.name).suffix.lower()
    accepted = {str(value).lower().lstrip('.') for value in (accepted_formats or [])}
    if accepted and extension.lstrip('.') not in accepted:
        raise ValidationError('This file type is not accepted for the assessment.')
    if upload.size <= 0:
        raise ValidationError('Empty files cannot be uploaded.')
    if upload.size > int(max_size_mb) * 1024 * 1024:
        raise ValidationError(f'Files must be {max_size_mb} MB or smaller.')
    content_type = (getattr(upload, 'content_type', '') or '').lower()
    expected_types = ASSESSMENT_SUBMISSION_CONTENT_TYPES.get(extension)
    if content_type and expected_types and content_type not in expected_types:
        raise ValidationError('The uploaded file type does not match its extension.')
