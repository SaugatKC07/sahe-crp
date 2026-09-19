from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('crp_app', '0012_studentgroup_cohort_livesession_studentrequest')]

    operations = [
        migrations.AddField(
            model_name='learningmaterial', name='is_published',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='learningmaterial', name='program',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='materials', to='crp_app.program'),
        ),
        migrations.AddField(
            model_name='learningmaterial', name='cohort',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='materials', to='crp_app.cohort'),
        ),
        migrations.AddField(
            model_name='quiz', name='program',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='quizzes', to='crp_app.program'),
        ),
        migrations.AddField(
            model_name='quiz', name='cohort',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='quizzes', to='crp_app.cohort'),
        ),
        migrations.RunSQL(
            "UPDATE crp_app_learningmaterial SET is_published = TRUE",
            migrations.RunSQL.noop,
        ),
    ]
