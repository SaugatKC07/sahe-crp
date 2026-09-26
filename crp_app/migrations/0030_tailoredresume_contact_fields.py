from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('crp_app', '0029_tailoredresume'),
    ]

    operations = [
        migrations.AddField(
            model_name='tailoredresume',
            name='contact_email',
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name='tailoredresume',
            name='contact_phone',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='tailoredresume',
            name='contact_location',
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
