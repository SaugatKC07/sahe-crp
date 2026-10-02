from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('crp_app', '0034_learningmaterial_resource_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='learningmaterial',
            name='material_type',
            field=models.CharField(
                choices=[
                    ('document', 'Document'),
                    ('presentation', 'Presentation'),
                    ('spreadsheet', 'Spreadsheet'),
                    ('image', 'Image'),
                    ('slides', 'Slide Deck'),
                    ('pdf', 'PDF Document'),
                    ('video', 'Video Recording'),
                    ('workbook', 'Workbook'),
                    ('link', 'External Link'),
                    ('other', 'Other'),
                ],
                max_length=20,
            ),
        ),
    ]
