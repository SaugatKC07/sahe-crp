from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('crp_app', '0020_learningweek_delivery_fields')]

    operations = [
        migrations.AlterField(
            model_name='studentnote',
            name='is_published',
            field=models.BooleanField(default=True),
        ),
    ]
