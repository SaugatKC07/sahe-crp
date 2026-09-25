from django.urls import path

from .views import cron_sync_jobs

app_name = 'job_cron'

urlpatterns = [
    path('', cron_sync_jobs, name='sync_jobs'),
]
