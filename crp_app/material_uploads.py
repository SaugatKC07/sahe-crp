"""Validation shared by all CRP learning-material upload entry points."""

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError


PDF_EXTENSIONS = {'.pdf'}
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov'}
PDF_CONTENT_TYPES = {'application/pdf'}
VIDEO_CONTENT_TYPES = {'video/mp4', 'video/webm', 'video/quicktime'}


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
