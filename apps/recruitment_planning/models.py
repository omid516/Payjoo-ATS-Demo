from django.db import models
from django.contrib.auth.models import User
from apps.core.models import SoftDeleteModel
from apps.jobs.models import JobOpportunity, JobOpportunityStage, STAGE_TYPE_CHOICES

class StageTypeConfiguration(SoftDeleteModel):
    stage_type = models.CharField(
        max_length=20, 
        choices=STAGE_TYPE_CHOICES, 
        unique=True, 
        verbose_name="نوع مرحله"
    )
    default_sla_days = models.PositiveIntegerField(
        default=5, 
        verbose_name="SLA پیش‌فرض (روز کاری)"
    )
    monthly_capacity = models.PositiveIntegerField(
        default=100, 
        verbose_name="ظرفیت ماهانه (تعداد نفرات)"
    )

    class Meta:
        verbose_name = "تنظیمات نوع مرحله"
        verbose_name_plural = "تنظیمات انواع مراحل"

    def __str__(self):
        return f"{self.get_stage_type_display()} (SLA: {self.default_sla_days} روز، ظرفیت: {self.monthly_capacity} نفر)"


class Holiday(SoftDeleteModel):
    date = models.DateField(unique=True, verbose_name="تاریخ روز تعطیل")
    title = models.CharField(max_length=200, verbose_name="عنوان مناسبت تعطیلی")

    class Meta:
        verbose_name = "روز تعطیل رسمی"
        verbose_name_plural = "روزهای تعطیل رسمی"
        ordering = ['date']

    def __str__(self):
        return f"{self.title} - {self.date}"


class JobRecruitmentPlan(SoftDeleteModel):
    STATUS_DRAFT = 'DRAFT'
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_COMPLETED = 'COMPLETED'

    STATUS_CHOICES = [
        (STATUS_DRAFT, 'پیش‌نویس'),
        (STATUS_ACTIVE, 'فعال'),
        (STATUS_COMPLETED, 'خاتمه یافته'),
    ]

    job = models.OneToOneField(
        JobOpportunity, 
        on_delete=models.CASCADE, 
        related_name='recruitment_plan', 
        verbose_name="فرصت شغلی"
    )
    start_date = models.DateField(verbose_name="تاریخ شروع برنامه‌ریزی")
    predicted_end_date = models.DateField(verbose_name="تاریخ پیش‌بینی شده اتمام")
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default=STATUS_DRAFT, 
        verbose_name="وضعیت برنامه"
    )

    class Meta:
        verbose_name = "برنامه جذب شغل"
        verbose_name_plural = "برنامه‌های جذب مشاغل"

    def __str__(self):
        return f"برنامه جذب برای {self.job.title} (شروع: {self.start_date})"

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self.stage_plans.all().delete()



class JobStagePlan(SoftDeleteModel):
    plan = models.ForeignKey(
        JobRecruitmentPlan, 
        on_delete=models.CASCADE, 
        related_name='stage_plans', 
        verbose_name="برنامه جذب"
    )
    stage = models.ForeignKey(
        JobOpportunityStage, 
        on_delete=models.CASCADE, 
        related_name='planning_states', 
        verbose_name="مرحله ارزیابی"
    )
    stage_type = models.CharField(
        max_length=20, 
        choices=STAGE_TYPE_CHOICES, 
        default='OTHER', 
        verbose_name="نوع مرحله"
    )
    planned_start_date = models.DateField(verbose_name="تاریخ شروع برنامه‌ریزی شده")
    planned_end_date = models.DateField(verbose_name="تاریخ پایان برنامه‌ریزی شده")
    sla_days = models.PositiveIntegerField(verbose_name="تعداد روز کار SLA")
    capacity_shifted = models.BooleanField(
        default=False, 
        verbose_name="جابجا شده به دلیل ظرفیت"
    )
    is_exact = models.BooleanField(
        default=False,
        verbose_name="روز دقیق ارزیابی"
    )

    class Meta:
        verbose_name = "برنامه مرحله جذب"
        verbose_name_plural = "برنامه‌های مراحل جذب"
        ordering = ['stage__sequence']

    def __str__(self):
        return f"{self.stage.name} - {self.plan.job.title} ({self.planned_start_date} تا {self.planned_end_date})"
