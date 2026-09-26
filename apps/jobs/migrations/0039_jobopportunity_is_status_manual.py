from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0038_alter_organizationsetting_exam_default_time_per_question_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobopportunity',
            name='is_status_manual',
            field=models.BooleanField(default=False, verbose_name='وضعیت دستی تنظیم شده توسط کاربر'),
        ),
    ]
