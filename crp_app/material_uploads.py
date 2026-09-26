"""Validation shared by all CRP learning-material upload entry points."""

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError


PDF_EXTENSIONS = {'.pdf'}
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov'}
PDF_CONTENT_TYPES = {'application/pdf'}
VIDEO_CONTENT_TYPES = {'video/mp4', 'video/webm', 'video/quicktime'}
ASSESSMENT_RESOURCE_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.ppt', '.pptx',
    '.txt', '.zip', '.py', '.js', '.html', '.css', '.json',
}
ASSESSMENT_SUBMISSION_CONTENT_TYPES = {
    '.pdf': {'application/pdf'},
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

    extension = Path(upload.name).suffix.lower()
    content_type = (getattr(upload, 'content_type', '') or '').lower()
    max_mb = int(getattr(settings, 'MAX_LEARNING_MATERIAL_UPLOAD_MB', 250))
    if upload.size > max_mb * 1024 * 1024:
        raise ValidationError(f'The uploaded file must be {max_mb} MB or smaller.')

    if material_type == 'pdf':
        if extension not in PDF_EXTENSIONS or content_type not in PDF_CONTENT_TYPES:
            raise ValidationError('PDF materials must be valid .pdf files.')
    elif material_type == 'video':
        if extension not in VIDEO_EXTENSIONS or content_type not in VIDEO_CONTENT_TYPES:
            raise ValidationError('Videos must be MP4, WebM, or MOV files.')
    else:
        raise ValidationError('Direct uploads are supported for PDF Document and Video Recording materials.')


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
