from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from apps.core.models import SoftDeleteModel

STAGE_TYPE_CHOICES = [
    ('SCREENING', 'غربالگری'),
    ('EXAM', 'آزمون کتبی'),
    ('SKILL_TEST', 'آزمون مهارتی'),
    ('IQ_TEST', 'تست هوش'),
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
    STATUS_IQ_TEST = 'IQ_TEST'
    STATUS_INTERVIEW = 'INTERVIEW'
    STATUS_ASSESSMENT = 'ASSESSMENT'
    STATUS_FINAL_SELECTION = 'FINAL_SELECTION'
    STATUS_CLOSED = 'CLOSED'
    STATUS_CANCELLED = 'CANCELLED'
    STATUS_SUSPENDED = 'SUSPENDED'

    STATUS_CHOICES = [
        (STATUS_RECEIVED, 'دریافت شده'),
        (STATUS_PLANNING, 'برنامه‌ریزی'),
        (STATUS_PUBLISHED, 'منتشر شده'),
        (STATUS_REGISTRATION_CLOSED, 'خاتمه ثبت‌نام'),
        (STATUS_SCREENING, 'غربالگری اولیه'),
        (STATUS_EXAM, 'آزمون کتبی'),
        (STATUS_SKILL_TEST, 'آزمون مهارتی'),
        (STATUS_IQ_TEST, 'تست هوش'),
        (STATUS_INTERVIEW, 'مصاحبه حضوری'),
        (STATUS_ASSESSMENT, 'کانون ارزیابی'),
        (STATUS_FINAL_SELECTION, 'انتخاب نهایی'),
        (STATUS_CLOSED, 'اتمام یافته'),
        (STATUS_CANCELLED, 'لغو شده'),
        (STATUS_SUSPENDED, 'توقف موقت'),
    ]

    RECRUITMENT_TYPE_CHOICES = [
        ('INTERNAL', 'داخلی'),
        ('EXTERNAL', 'خارجی'),
        ('TRANSFER', 'انتقالی'),
        ('CONTRACTUAL', 'قراردادی / پروژه‌ای'),
    ]

    request_number = models.CharField(max_length=50, verbose_name="شماره درخواست")
    title = models.CharField(max_length=100, verbose_name="عنوان شغل")
    code = models.CharField(max_length=50, verbose_name="کد شغل")
    department = models.CharField(max_length=100, verbose_name="بخش / دپارتمان")
    unit = models.CharField(max_length=100, blank=True, verbose_name="واحد سازمانی")
    factory_name = models.CharField(max_length=150, blank=True, null=True, verbose_name="کارخانه / محل استقرار")
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
    bypass_limits = models.BooleanField(default=False, verbose_name="بایپس کردن رنج")

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
        constraints = [
            models.UniqueConstraint(
                fields=['request_number'],
                condition=models.Q(is_deleted=False),
                name='unique_request_number_active',
                violation_error_message="یک فرصت شغلی فعال با این شماره درخواست از قبل وجود دارد."
            ),
            models.UniqueConstraint(
                fields=['request_number', 'code'],
                condition=models.Q(is_deleted=False),
                name='unique_request_number_code_active',
                violation_error_message="یک فرصت شغلی فعال با این ترکیب شماره درخواست و کد شغل از قبل وجود دارد."
            )
        ]

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

    @property
    def has_exam_stage(self):
        return self.stages.filter(stage_type='EXAM', is_deleted=False).exists()



    def get_status_from_stage_name(self, stage_name):
        name_lower = stage_name.lower()
        if any(kw in name_lower for kw in ["غربال", "screening"]):
            return self.STATUS_SCREENING
        elif any(kw in name_lower for kw in ["مهارتی", "skill_test", "عملی"]):
            return self.STATUS_SKILL_TEST
        elif any(kw in name_lower for kw in ["هوش", "iq"]):
            return self.STATUS_IQ_TEST
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
        if self.status in [self.STATUS_CANCELLED, self.STATUS_SUSPENDED]:
            return
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
            self.STATUS_SCREENING, self.STATUS_EXAM, self.STATUS_SKILL_TEST, self.STATUS_IQ_TEST,
            self.STATUS_INTERVIEW, self.STATUS_ASSESSMENT,
            self.STATUS_FINAL_SELECTION, self.STATUS_CLOSED
        ]
        if self.status in pipeline_statuses:
            self.status = self.STATUS_PUBLISHED
            self.save(update_fields=['status'])

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        update_fields = kwargs.get('update_fields')
        workflow_changed = False
        if not is_new and (update_fields is None or 'workflow' in update_fields):
            old_instance = JobOpportunity.objects.filter(pk=self.pk).first()
            if old_instance and self.workflow != old_instance.workflow:
                workflow_changed = True

        super().save(*args, **kwargs)
        
        if workflow_changed:
            old_stages = list(self.stages.filter(is_deleted=False))
            for stg in old_stages:
                stg.delete()
            
        # اگر فرصت شغلی جدید باشد یا الگوی فرآیند تغییر کرده باشد یا هیچ مرحله فعالی نداشته باشد و الگوی فرآیند انتخاب شده باشد، مراحل پیش‌فرض از روی الگو کپی می‌شوند
        if self.workflow and (is_new or workflow_changed or not self.stages.filter(is_deleted=False).exists()):
            stage_templates = self.workflow.stages.filter(is_deleted=False).order_by('sequence')
            for st in stage_templates:
                JobOpportunityStage.objects.create(
                    job=self,
                    name=st.name,
                    weight=st.default_weight,
                    sequence=st.sequence,
                    stage_type=st.stage_type
                )
        
        if workflow_changed and not is_new:
            self.sync_application_stages()

    def delete(self, *args, **kwargs):
        from django.utils import timezone
        super().delete(*args, **kwargs)
        
        # Soft delete related selected competencies
        self.selected_competencies.filter(is_deleted=False).update(
            is_deleted=True,
            deleted_at=timezone.now()
        )
        
        # Soft delete related stages
        stages = self.stages.filter(is_deleted=False)
        for stage in stages:
            stage.delete()
            
        # Soft delete related stage interviewers
        self.stage_interviewers.filter(is_deleted=False).update(
            is_deleted=True,
            deleted_at=timezone.now()
        )
        
        try:
            if hasattr(self, 'recruitment_plan') and self.recruitment_plan:
                self.recruitment_plan.delete()
        except Exception:
            pass

    def sync_application_stages(self):
        """
        همگام‌سازی وضعیت‌های مراحل (ApplicationStageState) متقاضیان فعال فرصت شغلی
        زمانی که ساختار مراحل تغییر می‌کند (مثلا در پیکربندی شایستگی‌ها یا تغییر گردش کار).
        """
        from apps.candidates.models import JobApplication, ApplicationStageState
        from django.utils import timezone
        
        applications = list(self.applications.filter(is_deleted=False))
        if not applications:
            return

        # مراحل فعال فعلی فرصت شغلی به ترتیب
        active_stages = list(self.stages.filter(is_deleted=False).order_by('sequence'))
        
        # تمام وضعیت‌های مراحل غیرحذف‌شده برای کاندیداهای این شغل
        existing_states = list(ApplicationStageState.objects.filter(
            application__in=applications,
            is_deleted=False
        ).select_related('stage'))
        
        # ساخت نگاشت برای هر کاندیدا و نوع مرحله: (application_id, stage_type) -> state
        state_map = {}
        for state in existing_states:
            key = (state.application_id, state.stage.stage_type)
            if key in state_map:
                old_val = state_map[key]
                # حفظ وضعیت نهایی شده یا دارای امتیاز بیشتر در صورت هم‌پوشانی
                if state.status in ['COMPLETED', 'FAILED'] or state.score > old_val.score:
                    state_map[key] = state
            else:
                state_map[key] = state
                
        states_to_soft_delete = []
        new_states_to_create = []
        
        for app in applications:
            # وضعیت‌های مرحله فعلی متقاضی
            app_states = [s for s in existing_states if s.application_id == app.id]
            app_states_by_type = {s.stage.stage_type: s for s in app_states}
            
            for stage in active_stages:
                existing_state = app_states_by_type.get(stage.stage_type)
                
                if existing_state:
                    if existing_state.stage_id == stage.id:
                        # از قبل به مرحله درستی اشاره می‌کند
                        continue
                    else:
                        # به یک مرحله قدیمی/غیرفعال از همان نوع اشاره می‌کند. آن را آرشیو (حذف نرم) می‌کنیم.
                        states_to_soft_delete.append(existing_state)
                        # ایجاد وضعیت جدید اشاره‌کننده به مرحله جدید با حفظ داده‌ها
                        new_states_to_create.append(ApplicationStageState(
                            application=app,
                            stage=stage,
                            status=existing_state.status,
                            score=existing_state.score,
                            evaluator=existing_state.evaluator,
                            notes=existing_state.notes,
                            score_discrepancy_alert=existing_state.score_discrepancy_alert,
                            is_conditional_pass=existing_state.is_conditional_pass,
                            evaluation_date=existing_state.evaluation_date,
                            is_manually_edited=existing_state.is_manually_edited,
                        ))
                else:
                    # هیچ وضعیت متناظری وجود ندارد -> ایجاد وضعیت در انتظار
                    new_states_to_create.append(ApplicationStageState(
                        application=app,
                        stage=stage,
                        status=ApplicationStageState.STATUS_PENDING,
                        score=0.0
                    ))
            
            # اگر وضعیتی وجود دارد که نوع مرحله آن دیگر در مراحل فعال نیست، آن را هم حذف نرم می‌کنیم.
            active_types = {st.stage_type for st in active_stages}
            for s in app_states:
                if s.stage.stage_type not in active_types:
                    states_to_soft_delete.append(s)
                    
        # اعمال تغییرات دیتابیس
        if states_to_soft_delete:
            state_ids_to_del = [s.id for s in states_to_soft_delete]
            ApplicationStageState.objects.filter(id__in=state_ids_to_del).update(
                is_deleted=True,
                deleted_at=timezone.now()
            )
            
        if new_states_to_create:
            ApplicationStageState.objects.bulk_create(new_states_to_create)
            
        # بروزرسانی مرحله جاری متقاضیان
        for app in applications:
            if 'stage_states' in app.__dict__:
                del app.__dict__['stage_states']
            app.recalculate_current_stage(save=True)



class JobOpportunityStage(SoftDeleteModel):
    job = models.ForeignKey(JobOpportunity, on_delete=models.CASCADE, related_name='stages', verbose_name="فرصت شغلی")
    name = models.CharField(max_length=100, verbose_name="نام مرحله")
    weight = models.PositiveIntegerField(default=0, verbose_name="وزن (٪)")
    sequence = models.PositiveIntegerField(default=1, verbose_name="ترتیب")
    passing_score = models.FloatField(default=60.0, verbose_name="کف نمره قبولی")
    stage_type = models.CharField(max_length=20, choices=STAGE_TYPE_CHOICES, default='OTHER', verbose_name="نوع مرحله")
    is_manually_completed = models.BooleanField(null=True, blank=True, default=None, verbose_name="وضعیت تکمیل دستی")

    class Meta:
        verbose_name = "مرحله ارزیابی فرصت شغلی"
        verbose_name_plural = "مراحل ارزیابی فرصت‌های شغلی"
        ordering = ['sequence', 'created_at']

    def __str__(self):
        return f"{self.name} - {self.job.title} (وزن: {self.weight}٪)"

    @property
    def actual_start_date(self):
        from apps.candidates.models import ApplicationStageState
        from django.db.models import Min
        return ApplicationStageState.objects.filter(
            stage=self,
            is_deleted=False,
            evaluation_date__isnull=False
        ).aggregate(min_date=Min('evaluation_date'))['min_date']

    @property
    def actual_end_date(self):
        from apps.candidates.models import ApplicationStageState
        from django.db.models import Max
        return ApplicationStageState.objects.filter(
            stage=self,
            is_deleted=False,
            evaluation_date__isnull=False
        ).aggregate(max_date=Max('evaluation_date'))['max_date']

    @property
    def is_completed(self):
        if self.is_manually_completed is not None:
            return self.is_manually_completed

        from apps.candidates.models import ApplicationStageState
        reached_states_qs = ApplicationStageState.objects.filter(
            stage=self,
            is_deleted=False,
            application__is_deleted=False
        ).select_related('application').prefetch_related('application__stage_states__stage')

        reached_states = []
        for state in reached_states_qs:
            state.stage = self
            for s in state.application.stage_states.all():
                s.application = state.application
            if state.is_accessible:
                reached_states.append(state)

        if not reached_states:
            return False
        return not any(state.status == ApplicationStageState.STATUS_PENDING for state in reached_states)

    def delete(self, *args, **kwargs):
        from django.utils import timezone
        super().delete(*args, **kwargs)
        # Soft delete related assessment competencies
        self.competencies.filter(is_deleted=False).update(
            is_deleted=True,
            deleted_at=timezone.now()
        )
        # Soft delete related stage interviewers
        self.interviewers.filter(is_deleted=False).update(
            is_deleted=True,
            deleted_at=timezone.now()
        )



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


class CentralCompetency(SoftDeleteModel):
    post_code = models.CharField(max_length=50, db_index=True, verbose_name="کد پست")
    post_title = models.CharField(max_length=200, null=True, blank=True, verbose_name="پست")
    code = models.CharField(max_length=50, db_index=True, verbose_name="کد شایستگی")
    old_code = models.CharField(max_length=50, null=True, blank=True, verbose_name="کد شایستگی قدیم")
    title = models.CharField(max_length=300, verbose_name="شایستگی")
    competency_type = models.CharField(max_length=10, choices=[
        ('KN', 'دانش (Knowledge)'),
        ('SK', 'مهارت (Skill)'),
        ('AB', 'توانایی (Ability)'),
        ('GE', 'رفتاری (General/Behavioral)'),
        ('ST', 'ارزش‌ها و سبک‌ها (Styles & Values)'),
        ('PR', 'گردشکار و فرآیندها (Process)'),
        ('CQ', 'گواهینامه‌ها و صلاحیت‌ها (Certification & Qualification)'),
        ('IN', 'علایق حرفه‌ای (Interests)'),
    ], verbose_name="نوع شایستگی")
    category_raw = models.CharField(max_length=100, null=True, blank=True, verbose_name="طبقه")
    cluster_raw = models.CharField(max_length=100, null=True, blank=True, verbose_name="خوشه")
    importance = models.PositiveIntegerField(choices=[
        (1, 'محوری'),
        (2, 'تکلیف محور'),
        (3, 'حداقلی'),
    ], verbose_name="اهمیت شایستگی")
    level = models.PositiveIntegerField(choices=[
        (1, 'آشنایی'),
        (2, 'توانایی'),
        (3, 'تسلط'),
    ], verbose_name="سطح شایستگی")
    
    management_code = models.CharField(max_length=50, null=True, blank=True, verbose_name="کد مدیریت")
    management_name = models.CharField(max_length=200, null=True, blank=True, verbose_name="مدیریت")
    vice_president_code = models.CharField(max_length=50, null=True, blank=True, verbose_name="کد معاونت")
    vice_president_name = models.CharField(max_length=200, null=True, blank=True, verbose_name="معاونت")
    section_code = models.CharField(max_length=50, null=True, blank=True, verbose_name="کد قسمت")
    section_name = models.CharField(max_length=200, null=True, blank=True, verbose_name="قسمت")
    cost_center_code = models.CharField(max_length=50, null=True, blank=True, verbose_name="کد مرکز هزینه")
    cost_center_name = models.CharField(max_length=200, null=True, blank=True, verbose_name="مرکز هزینه")

    is_organizational = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="شایستگی سازمانی",
        help_text="شایستگی‌هایی که در بیش از ۵۰٪ پست‌های سازمان تعریف شده‌اند و سطح سازمانی دارند"
    )

    class Meta:
        verbose_name = "شایستگی مرجع"
        verbose_name_plural = "بانک شایستگی‌های مرجع"
        ordering = ['post_code', 'code']

    def __str__(self):
        return f"{self.title} ({self.code}) - پست {self.post_code}"


class JobOpportunityCompetency(SoftDeleteModel):
    job = models.ForeignKey(JobOpportunity, on_delete=models.CASCADE, related_name='selected_competencies', verbose_name="فرصت شغلی")
    central_competency = models.ForeignKey(CentralCompetency, on_delete=models.SET_NULL, null=True, blank=True, related_name='job_links', verbose_name="شایستگی مرجع")
    code = models.CharField(max_length=50, verbose_name="کد شایستگی")
    title = models.CharField(max_length=300, verbose_name="شایستگی")
    competency_type = models.CharField(max_length=10, choices=[
        ('KN', 'دانش (Knowledge)'),
        ('SK', 'مهارت (Skill)'),
        ('AB', 'توانایی (Ability)'),
        ('GE', 'رفتاری (General/Behavioral)'),
        ('ST', 'ارزش‌ها و سبک‌ها (Styles & Values)'),
        ('PR', 'گردشکار و فرآیندها (Process)'),
        ('CQ', 'گواهینامه‌ها و صلاحیت‌ها (Certification & Qualification)'),
        ('IN', 'علایق حرفه‌ای (Interests)'),
    ], verbose_name="نوع شایستگی")
    importance = models.PositiveIntegerField(choices=[
        (1, 'محوری'),
        (2, 'تکلیف محور'),
        (3, 'حداقلی'),
    ], verbose_name="اهمیت شایستگی")
    level = models.PositiveIntegerField(choices=[
        (1, 'آشنایی'),
        (2, 'توانایی'),
        (3, 'تسلط'),
    ], verbose_name="سطح شایستگی")
    is_custom = models.BooleanField(default=False, verbose_name="ایجاد دستی")
    model_name = models.CharField(max_length=100, null=True, blank=True, verbose_name="نام مدل شایستگی")

    class Meta:
        verbose_name = "شایستگی فرصت شغلی"
        verbose_name_plural = "شایستگی‌های فرصت شغلی"
        ordering = ['job', 'code']

    def __str__(self):
        return f"{self.title} ({self.code}) - {self.job.title}"


class CompetencyModel(SoftDeleteModel):
    name = models.CharField(max_length=100, verbose_name="نام مدل شایستگی")
    description = models.TextField(null=True, blank=True, verbose_name="توضیحات")
    
    class Meta:
        verbose_name = "مدل شایستگی"
        verbose_name_plural = "مدل‌های شایستگی"
        
    def __str__(self):
        return self.name


class CompetencyModelItem(SoftDeleteModel):
    competency_model = models.ForeignKey(CompetencyModel, on_delete=models.CASCADE, related_name='items', verbose_name="مدل شایستگی")
    title = models.CharField(max_length=300, verbose_name="عنوان شایستگی")
    competency_type = models.CharField(max_length=10, choices=[
        ('KN', 'دانش (Knowledge)'),
        ('SK', 'مهارت (Skill)'),
        ('AB', 'توانایی (Ability)'),
        ('GE', 'رفتاری (General/Behavioral)'),
        ('ST', 'ارزش‌ها و سبک‌ها (Styles & Values)'),
    ], default='GE', verbose_name="نوع شایستگی")
    importance = models.PositiveIntegerField(choices=[
        (1, 'محوری'),
        (2, 'تکلیف محور'),
        (3, 'حداقلی'),
    ], default=1, verbose_name="اهمیت شایستگی")
    level = models.PositiveIntegerField(choices=[
        (1, 'آشنایی'),
        (2, 'توانایی'),
        (3, 'تسلط'),
    ], default=2, verbose_name="سطح شایستگی")
    code = models.CharField(max_length=50, default='MODEL', verbose_name="کد شایستگی")

    class Meta:
        verbose_name = "شایستگی مدل"
        verbose_name_plural = "شایستگی‌های مدل"

    def __str__(self):
        return f"{self.title} - {self.competency_model.name}"



class AISetting(SoftDeleteModel):
    api_key = models.CharField(max_length=255, blank=True, verbose_name="کلید API")
    base_url = models.CharField(max_length=255, default="https://api.avalai.ir/v1", verbose_name="آدرس پایه (Base URL)")
    model_name = models.CharField(max_length=100, default="gpt-4o", verbose_name="نام مدل")
    is_active = models.BooleanField(default=True, verbose_name="فعال")

    class Meta:
        verbose_name = "تنظیمات هوش مصنوعی"
        verbose_name_plural = "تنظیمات هوش مصنوعی"

    def __str__(self):
        return f"تنظیمات AI - {self.model_name} ({'فعال' if self.is_active else 'غیرفعال'})"

    @classmethod
    def get_active_setting(cls):
        return cls.objects.filter(is_active=True).first()


class AIPostRecommendation(SoftDeleteModel):
    post_code = models.CharField(max_length=50, verbose_name="کد پست سازمانی")
    opt_advice = models.JSONField(null=True, blank=True, verbose_name="توصیه‌های بهینه‌سازی شایستگی‌ها")
    scenario = models.TextField(null=True, blank=True, verbose_name="سناریوی ارزیابی کانون ارزیابی")
    questions = models.JSONField(null=True, blank=True, verbose_name="سوالات مصاحبه ساختاریافته")
    benchmark_mappings = models.JSONField(null=True, blank=True, verbose_name="نگاشت بنچمارک‌های جهانی")
    last_generated = models.DateTimeField(auto_now=True, verbose_name="تاریخ آخرین تولید پاسخ")

    class Meta:
        verbose_name = "پیشنهاد هوش مصنوعی پست"
        verbose_name_plural = "پیشنهادات هوش مصنوعی پست‌ها"
        constraints = [
            models.UniqueConstraint(
                fields=['post_code'],
                condition=models.Q(is_deleted=False),
                name='unique_post_code_active_recommendation'
            )
        ]

    def __str__(self):
        return f"پیشنهاد AI برای پست {self.post_code}"


class OrganizationSetting(SoftDeleteModel):
    name = models.CharField(max_length=200, default="سیستم جذب", verbose_name="نام سازمان")
    logo = models.FileField(upload_to='org_logos/', blank=True, null=True, verbose_name="لوگوی سازمان")

    # ۱. ثبت‌نام و ورود اولیه به سامانه (ثبت‌نام)
    reg_email_enabled = models.BooleanField(default=True, verbose_name="ارسال ایمیل ثبت‌نام فعال باشد")
    reg_email_subject = models.CharField(max_length=255, default="دریافت رزومه با موفقیت انجام شد", verbose_name="موضوع ایمیل ثبت‌نام")
    reg_email_body = models.TextField(
        default="""<div dir="rtl" style="font-family: Tahoma, Arial, sans-serif; text-align: right; padding: 20px; line-height: 1.6; color: #1e293b;">
    <h2 style="color: #4f46e5;">دریافت رزومه با موفقیت انجام شد</h2>
    <p>جناب/سرکار خانم <strong>{{ candidate_name }}</strong> عزیز، سلام؛</p>
    <p>از علاقه‌مندی شما به همکاری با <strong>{{ company_name }}</strong> سپاسگزاریم.</p>
    <p>رزومه شما برای فرصت شغلی <strong>«{{ job_title }}»</strong> دریافت گردید و در حال حاضر در مرحله غربالگری اولیه قرار دارد.</p>
    <div style="background-color: #f8fafc; padding: 15px; border-radius: 8px; border-right: 4px solid #4f46e5; margin: 20px 0;">
        <strong>اطلاعات پیگیری وضعیت:</strong><br/>
        برای مشاهده وضعیت لحظه‌ای پرونده خود، دریافت بازخوردها و شرکت در آزمون‌های آنلاین آتی، می‌توانید به پنل اختصاصی متقاضیان مراجعه نمایید.<br/>
        <a href="{{ link }}" style="display: inline-block; margin-top: 10px; background-color: #4f46e5; color: #ffffff; padding: 8px 16px; text-decoration: none; border-radius: 6px;">ورود به پنل متقاضی</a>
    </div>
    <p>در صورت تایید رزومه شما، مراحل بعدی از طریق پیامک و ایمیل اطلاع‌رسانی خواهد شد.</p>
    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;"/>
    <small style="color: #64748b;">تیم جذب و استخدام {{ company_name }}</small>
</div>""",
        verbose_name="متن ایمیل ثبت‌نام (HTML)"
    )
    reg_sms_enabled = models.BooleanField(default=True, verbose_name="ارسال پیامک ثبت‌نام فعال باشد")
    reg_sms_body = models.TextField(
        default="{{ candidate_name }} عزیز، رزومه شما برای شغل \"{{ job_title }}\" در {{ company_name }} دریافت شد.\nبرای پیگیری وضعیت و آزمون‌ها به پنل خود مراجعه کنید:\n{{ link }}",
        verbose_name="متن پیامک ثبت‌نام"
    )

    # ۲. دعوت به آزمون کتبی / تخصصی
    exam_email_enabled = models.BooleanField(default=True, verbose_name="ارسال ایمیل دعوت به آزمون فعال باشد")
    exam_email_subject = models.CharField(max_length=255, default="دعوت به آزمون کتبی / تخصصی", verbose_name="موضوع ایمیل دعوت به آزمون")
    exam_email_body = models.TextField(
        default="""<div dir="rtl" style="font-family: Tahoma, Arial, sans-serif; text-align: right; padding: 20px; line-height: 1.6; color: #1e293b;">
    <h2 style="color: #4f46e5;">دعوت به آزمون کتبی / تخصصی</h2>
    <p>متقاضی گرامی <strong>{{ candidate_name }}</strong> عزیز، سلام؛</p>
    <p>پس از بررسی اولیه رزومه شما برای فرصت شغلی <strong>«{{ job_title }}»</strong>، بدین‌وسیله از شما جهت شرکت در مرحله **آزمون تخصصی** دعوت به عمل می‌آید.</p>
    <div style="background-color: #f8fafc; padding: 15px; border-radius: 8px; border-right: 4px solid #f59e0b; margin: 20px 0;">
        <strong>جزییات برگزاری آزمون:</strong>
        <ul>
            <li><strong>تاریخ برگزاری:</strong> {{ date }}</li>
            <li><strong>ساعت شروع:</strong> {{ time }}</li>
            <li><strong>مدت زمان آزمون:</strong> ۹۰ دقیقه</li>
            <li><strong>نوع آزمون:</strong> آنلاین (تستی و تشریحی)</li>
        </ul>
        <a href="{{ link }}" style="display: inline-block; margin-top: 10px; background-color: #4f46e5; color: #ffffff; padding: 8px 16px; text-decoration: none; border-radius: 6px;">ورود به سامانه آزمون آنلاین</a>
    </div>
    <p style="color: #ef4444; font-weight: bold;">⚠️ نکته مهم: لینک فوق فقط در بازه زمانی اعلام شده فعال خواهد بود.</p>
    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;"/>
    <small style="color: #64748b;">تیم جذب و استخدام {{ company_name }}</small>
</div>""",
        verbose_name="متن ایمیل دعوت به آزمون (HTML)"
    )
    exam_sms_enabled = models.BooleanField(default=True, verbose_name="ارسال پیامک دعوت به آزمون فعال باشد")
    exam_sms_body = models.TextField(
        default="متقاضی گرامی {{ candidate_name }}، دعوت‌نامه شرکت در آزمون کتبی شغل \"{{ job_title }}\" برای شما صادر شد.\nزمان آزمون: {{ date }} ساعت {{ time }}\nجزییات بیشتر و لینک شرکت در آزمون در پنل {{ company_name }}:\n{{ link }}",
        verbose_name="متن پیامک دعوت به آزمون"
    )

    # ۳. دعوت به مصاحبه (حضوری یا آنلاین)
    interview_email_enabled = models.BooleanField(default=True, verbose_name="ارسال ایمیل دعوت به مصاحبه فعال باشد")
    interview_email_subject = models.CharField(max_length=255, default="دعوت به جلسه مصاحبه تخصصی", verbose_name="موضوع ایمیل دعوت به مصاحبه")
    interview_email_body = models.TextField(
        default="""<div dir="rtl" style="font-family: Tahoma, Arial, sans-serif; text-align: right; padding: 20px; line-height: 1.6; color: #1e293b;">
    <h2 style="color: #4f46e5;">دعوت به جلسه مصاحبه تخصصی</h2>
    <p>جناب/سرکار خانم <strong>{{ candidate_name }}</strong> عزیز، سلام؛</p>
    <p>با توجه به نتایج مثبت ارزیابی‌های قبلی شما برای فرصت شغلی <strong>«{{ job_title }}»</strong>، از شما دعوت می‌شود در جلسه مصاحبه با تیم فنی و مدیران ارشد شرکت نمایید.</p>
    <div style="background-color: #f8fafc; padding: 15px; border-radius: 8px; border-right: 4px solid #10b981; margin: 20px 0;">
        <strong>مشخصات جلسه مصاحبه:</strong>
        <ul>
            <li><strong>تاریخ مصاحبه:</strong> {{ date }}</li>
            <li><strong>ساعت برگزاری:</strong> {{ time }}</li>
            <li><strong>نوع جلسه:</strong> آنلاین (تصویری)</li>
            <li><strong>لینک ورود به اتاق جلسه:</strong> <a href="{{ link }}">{{ link }}</a></li>
        </ul>
    </div>
    <p>پیشنهاد می‌شود ۱۰ دقیقه قبل از ساعت مقرر، اتصالات سیستم خود (دوربین و میکروفون) را بررسی نمایید. در صورت نیاز به هماهنگی مجدد با ایمیل یا شماره تماس کارشناس جذب مربوطه تماس حاصل فرمایید.</p>
    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;"/>
    <small style="color: #64748b;">تیم جذب و استخدام {{ company_name }}</small>
</div>""",
        verbose_name="متن ایمیل دعوت به مصاحبه (HTML)"
    )
    interview_sms_enabled = models.BooleanField(default=True, verbose_name="ارسال پیامک دعوت به مصاحبه فعال باشد")
    interview_sms_body = models.TextField(
        default="جناب/سرکار خانم {{ candidate_name }}، جلسه مصاحبه شما برای موقعیت شغلی \"{{ job_title }}\" تنظیم شد.\nزمان: {{ date }} ساعت {{ time }}\nجزییات و لینک اتصال آنلاین (یا لوکیشن حضوری) به ایمیل شما ارسال شد.\n{{ company_name }}",
        verbose_name="متن پیامک دعوت به مصاحبه"
    )

    # ۴. قبولی نهایی و پیشنهاد همکاری (Job Offer)
    offer_email_enabled = models.BooleanField(default=True, verbose_name="ارسال ایمیل پیشنهاد همکاری فعال باشد")
    offer_email_subject = models.CharField(max_length=255, default="🎉 تبریک! پذیرش نهایی و پیشنهاد همکاری در {{ company_name }}", verbose_name="موضوع ایمیل پیشنهاد همکاری")
    offer_email_body = models.TextField(
        default="""<div dir="rtl" style="font-family: Tahoma, Arial, sans-serif; text-align: right; padding: 20px; line-height: 1.6; color: #1e293b;">
    <h2 style="color: #10b981;">🎉 تبریک! پذیرش نهایی و پیشنهاد همکاری در {{ company_name }}</h2>
    <p>همکار آینده ما، جناب/سرکار خانم <strong>{{ candidate_name }}</strong> عزیز، سلام؛</p>
    <p>بسیار خرسندیم که به اطلاع شما برسانیم فرآیند ارزیابی‌های شما با موفقیت کامل سپری شده و شایستگی شما برای احراز فرصت شغلی <strong>«{{ job_title }}»</strong> مورد تایید نهایی قرار گرفته است.</p>
    <p>ما مشتاقانه منتظر پیوستن شما به تیم پویای <strong>{{ company_name }}</strong> هستیم.</p>
    <div style="background-color: #f0fdf4; padding: 15px; border-radius: 8px; border: 1px solid #bbf7d0; margin: 20px 0;">
        <strong>گام بعدی چیست؟</strong><br/>
        پیش‌نویس تفاهم‌نامه و آفر فرم همکاری (شامل جزییات حقوق، بیمه، ساعات کاری و مزایا) پیوست این ایمیل شده و در پنل شما قرار گرفته است. خواهشمند است حداکثر تا تاریخ {{ date }} فرم امضا شده را از طریق لینک زیر برای ما ارسال نمایید.<br/>
        <a href="{{ link }}" style="display: inline-block; margin-top: 10px; background-color: #10b981; color: #ffffff; padding: 8px 16px; text-decoration: none; border-radius: 6px; font-weight: bold;">بررسی و امضای پیشنهاد همکاری</a>
    </div>
    <p>در صورت وجود هرگونه ابهام یا سوال، کارشناس جذب ما <strong>{{ recruiter_name }}</strong> آماده پاسخگویی به شماست.</p>
    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;"/>
    <small style="color: #64748b;">مدیریت منابع انسانی {{ company_name }}</small>
</div>""",
        verbose_name="متن ایمیل پیشنهاد همکاری (HTML)"
    )
    offer_sms_enabled = models.BooleanField(default=True, verbose_name="ارسال پیامک پیشنهاد همکاری فعال باشد")
    offer_sms_body = models.TextField(
        default="تبریک فراوان {{ candidate_name }} عزیز! 🎉\nشما در فرآیند جذب \"{{ job_title }}\" پذیرفته شدید.\nآفر فرم (پیشنهاد همکاری) به ایمیل شما ارسال شد. لطفا نسبت به بررسی و امضای آن اقدام کنید:\n{{ link }}\n{{ company_name }}",
        verbose_name="متن پیامک پیشنهاد همکاری"
    )

    # ۵. عدم پذیرش / مردودی (Rejection)
    reject_email_enabled = models.BooleanField(default=True, verbose_name="ارسال ایمیل رد رزومه فعال باشد")
    reject_email_subject = models.CharField(max_length=255, default="تقدیر و تشکر از حضور در فرآیند ارزیابی", verbose_name="موضوع ایمیل رد رزومه")
    reject_email_body = models.TextField(
        default="""<div dir="rtl" style="font-family: Tahoma, Arial, sans-serif; text-align: right; padding: 20px; line-height: 1.6; color: #1e293b;">
    <h2 style="color: #ef4444;">تقدیر و تشکر از حضور در فرآیند ارزیابی</h2>
    <p>جناب/سرکار خانم <strong>{{ candidate_name }}</strong> عزیز، سلام؛</p>
    <p>از اینکه وقت گرانبهای خود را برای شرکت در فرآیند استخدام موقعیت شغلی <strong>«{{ job_title }}»</strong> در اختیار <strong>{{ company_name }}</strong> قرار دادید، صمیمانه سپاسگزاریم.</p>
    <p>پس از بررسی‌های دقیق و مصاحبه‌های انجام شده با کاندیداهای محترم، متاسفانه در این دوره امکان پذیرش و همکاری با شما فراهم نگردید. انتخاب نهایی بر اساس تطابق حداکثری نیازهای فعلی تیم با سوابق فنی صورت گرفته و این به معنی نفی شایستگی‌های ارزشمند شما نیست.</p>
    <div style="background-color: #f8fafc; padding: 15px; border-radius: 8px; border-right: 4px solid #ef4444; margin: 20px 0;">
        <strong>نگاهداشت رزومه در بانک استعدادها:</strong><br/>
        سوابق ارزنده شما در بانک استعدادهای (Talent Pool) ما آرشیو می‌شود تا در صورت تعریف فرصت‌های شغلی جدید و متناسب با تخصصتان، در اولویت تماس مجدد همکاران ما قرار بگیرید.
    </div>
    <p>برای شما در تمام مراحل زندگی حرفه‌ای آرزوی موفقیت و پیروزی داریم.</p>
    <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;"/>
    <small style="color: #64748b;">تیم جذب و استخدام {{ company_name }}</small>
</div>""",
        verbose_name="متن ایمیل رد رزومه (HTML)"
    )
    reject_sms_enabled = models.BooleanField(default=True, verbose_name="ارسال پیامک رد رزومه فعال باشد")
    reject_sms_body = models.TextField(
        default="{{ candidate_name }} عزیز، از وقتی که برای ارزیابی شغل \"{{ job_title }}\" در {{ company_name }} گذاشتید سپاسگزاریم.\nمتاسفانه در این دوره امکان همکاری فراهم نشد. رزومه شما در بانک استعدادهای ما ذخیره می‌گردد.\nنامه رسمی و جزئیات بیشتر به ایمیل شما ارسال شد.",
        verbose_name="متن پیامک رد رزومه"
    )

    # --- تنظیمات درگاه‌های ارتباطی (SMTP & SMS Gateways) ---
    
    # تنظیمات SMTP (ایمیل)
    EMAIL_PROVIDER_CHOICES = [
        ('CUSTOM', 'ایجاد دستی (SMTP سفارشی)'),
        ('GMAIL', 'گوگل (Gmail)'),
        ('OUTLOOK', 'اوتلوک (Outlook)'),
    ]
    email_provider = models.CharField(max_length=30, choices=EMAIL_PROVIDER_CHOICES, default='CUSTOM', verbose_name="سرویس‌دهنده ایمیل")
    smtp_host = models.CharField(max_length=255, default="", blank=True, verbose_name="آدرس سرور SMTP (مثال: smtp.gmail.com)")
    smtp_port = models.IntegerField(default=587, verbose_name="پورت SMTP")
    smtp_user = models.CharField(max_length=255, default="", blank=True, verbose_name="نام کاربری SMTP (ایمیل)")
    smtp_password = models.CharField(max_length=255, default="", blank=True, verbose_name="کلمه عبور SMTP")
    smtp_use_tls = models.BooleanField(default=True, verbose_name="استفاده از TLS")
    smtp_use_ssl = models.BooleanField(default=False, verbose_name="استفاده از SSL")
    smtp_sender_email = models.EmailField(default="", blank=True, verbose_name="ایمیل فرستنده پیش‌فرض")

    # تنظیمات پنل پیامک (SMS Gateway)
    SMS_PROVIDER_CHOICES = [
        ('MOCK', 'شبیه‌ساز (ثبت در فایل لاگ سیستم)'),
        ('KAVENEGAR', 'پنل کاوه نگار (Kavenegar)'),
        ('MELIPAYAMAK', 'پنل ملی پیامک (Melipayamak)'),
        ('FARAPAYAMAK', 'پنل فراپیامک (Farapayamak)'),
        ('OTHER', 'سایر پیام‌رسان‌ها (پیام‌رسان‌های دیگر)'),
        ('CUSTOM', 'ایجاد دستی درگاه (تنظیم آدرس API اختصاصی)'),
    ]
    sms_provider = models.CharField(max_length=30, choices=SMS_PROVIDER_CHOICES, default='MOCK', verbose_name="ارائه‌دهنده پنل پیامک")
    sms_api_key = models.CharField(max_length=255, default="", blank=True, verbose_name="کلید API / کلمه عبور پنل")
    sms_sender_number = models.CharField(max_length=50, default="", blank=True, verbose_name="شماره خط اختصاصی فرستنده")
    sms_custom_url = models.CharField(max_length=500, default="", blank=True, verbose_name="آدرس API اختصاصی / دستی")
    license_key = models.TextField(default="", blank=True, verbose_name="کلید لایسنس سیستم")

    class Meta:
        verbose_name = "تنظیمات سازمان"
        verbose_name_plural = "تنظیمات سازمان"

    def __str__(self):
        return self.name

    @classmethod
    def get_active_setting(cls):
        setting = cls.objects.filter(is_deleted=False).first()
        if not setting:
            setting = cls.objects.create(name="سیستم جذب")
        return setting
