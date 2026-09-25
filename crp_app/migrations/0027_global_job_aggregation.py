# Generated for the global job aggregation feature.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crp_app', '0026_course_slug'),
    ]

    operations = [
        migrations.CreateModel(
            name='JobSource',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('provider', models.CharField(choices=[('adzuna', 'Adzuna')], default='adzuna', max_length=30)),
                ('country', models.CharField(default='au', max_length=2)),
                ('search_query', models.CharField(blank=True, max_length=200)),
                ('results_per_page', models.PositiveSmallIntegerField(default=50)),
                ('is_enabled', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='JobSyncRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('running', 'Running'), ('succeeded', 'Succeeded'), ('failed', 'Failed')], default='running', max_length=20)),
                ('jobs_seen', models.PositiveIntegerField(default=0)),
                ('jobs_created', models.PositiveIntegerField(default=0)),
                ('jobs_updated', models.PositiveIntegerField(default=0)),
                ('error_message', models.TextField(blank=True)),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sync_runs', to='crp_app.jobsource')),
            ],
            options={'ordering': ['-started_at']},
        ),
        migrations.AddField(
            model_name='studentpreference',
            name='job_keywords',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='studentpreference',
            name='job_locations',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='studentpreference',
            name='job_remote_only',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='joblisting',
            name='source_external_id',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='joblisting',
            name='apply_url',
            field=models.URLField(blank=True, max_length=1000),
        ),
        migrations.AddField(
            model_name='joblisting',
            name='is_remote',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='joblisting',
            name='source',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='jobs', to='crp_app.jobsource'),
        ),
        migrations.AddConstraint(
            model_name='joblisting',
            constraint=models.UniqueConstraint(condition=~models.Q(source_external_id=''), fields=('source', 'source_external_id'), name='unique_job_source_external_id'),
        ),
    ]
