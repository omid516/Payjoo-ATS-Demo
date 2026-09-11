import os
from django.core.management.base import BaseCommand
from django.db import connection
from django.conf import settings


class Command(BaseCommand):
    help = "بهینه‌سازی دیتابیس، پاکسازی لاگ‌های حجیم و زائد، و آزادسازی فضای فیزیکی دیسک (VACUUM)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=None,
            help='تعداد روزهای نگهداری لاگ‌های عادی (اختیاری)',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=== شروع بهینه‌سازی دیتابیس سامانه ==="))

        db_settings = settings.DATABASES.get('default', {})
        db_engine = db_settings.get('ENGINE', '')
        db_path = db_settings.get('NAME', '')

        size_before_mb = 0
        if os.path.exists(db_path):
            size_before_mb = os.path.getsize(db_path) / (1024 * 1024)
            self.stdout.write(f"حجم دیتابیس قبل از بهینه‌سازی: {size_before_mb:.2f} MB")

        # 1. پاکسازی لاگ‌های کاتالوگی زائد
        with connection.cursor() as cursor:
            cursor.execute("""
                DELETE FROM core_auditlog 
                WHERE model_name IN ('centralcompetency', 'notificationlog', 'jobdescriptiontemplate')
            """)
            deleted_catalog_logs = cursor.rowcount
            self.stdout.write(self.style.SUCCESS(f"✓ لاگ‌های زائد مدل‌های کاتالوگی پاکسازی شد: {deleted_catalog_logs:,} رکورد"))

            # پاکسازی اختیاری بر اساس روزهای نگهداری
            days = options.get('days')
            if days:
                cursor.execute(f"""
                    DELETE FROM core_auditlog 
                    WHERE timestamp < datetime('now', '-{days} days')
                """)
                deleted_old_logs = cursor.rowcount
                self.stdout.write(self.style.SUCCESS(f"✓ لاگ‌های قدیمی‌تر از {days} روز پاکسازی شد: {deleted_old_logs:,} رکورد"))

        # 2. فشرده‌سازی و یکپارچه‌سازی فضای دیسک (VACUUM & ANALYZE)
        if 'sqlite' in db_engine or connection.vendor == 'sqlite':
            self.stdout.write("در حال اجرای عملیات فشرده‌سازی فیزیکی دیسک (VACUUM)...")
            connection.close()  # بستن کانکشن جاری برای اجرای تمیز VACUUM
            with connection.cursor() as cursor:
                cursor.execute("VACUUM;")
                cursor.execute("ANALYZE;")
            self.stdout.write(self.style.SUCCESS("✓ عملیات VACUUM و ANALYZE با موفقیت اجرا شد."))

        # 3. محاسبه حجم جدید
        if os.path.exists(db_path):
            size_after_mb = os.path.getsize(db_path) / (1024 * 1024)
            saved_mb = size_before_mb - size_after_mb
            pct_saved = (saved_mb / size_before_mb * 100) if size_before_mb > 0 else 0
            self.stdout.write(self.style.MIGRATE_HEADING("----------------------------------------------"))
            self.stdout.write(self.style.SUCCESS(f"حجم دیتابیس بعد از بهینه‌سازی: {size_after_mb:.2f} MB"))
            self.stdout.write(self.style.SUCCESS(f"فضای آزاد شده: {saved_mb:.2f} MB ({pct_saved:.1f}٪ کاهش حجم)"))
            self.stdout.write(self.style.MIGRATE_HEADING("=============================================="))
