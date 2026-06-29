from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0027_alter_centralcompetency_code_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='centralcompetency',
            name='is_organizational',
            field=models.BooleanField(
                default=False,
                db_index=True,
                verbose_name="شایستگی سازمانی",
                help_text="شایستگی‌هایی که در بیش از ۵۰٪ پست‌های سازمان تعریف شده‌اند و سطح سازمانی دارند"
            ),
        ),
    ]
