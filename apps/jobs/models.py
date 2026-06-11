from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from apps.core.models import SoftDeleteModel

STAGE_TYPE_CHOICES = [
    ('SCREENING', 'غربالگری'),
    ('EXAM', 'آزمون کتبی'),
    ('SKILL_TEST', 'آزمون مهارتی'),
    ('INTERVIEW', 'مصاحبه'),
    ('ASSESSMENT', 'کانون ارزیابی'),
    ('OTHER', 'سایر'),
]

class WorkflowTemplate(SoftDeleteModel):
    name = models.CharField(max_length=100, unique=True, verbose_name="نام الگو")
    description = models.TextField(blank=True, verbose_name="توضیحات الگو")

    class Meta:
        verbose_name = "الگوی فرآیند استخدام"
        verbose_name_plural = "الگوهای فرآیند استخدام"
        ordering = ['name']

    def __str__(self):
        return self.name


class WorkflowStageTemplate(SoftDeleteModel):
    workflow = models.ForeignKey(WorkflowTemplate, on_delete=models.CASCADE, related_name='stages', verbose_name="الگوی فرآیند")
    name = models.CharField(max_length=100, verbose_name="نام مرحله پیش‌فرض")
    default_weight = models.PositiveIntegerField(default=0, verbose_name="وزن پیش‌فرض (٪)")
    sequence = models.PositiveIntegerField(default=1, verbose_name="ترتیب")
    stage_type = models.CharField(max_length=20, choices=STAGE_TYPE_CHOICES, default='OTHER', verbose_name="نوع مرحله")

    class Meta:
        verbose_name = "مرحله پیش‌فرض فرآیند"
        verbose_name_plural = "مراحل پیش‌فرض فرآیند"
        ordering = ['sequence', 'created_at']

    def __str__(self):
        return f"{self.name} در {self.workflow.name} ({self.default_weight}٪)"


class JobOpportunity(SoftDeleteModel):
    STATUS_RECEIVED = 'RECEIVED'
    STATUS_PLANNING = 'PLANNING'
    STATUS_PUBLISHED = 'PUBLISHED'
    STATUS_REGISTRATION_CLOSED = 'REGISTRATION_CLOSED'
    STATUS_SCREENING = 'SCREENING'
    STATUS_EXAM = 'EXAM'
    STATUS_SKILL_TEST = 'SKILL_TEST'
    STATUS_INTERVIEW = 'INTERVIEW'
    STATUS_ASSESSMENT = 'ASSESSMENT'
    STATUS_FINAL_SELECTION = 'FINAL_SELECTION'
    STATUS_CLOSED = 'CLOSED'
    STATUS_CANCELLED = 'CANCELLED'

    STATUS_CHOICES = [
        (STATUS_RECEIVED, 'دریافت شده'),
        (STATUS_PLANNING, 'برنامه‌ریزی'),
        (STATUS_PUBLISHED, 'منتشر شده'),
        (STATUS_REGISTRATION_CLOSED, 'خاتمه ثبت‌نام'),
        (STATUS_SCREENING, 'غربالگری اولیه'),
        (STATUS_EXAM, 'آزمون کتبی'),
        (STATUS_SKILL_TEST, 'آزمون مهارتی'),
        (STATUS_INTERVIEW, 'مصاحبه حضوری'),
        (STATUS_ASSESSMENT, 'کانون ارزیابی'),
        (STATUS_FINAL_SELECTION, 'انتخاب نهایی'),
        (STATUS_CLOSED, 'اتمام یافته'),
        (STATUS_CANCELLED, 'لغو شده'),
    ]

    RECRUITMENT_TYPE_CHOICES = [
        ('INTERNAL', 'داخلی'),
        ('EXTERNAL', 'خارجی'),
        ('TRANSFER', 'انتقالی'),
        ('CONTRACTUAL', 'قراردادی / پروژه‌ای'),
    ]

    request_number = models.CharField(max_length=50, unique=True, verbose_name="شماره درخواست")
    title = models.CharField(max_length=100, verbose_name="عنوان شغل")
    code = models.CharField(max_length=50, unique=True, verbose_name="کد شغل")
    department = models.CharField(max_length=100, verbose_name="بخش / دپارتمان")
    unit = models.CharField(max_length=100, blank=True, verbose_name="واحد سازمانی")
    CATEGORY_CHOICES = [
        ('اپراتور - تعمیرکار', 'اپراتور - تعمیرکار'),
        ('کاردان', 'کاردان'),
        ('کاردان مسئول', 'کاردان مسئول'),
        ('کارشناس', 'کارشناس'),
        ('کارشناس مسئول', 'کارشناس مسئول'),
        ('کارشناس مدیریت', 'کارشناس مدیریت'),
    ]

    job_category = models.CharField(
        max_length=100,
        choices=CATEGORY_CHOICES,
        blank=True,
        null=True,
        verbose_name="رده شغلی"
    )
    headcount = models.PositiveIntegerField(default=1, verbose_name="ظرفیت جذب (تعداد)")
    recruitment_type = models.CharField(max_length=20, choices=RECRUITMENT_TYPE_CHOICES, default='EXTERNAL', verbose_name="نوع استخدام")
    assigned_recruiter = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_jobs', verbose_name="کارشناس جذب مسئول")
    workflow = models.ForeignKey(WorkflowTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='jobs', verbose_name="الگوی فرآیند استخدامی")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_RECEIVED, verbose_name="وضعیت فرصت شغلی")

    SOURCE_ATS = 'ATS'
    SOURCE_IMPORT = 'IMPORT'
    SOURCE_CHOICES = [
        (SOURCE_ATS, 'سیستم ATS'),
        (SOURCE_IMPORT, 'ایمپورت شده'),
    ]
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_ATS, verbose_name="منبع ایجاد")
    description = models.TextField(blank=True, verbose_name="شرح شغل")
    requirements = models.TextField(blank=True, verbose_name="شرایط احراز")
    start_date = models.DateField(null=True, blank=True, verbose_name="تاریخ شروع")
    end_date = models.DateField(null=True, blank=True, verbose_name="تاریخ پایان")
    notes = models.TextField(blank=True, verbose_name="یادداشت‌های داخلی")

    class Meta:
        verbose_name = "فرصت شغلی"
        verbose_name_plural = "فرصت‌های شغلی"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.code})"

    @property
    def has_all_evaluations_completed(self):
        active_apps = self.applications.filter(status='IN_PROGRESS', is_deleted=False)
        if not active_apps.exists():
            return False
        
        stages_count = self.stages.filter(is_deleted=False).count()
        if stages_count == 0:
            return False

        for app in active_apps:
            pending_states = app.stage_states.filter(status='PENDING', is_deleted=False)
            if pending_states.exists():
                return False
        return True

    @property
    def current_stage(self):
        # 1. Look at furthest stage of active applications
        active_apps = self.applications.filter(status='IN_PROGRESS', is_deleted=False)
        if active_apps.exists():
            from django.db.models import Max
            max_seq = active_apps.aggregate(max_seq=Max('current_stage__sequence'))['max_seq']
            if max_seq is not None:
                furthest_stage = self.stages.filter(sequence=max_seq, is_deleted=False).first()
                if furthest_stage:
                    return furthest_stage
                    
        # 2. Fallback to status mapping
        stage = self.stages.filter(stage_type=self.status, is_deleted=False).first()
        if stage:
            return stage
            
        # 3. Fallback to first stage
        return self.stages.filter(is_deleted=False).order_by('sequence').first()


    def get_status_from_stage_name(self, stage_name):
        name_lower = stage_name.lower()
        if any(kw in name_lower for kw in ["غربال", "screening"]):
            return self.STATUS_SCREENING
        elif any(kw in name_lower for kw in ["مهارتی", "skill_test", "عملی"]):
            return self.STATUS_SKILL_TEST
        elif any(kw in name_lower for kw in ["آزمون", "امتحان", "کتبی", "exam", "test"]):
            return self.STATUS_EXAM
        elif any(kw in name_lower for kw in ["مصاحبه", "interview"]):
            return self.STATUS_INTERVIEW
        elif any(kw in name_lower for kw in ["کانون", "ارزیابی", "assessment", "سنتر", "competency"]):
            return self.STATUS_ASSESSMENT
        elif any(kw in name_lower for kw in ["انتخاب", "نهایی", "selection"]):
            return self.STATUS_FINAL_SELECTION
        return None

    def update_status(self):
        # 1. Check if any candidate is SELECTED (قبول نهایی)
        if self.applications.filter(status='SELECTED', is_deleted=False).exists():
            if self.status != self.STATUS_CLOSED:
                self.status = self.STATUS_CLOSED
                self.save(update_fields=['status'])
            return

        # 2. Check furthest stage of in-progress candidates
        active_apps = self.applications.filter(status='IN_PROGRESS', is_deleted=False)
        if active_apps.exists():
            from django.db.models import Max
            max_seq = active_apps.aggregate(max_seq=Max('current_stage__sequence'))['max_seq']
            if max_seq is not None:
                furthest_stage = self.stages.filter(sequence=max_seq, is_deleted=False).first()
                if furthest_stage:
                    new_status = self.get_status_from_stage_name(furthest_stage.name)
                    if not new_status:
                        # Fallback mapping based on relative position
                        stages_list = list(self.stages.filter(is_deleted=False).order_by('sequence'))
                        if furthest_stage in stages_list:
                            idx = stages_list.index(furthest_stage)
                            total = len(stages_list)
                            if total == 1:
                                new_status = self.STATUS_EXAM
                            elif total == 2:
                                new_status = [self.STATUS_EXAM, self.STATUS_INTERVIEW][idx]
                            elif total == 3:
                                new_status = [self.STATUS_EXAM, self.STATUS_INTERVIEW, self.STATUS_ASSESSMENT][idx]
                            else:
                                if idx == 0:
                                    new_status = self.STATUS_SCREENING
                                elif idx == total - 1:
                                    new_status = self.STATUS_FINAL_SELECTION
                                elif idx == 1:
                                    new_status = self.STATUS_EXAM
                                elif idx == 2:
                                    new_status = self.STATUS_INTERVIEW
                                else:
                                    new_status = self.STATUS_ASSESSMENT
                    if new_status and self.status != new_status:
                        self.status = new_status
                        self.save(update_fields=['status'])
                    return

        # 3. If there are no active/selected applications, and current status is a pipeline/closed status, revert to PUBLISHED
        pipeline_statuses = [
            self.STATUS_SCREENING, self.STATUS_EXAM, self.STATUS_SKILL_TEST,
            self.STATUS_INTERVIEW, self.STATUS_ASSESSMENT,
            self.STATUS_FINAL_SELECTION, self.STATUS_CLOSED
        ]
        if self.status in pipeline_statuses:
            self.status = self.STATUS_PUBLISHED
            self.save(update_fields=['status'])

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # اگر فرصت شغلی جدید باشد و الگوی فرآیند انتخاب شده باشد، مراحل پیش‌فرض از روی الگو کپی می‌شوند
        if is_new and self.workflow:
            stage_templates = self.workflow.stages.all().order_by('sequence')
            for st in stage_templates:
                JobOpportunityStage.objects.create(
                    job=self,
                    name=st.name,
                    weight=st.default_weight,
                    sequence=st.sequence,
                    stage_type=st.stage_type
                )

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        try:
            if hasattr(self, 'recruitment_plan') and self.recruitment_plan:
                self.recruitment_plan.delete()
        except Exception:
            pass



class JobOpportunityStage(SoftDeleteModel):
    job = models.ForeignKey(JobOpportunity, on_delete=models.CASCADE, related_name='stages', verbose_name="فرصت شغلی")
    name = models.CharField(max_length=100, verbose_name="نام مرحله")
    weight = models.PositiveIntegerField(default=0, verbose_name="وزن (٪)")
    sequence = models.PositiveIntegerField(default=1, verbose_name="ترتیب")
    passing_score = models.FloatField(default=60.0, verbose_name="کف نمره قبولی")
    stage_type = models.CharField(max_length=20, choices=STAGE_TYPE_CHOICES, default='OTHER', verbose_name="نوع مرحله")

    class Meta:
        verbose_name = "مرحله ارزیابی فرصت شغلی"
        verbose_name_plural = "مراحل ارزیابی فرصت‌های شغلی"
        ordering = ['sequence', 'created_at']

    def __str__(self):
        return f"{self.name} - {self.job.title} (وزن: {self.weight}٪)"


class JobStageInterviewer(SoftDeleteModel):
    job = models.ForeignKey(JobOpportunity, on_delete=models.CASCADE, related_name='stage_interviewers', verbose_name="فرصت شغلی")
    stage = models.ForeignKey(JobOpportunityStage, on_delete=models.CASCADE, related_name='interviewers', verbose_name="مرحله ارزیابی")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='assigned_interviews', verbose_name="مصاحبه‌گر")
    weight = models.PositiveIntegerField(default=100, verbose_name="وزن نمره مصاحبه‌گر (٪)")
    group_name = models.CharField(max_length=100, blank=True, verbose_name="گروه / کمیته مصاحبه")

    class Meta:
        verbose_name = "مصاحبه‌گر مرحله ارزیابی"
        verbose_name_plural = "مصاحبه‌گران مراحل ارزیابی"
        unique_together = ('stage', 'user')

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - {self.stage.name} (وزن: {self.weight}٪)"


class AssessmentCompetency(SoftDeleteModel):
    stage = models.ForeignKey(JobOpportunityStage, on_delete=models.CASCADE, related_name='competencies', verbose_name="مرحله ارزیابی")
    name = models.CharField(max_length=100, verbose_name="نام شایستگی")
    weight = models.PositiveIntegerField(default=100, verbose_name="وزن شایستگی (٪)")

    class Meta:
        verbose_name = "شایستگی کانون ارزیابی"
        verbose_name_plural = "شایستگی‌های کانون ارزیابی"
        unique_together = ('stage', 'name')

    def __str__(self):
        return f"{self.name} - {self.stage.name} (وزن: {self.weight}٪)"
