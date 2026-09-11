from django.db import migrations, connection


def cleanup_historical_audit_logs(apps, schema_editor):
    """
    پاکسازی لاگ‌های حجیم و تکراری مربوط به ایمپورت‌های اولیه و کاتالوگ‌های ثابت.
    این عملیات صرفاً لاگ‌های تغییرات را حذف می‌کند و هیچ اثری بر داده‌های اصلی ندارد.
    """
    with connection.cursor() as cursor:
        # حذف لاگ‌های مربوط به مدل‌های حجیم کاتالوگی و لاگ‌های تکراری اعلان‌ها
        cursor.execute("""
            DELETE FROM core_auditlog 
            WHERE model_name IN ('centralcompetency', 'notificationlog', 'jobdescriptiontemplate')
        """)
        deleted_count = cursor.rowcount
        print(f"\n[Data Migration] تعداد {deleted_count:,} رکورد لاگ تاریخی زائد با موفقیت پاکسازی شد.")

        # در دیتابیس SQLite برای آزادسازی فضای دیسک دستور VACUUM اجرا می‌شود
        if connection.vendor == 'sqlite':
            print("[Data Migration] در حال اجرای VACUUM برای آزادسازی فضای فیزیکی دیسک...")
            cursor.execute("VACUUM")
            cursor.execute("ANALYZE")
            print("[Data Migration] آزادسازی فضا و بهینه‌سازی دیتابیس با موفقیت پایان یافت.")


def reverse_cleanup(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    # اجرای بدون تراکنش سراسری جهت امکان اجرای VACUUM در SQLite
    atomic = False

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(cleanup_historical_audit_logs, reverse_cleanup),
    ]
