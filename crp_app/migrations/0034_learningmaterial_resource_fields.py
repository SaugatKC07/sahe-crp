from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('crp_app', '0033_phase2_trainer_rubric_marking'),
    ]

    operations = [
        migrations.AddField(
            model_name='learningmaterial',
            name='description',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='learningmaterial',
            name='file',
            field=models.FileField(
                blank=True,
                help_text='Uploaded learning material file',
                null=True,
                upload_to='learning_materials/%Y/%m/',
            ),
        ),
    ]
