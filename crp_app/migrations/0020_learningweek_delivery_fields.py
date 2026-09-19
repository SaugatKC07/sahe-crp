from django.db import migrations, models


def publish_existing_weeks(apps, schema_editor):
    apps.get_model('crp_app', 'LearningWeek').objects.update(is_published=True)


class Migration(migrations.Migration):
    dependencies = [('crp_app', '0019_quizquestion_is_archived')]

    operations = [
        migrations.AddField(model_name='learningweek', name='learning_objectives', field=models.TextField(blank=True)),
        migrations.AddField(model_name='learningweek', name='release_date', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='learningweek', name='completion_requirements', field=models.TextField(blank=True)),
        migrations.AddField(model_name='learningweek', name='require_materials', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='learningweek', name='require_quiz', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='learningweek', name='require_assessment', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='learningweek', name='is_published', field=models.BooleanField(default=False)),
        migrations.RunPython(publish_existing_weeks, migrations.RunPython.noop),
    ]
