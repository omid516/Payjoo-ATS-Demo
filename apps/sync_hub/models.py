import uuid
from django.db import models


class SyncSetting(models.Model):
    server_url = models.URLField(
        default="https://zarfy.ir/ats-sync/api.php",
        verbose_name="آدرس وب‌سرویس همگام‌سازی (zarfy.ir)"
    )
    api_key = models.CharField(
        max_length=255,
        default="ats_secret_key_zarfy_2026",
        verbose_name="کلید امنیتی اتصال (API Key)"
    )
    specialist_name = models.CharField(
        max_length=200,
        default="کارشناس تامین سرمایه انسانی",
        verbose_name="نام و عنوان کارشناس جاری"
    )
    device_id = models.CharField(
        max_length=100,
        default=uuid.uuid4,
        verbose_name="شناسه یکتای دستگاه"
    )
    last_sync_check = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="آخرین زمان بررسی سرور"
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="تاریخ ویرایش")

    class Meta:
        verbose_name = "تنظیمات همگام‌سازی"
        verbose_name_plural = "تنظیمات همگام‌سازی"

    @classmethod
    def get_settings(cls):
        setting, _ = cls.objects.get_or_create(id=1)
        return setting


class SyncPackageHistory(models.Model):
    DIRECTION_CHOICES = [
        ('OUTGOING', 'ارسال شده به سرور'),
        ('INCOMING', 'دریافت شده از سرور / فایل'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'در انتظار بررسی و تایید'),
        ('MERGED', 'ادغام و اعمال شده در دیتابیس'),
        ('REJECTED', 'رد شده'),
        ('EXPORTED', 'ارسال / ذخیره شده'),
    ]

    package_id = models.CharField(max_length=100, unique=True, db_index=True, verbose_name="شناسه بسته")
    direction = models.CharField(max_length=15, choices=DIRECTION_CHOICES, verbose_name="جهت انتقال")
    author = models.CharField(max_length=200, verbose_name="کارشناس تولیدکننده")
    title = models.CharField(max_length=300, verbose_name="عنوان بسته")
    summary = models.JSONField(default=dict, verbose_name="خلاصه تغییرات")
    payload = models.JSONField(default=dict, verbose_name="محتوای بسته")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', verbose_name="وضعیت")
    merge_report = models.JSONField(null=True, blank=True, verbose_name="گزارش ادغام")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ثبت")
    applied_at = models.DateTimeField(null=True, blank=True, verbose_name="تاریخ اعمال در دیتابیس")

    class Meta:
        verbose_name = "تاریخچه بسته همگام‌سازی"
        verbose_name_plural = "تاریخچه بسته‌های همگام‌سازی"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_direction_display()} - {self.author})"
