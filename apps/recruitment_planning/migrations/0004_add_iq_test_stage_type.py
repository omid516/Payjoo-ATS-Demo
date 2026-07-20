from django.db import migrations, models


STAGE_TYPE_CHOICES = [
    ('SCREENING', 'غربالگری'),
    ('EXAM', 'آزمون کتبی'),
    ('SKILL_TEST', 'آزمون مهارتی'),
    ('IQ_TEST', 'تست هوش'),
    ('INTERVIEW', 'مصاحبه'),
    ('ASSESSMENT', 'کانون ارزیابی'),
    ('OTHER', 'سایر'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('recruitment_planning', '0003_jobstageplan_is_exact'),
    ]

    operations = [
        migrations.AlterField(
            model_name='jobstageplan',
            name='stage_type',
            field=models.CharField(
                choices=STAGE_TYPE_CHOICES,
                default='OTHER',
                max_length=20,
                verbose_name='نوع مرحله',
            ),
        ),
        migrations.AlterField(
            model_name='stagetypeconfiguration',
            name='stage_type',
            field=models.CharField(
                choices=STAGE_TYPE_CHOICES,
                max_length=20,
                unique=True,
                verbose_name='نوع مرحله',
            ),
        ),
    ]
