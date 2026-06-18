from django.db import models
from django.contrib.auth.models import User

class ImportSession(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'در انتظار تحلیل'),
        ('ANALYZED', 'تحلیل شده'),
        ('MAPPED', 'نگاشت شده'),
        ('PREVIEWED', 'پیش‌نمایش شده'),
        ('COMPLETED', 'ایمپورت موفقیت‌آمیز'),
        ('FAILED', 'خطا در فرآیند ایمپورت'),
    ]
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="کاربر ایجاد کننده")
    excel_file = models.FileField(upload_to='historical_imports/', verbose_name="فایل اکسل سوابق")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', verbose_name="وضعیت")
    mapping_config = models.JSONField(null=True, blank=True, verbose_name="پیکربندی نگاشت")
    summary_data = models.JSONField(null=True, blank=True, verbose_name="خلاصه آمار")

    class Meta:
        verbose_name = "نشست ورود سوابق"
        verbose_name_plural = "نشست‌های ورود سوابق"
        ordering = ['-created_at']

    def __str__(self):
        return f"نشست #{self.id} - {self.get_status_display()} ({self.created_at.strftime('%Y-%m-%d %H:%M')})"


class StagingJobOpportunity(models.Model):
    import_session = models.ForeignKey(ImportSession, on_delete=models.CASCADE, related_name='staging_jobs', verbose_name="نشست ورود")
    row_index = models.PositiveIntegerField(verbose_name="شماره ردیف")
    job_code = models.CharField(max_length=100, null=True, blank=True, verbose_name="کد شغل")
    title = models.CharField(max_length=255, null=True, blank=True, verbose_name="عنوان شغل")
    department = models.CharField(max_length=255, null=True, blank=True, verbose_name="دپارتمان / واحد")
    headcount = models.CharField(max_length=50, null=True, blank=True, verbose_name="تعداد مورد نیاز")
    status = models.CharField(max_length=100, null=True, blank=True, verbose_name="وضعیت")
    start_date_str = models.CharField(max_length=100, null=True, blank=True, verbose_name="تاریخ شروع")
    workflow_pattern = models.CharField(max_length=255, null=True, blank=True, verbose_name="الگوی استخدام")
    unit = models.CharField(max_length=255, null=True, blank=True, verbose_name="واحد سازمانی")
    job_category = models.CharField(max_length=255, null=True, blank=True, verbose_name="رده شغلی")
    notes = models.TextField(null=True, blank=True, verbose_name="یادداشت‌های داخلی")
    description = models.TextField(null=True, blank=True, verbose_name="شرح شغل")
    
    # Step implementation dates from status sheet
    screening_date_str = models.CharField(max_length=100, null=True, blank=True, verbose_name="تاریخ غربالگری")
    exam_date_str = models.CharField(max_length=100, null=True, blank=True, verbose_name="تاریخ آزمون کتبی")
    skill_test_date_str = models.CharField(max_length=100, null=True, blank=True, verbose_name="تاریخ آزمون مهارتی")
    interview_date_str = models.CharField(max_length=100, null=True, blank=True, verbose_name="تاریخ مصاحبه")
    assessment_date_str = models.CharField(max_length=100, null=True, blank=True, verbose_name="تاریخ کانون ارزیابی")
    
    # Store all columns dynamically to allow custom logic/debugging
    raw_data = models.JSONField(default=dict, verbose_name="داده‌های خام")
    
    # Validation results
    is_valid = models.BooleanField(default=True, verbose_name="معتبر است؟")
    validation_errors = models.JSONField(default=list, verbose_name="خطاهای اعتبارسنجی")
    validation_warnings = models.JSONField(default=list, verbose_name="هشدارهای اعتبارسنجی")
    
    # Link to final JobOpportunity if created/updated
    final_job = models.ForeignKey('jobs.JobOpportunity', null=True, blank=True, on_delete=models.SET_NULL, verbose_name="فرصت شغلی نهایی")

    class Meta:
        verbose_name = "فرصت شغلی موقت"
        verbose_name_plural = "فرصت‌های شغلی موقت"
        ordering = ['row_index']


class StagingCandidate(models.Model):
    import_session = models.ForeignKey(ImportSession, on_delete=models.CASCADE, related_name='staging_candidates', verbose_name="نشست ورود")
    sheet_name = models.CharField(max_length=100, verbose_name="نام شیت")
    row_index = models.PositiveIntegerField(verbose_name="شماره ردیف")
    job_code = models.CharField(max_length=100, null=True, blank=True, verbose_name="کد فرصت شغلی")
    national_id = models.CharField(max_length=50, null=True, blank=True, verbose_name="کد ملی")
    first_name = models.CharField(max_length=100, null=True, blank=True, verbose_name="نام")
    last_name = models.CharField(max_length=100, null=True, blank=True, verbose_name="نام خانوادگی")
    phone_number = models.CharField(max_length=50, null=True, blank=True, verbose_name="تلفن تماس")
    email = models.CharField(max_length=100, null=True, blank=True, verbose_name="ایمیل")
    score = models.CharField(max_length=50, null=True, blank=True, verbose_name="امتیاز")
    evaluation_date_str = models.CharField(max_length=100, null=True, blank=True, verbose_name="تاریخ ارزیابی")
    stage_type = models.CharField(max_length=50, verbose_name="نوع مرحله")
    
    raw_data = models.JSONField(default=dict, verbose_name="داده‌های خام")
    
    # Validation results
    is_valid = models.BooleanField(default=True, verbose_name="معتبر است؟")
    validation_errors = models.JSONField(default=list, verbose_name="خطاهای اعتبارسنجی")
    validation_warnings = models.JSONField(default=list, verbose_name="هشدارهای اعتبارسنجی")
    
    # Link to final Candidate if created/updated
    final_candidate = models.ForeignKey('candidates.Candidate', null=True, blank=True, on_delete=models.SET_NULL, verbose_name="متقاضی نهایی")

    class Meta:
        verbose_name = "متقاضی موقت"
        verbose_name_plural = "متقاضیان موقت"
        ordering = ['sheet_name', 'row_index']


class ImportSessionLog(models.Model):
    LEVEL_CHOICES = [
        ('INFO', 'اطلاعات'),
        ('WARNING', 'هشدار'),
        ('ERROR', 'خطا'),
    ]
    import_session = models.ForeignKey(ImportSession, on_delete=models.CASCADE, related_name='logs', verbose_name="نشست ورود")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="زمان ثبت")
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='INFO', verbose_name="سطح لاگ")
    message = models.TextField(verbose_name="متن پیام")
    sheet_name = models.CharField(max_length=100, null=True, blank=True, verbose_name="نام شیت")
    row_index = models.PositiveIntegerField(null=True, blank=True, verbose_name="شماره ردیف")

    class Meta:
        verbose_name = "لاگ نشست ورود"
        verbose_name_plural = "لاگ‌های نشست ورود"
        ordering = ['id']
