"""Persist normalized jobs and audit each external provider sync."""

from django.db import transaction
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from .job_providers import get_provider
from .models import JobListing, JobSource, JobSyncRun


def sync_job_source(source):
    if not isinstance(source, JobSource):
        source = JobSource.objects.get(pk=source)
    if not source.is_enabled:
        raise ValueError(f'Job source "{source.name}" is disabled.')

    run = JobSyncRun.objects.create(source=source)
    try:
        normalized_jobs = get_provider(source.provider).fetch_jobs(source)
        created = 0
        updated = 0
        with transaction.atomic():
            seen_ids = set()
            for job_data in normalized_jobs:
                seen_ids.add(job_data['source_external_id'])
                _, was_created = JobListing.objects.update_or_create(
                    source=source,
                    source_external_id=job_data['source_external_id'],
                    defaults=job_data,
                )
                created += int(was_created)
                updated += int(not was_created)
            now = timezone.now()
            stale_after = max(int(getattr(settings, 'JOB_STALE_AFTER_DAYS', 7)), 1)
            stale_cutoff = now - timedelta(days=stale_after)
            stale = JobListing.objects.filter(
                source=source, is_active=True,
            ).exclude(source_external_id__in=seen_ids).filter(
                last_seen_at__lt=stale_cutoff,
            ).update(is_active=False)
            expired = JobListing.objects.filter(
                source=source, is_active=True, expires_at__lte=now,
            ).update(is_active=False)
            source.last_synced_at = now
            source.save(update_fields=['last_synced_at', 'updated_at'])
            run.status = 'succeeded'
            run.jobs_seen = len(normalized_jobs)
            run.jobs_created = created
            run.jobs_updated = updated
            run.jobs_stale = stale
            run.jobs_expired = expired
            run.finished_at = timezone.now()
            run.save(update_fields=[
                'status', 'jobs_seen', 'jobs_created', 'jobs_updated',
                'jobs_stale', 'jobs_expired', 'finished_at',
            ])
    except Exception as exc:
        run.status = 'failed'
        run.error_message = str(exc)[:4000]
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'error_message', 'finished_at'])
        raise
    return run
