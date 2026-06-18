from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from apps.core.models import SoftDeleteModel
from apps.jobs.models import JobOpportunity, JobOpportunityStage, AssessmentCompetency

class Candidate(SoftDeleteModel):
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='candidate_profile', verbose_name="کاربر متصل")
    first_name = models.CharField(max_length=100, verbose_name="نام")
    last_name = models.CharField(max_length=100, verbose_name="نام خانوادگی")
    email = models.EmailField(blank=True, verbose_name="ایمیل")
    phone_number = models.CharField(max_length=15, verbose_name="شماره تماس")
    national_id = models.CharField(max_length=10, unique=True, verbose_name="کد ملی")
    personnel_number = models.CharField(max_length=20, blank=True, null=True, unique=True, verbose_name="شماره پرسنلی")
    resume = models.FileField(upload_to='resumes/', blank=True, null=True, verbose_name="فایل رزومه")

    class Meta:
        verbose_name = "متقاضی"
        verbose_name_plural = "متقاضیان"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def stage_scores(self):
        scores = {'exam': None, 'interview': None, 'assessment': None}
        exam_kws = ["آزمون", "امتحان", "کتبی", "exam", "test"]
        intv_kws = ["مصاحبه", "interview"]
        asmt_kws = ["کانون", "ارزیابی", "assessment", "سنتر", "competency"]
        
        for app in self.applications.all():
            if app.is_deleted:
                continue
            for state in app.stage_states.all():
                if state.is_deleted:
                    continue
                name_lower = state.stage.name.lower()
                score = state.score
                if any(kw in name_lower for kw in exam_kws):
                    if scores['exam'] is None or score > scores['exam']:
                        scores['exam'] = score
                elif any(kw in name_lower for kw in intv_kws):
                    if scores['interview'] is None or score > scores['interview']:
                        scores['interview'] = score
                elif any(kw in name_lower for kw in asmt_kws):
                    if scores['assessment'] is None or score > scores['assessment']:
                        scores['assessment'] = score
        return scores



class CandidateEducation(SoftDeleteModel):
    DEGREE_CHOICES = [
        ('ASSOCIATE', 'کاردانی'),
        ('BACHELOR', 'کارشناسی'),
        ('MASTER', 'کارشناسی ارشد'),
        ('PHD', 'دکتری'),
    ]

    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='education', verbose_name="متقاضی")
    degree = models.CharField(max_length=20, choices=DEGREE_CHOICES, verbose_name="مقطع تحصیلی")
    major = models.CharField(max_length=100, verbose_name="رشته تحصیلی")
    university = models.CharField(max_length=100, verbose_name="دانشگاه / موسسه")
    gpa = models.FloatField(verbose_name="معدل")
    graduation_year = models.PositiveIntegerField(verbose_name="سال فارغ‌التحصیلی")

    class Meta:
        verbose_name = "سابقه تحصیلی متقاضی"
        verbose_name_plural = "سوابق تحصیلی متقاضیان"
        ordering = ['-graduation_year']

    def __str__(self):
        return f"{self.get_degree_display()} {self.major} - {self.university}"


class CandidateExperience(SoftDeleteModel):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='experience', verbose_name="متقاضی")
    company = models.CharField(max_length=100, verbose_name="نام شرکت / سازمان")
    job_title = models.CharField(max_length=100, verbose_name="عنوان شغلی")
    start_date = models.DateField(verbose_name="تاریخ شروع")
    end_date = models.DateField(null=True, blank=True, verbose_name="تاریخ پایان")
    description = models.TextField(blank=True, verbose_name="شرح مسئولیت‌ها و دستاوردها")

    class Meta:
        verbose_name = "سابقه کاری متقاضی"
        verbose_name_plural = "سوابق کاری متقاضیان"
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.job_title} در {self.company}"


class JobApplication(SoftDeleteModel):
    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_SELECTED = 'SELECTED'
    STATUS_RESERVE = 'RESERVE'
    STATUS_REJECTED = 'REJECTED'

    STATUS_CHOICES = [
        (STATUS_IN_PROGRESS, 'در حال بررسی / ارزیابی'),
        (STATUS_SELECTED, 'پذیرفته شده نهایی'),
        (STATUS_RESERVE, 'ذخیره'),
        (STATUS_REJECTED, 'رد شده'),
    ]

    job = models.ForeignKey(JobOpportunity, on_delete=models.CASCADE, related_name='applications', verbose_name="فرصت شغلی")
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='applications', verbose_name="متقاضی")
    current_stage = models.ForeignKey(JobOpportunityStage, on_delete=models.SET_NULL, null=True, blank=True, related_name='active_applications', verbose_name="مرحله فعلی ارزیابی")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS, verbose_name="وضعیت نهایی درخواست")
    final_score = models.FloatField(default=0.0, verbose_name="امتیاز کل محاسبه شده")
    admission_date = models.DateField(null=True, blank=True, verbose_name="تاریخ پذیرش نهایی")

    @property
    def effective_status(self):
        # 1. If any active stage state is FAILED, then status is REJECTED
        for state in self.stage_states.all():
            if state.status == 'FAILED' and not state.is_conditional_pass and not state.is_deleted:
                return self.STATUS_REJECTED
        
        # 2. If the job status is CLOSED or FINAL_SELECTION (meaning selection is finalized), 
        # and this app is still IN_PROGRESS, it is effectively REJECTED
        if self.status == self.STATUS_IN_PROGRESS:
            if self.job.status in [JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_FINAL_SELECTION]:
                return self.STATUS_REJECTED
                
        return self.status

    class Meta:
        verbose_name = "درخواست همکاری"
        verbose_name_plural = "درخواست‌های همکاری"
        unique_together = ('job', 'candidate')
        ordering = ['-created_at']

    def __str__(self):
        return f"درخواست {self.candidate} برای {self.job.title}"

    def recalculate_current_stage(self, save=True):
        stages = list(self.job.stages.filter(is_deleted=False).order_by('sequence'))
        if not stages:
            if self.current_stage is not None:
                self.current_stage = None
                if save:
                    self.save(update_fields=['current_stage'])
            return None

        if self.pk is None:
            # If the application is new, it has no stage states, so it's in the first stage.
            target_stage = stages[0]
        else:
            # Get completed or conditional pass stages
            completed_or_conditional = set(self.stage_states.filter(
                is_deleted=False,
                status='COMPLETED'
            ).values_list('stage_id', flat=True)) | set(self.stage_states.filter(
                is_deleted=False,
                is_conditional_pass=True
            ).values_list('stage_id', flat=True))

            target_stage = None
            for stage in stages:
                if stage.id not in completed_or_conditional:
                    target_stage = stage
                    break
            if not target_stage and stages:
                target_stage = stages[-1]

        if self.current_stage != target_stage:
            self.current_stage = target_stage
            if save:
                self.save(update_fields=['current_stage'])
        return target_stage

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        
        # پیش‌محاسبه مرحله جاری قبل از ذخیره اولیه
        if not getattr(self, '_bypass_stage_recalculation', False):
            import sys
            is_importing = getattr(self, '_bypass_screening_auto_fail', False) or any(
                'import_historical' in arg or 'update_historical' in arg or 'fix_missing' in arg 
                for arg in sys.argv
            )
            if not is_new and not is_importing:
                # Check if this application is rejected or the job has moved past screening,
                # meaning they failed screening if they have no scores in subsequent stages.
                # Also, if they have no scores, they are no longer in progress, so we should reject them.
                should_check_screening = False
                
                # Those that are in early statuses (RECEIVED, PLANNING, PUBLISHED, SCREENING) should not get screening failed
                early_statuses = [
                    JobOpportunity.STATUS_RECEIVED,
                    JobOpportunity.STATUS_PLANNING,
                    JobOpportunity.STATUS_PUBLISHED,
                    JobOpportunity.STATUS_SCREENING,
                ]
                
                if self.job.status not in early_statuses:
                    if self.status == self.STATUS_REJECTED or self.effective_status == self.STATUS_REJECTED:
                        should_check_screening = True
                    else:
                        # If job has moved past screening
                        past_screening_statuses = [
                            JobOpportunity.STATUS_EXAM,
                            JobOpportunity.STATUS_SKILL_TEST,
                            JobOpportunity.STATUS_INTERVIEW,
                            JobOpportunity.STATUS_ASSESSMENT,
                            JobOpportunity.STATUS_FINAL_SELECTION,
                            JobOpportunity.STATUS_CLOSED,
                            JobOpportunity.STATUS_CANCELLED,
                            JobOpportunity.STATUS_SUSPENDED
                        ]
                        if self.job.status in past_screening_statuses:
                            should_check_screening = True

                if should_check_screening:
                    stages = list(self.job.stages.filter(is_deleted=False).order_by('sequence'))
                    if stages:
                        first_stage = stages[0]
                        if 'غربالگری' in first_stage.name or first_stage.stage_type == 'SCREENING':
                            # Check subsequent stages states
                            subsequent_states = self.stage_states.filter(stage__sequence__gt=first_stage.sequence, is_deleted=False)
                            all_pending_zero = True
                            for state in subsequent_states:
                                if state.score != 0.0 or state.status != 'PENDING':
                                    all_pending_zero = False
                                    break
                            
                            # If job is in EXAM stage, only fail them if other candidates have scores entered
                            if self.job.status == JobOpportunity.STATUS_EXAM:
                                other_has_scores = self.job.applications.filter(
                                    is_deleted=False,
                                    stage_states__stage__sequence__gt=first_stage.sequence,
                                    stage_states__is_deleted=False
                                ).exclude(
                                    stage_states__score=0.0,
                                    stage_states__status='PENDING'
                                ).exists()
                                if not other_has_scores:
                                    all_pending_zero = False
                            
                            if subsequent_states.exists() and all_pending_zero:
                                scr_state = self.stage_states.filter(stage=first_stage, is_deleted=False).first()
                                if scr_state and scr_state.status != 'FAILED' and scr_state.status != 'COMPLETED':
                                    scr_state.status = 'FAILED'
                                    super(ApplicationStageState, scr_state).save(update_fields=['status'])
                                    
                                    # clear cached relation to force refetch
                                    if 'stage_states' in self.__dict__:
                                        del self.__dict__['stage_states']
                                    if hasattr(self, '_prefetched_objects_cache') and 'stage_states' in self._prefetched_objects_cache:
                                        del self._prefetched_objects_cache['stage_states']
                                        
                                    if self.status != self.STATUS_REJECTED:
                                        self.status = self.STATUS_REJECTED
                                        update_fields = kwargs.get('update_fields')
                                        if update_fields is not None:
                                            update_fields = list(update_fields)
                                            if 'status' not in update_fields:
                                                update_fields.append('status')
                                            kwargs['update_fields'] = update_fields
            
            old_stage = self.current_stage
            self.recalculate_current_stage(save=False)
            if self.current_stage != old_stage:
                update_fields = kwargs.get('update_fields')
                if update_fields is not None:
                    update_fields = list(update_fields)
                    if 'current_stage' not in update_fields:
                        update_fields.append('current_stage')
                    kwargs['update_fields'] = update_fields

        super().save(*args, **kwargs)
        
        # در صورت ایجاد درخواست جدید، به تعداد مراحل فعال فرصت شغلی، رکوردهای وضعیت مراحل ثبت می‌شود
        if is_new and not getattr(self, '_bypass_stage_creation', False):
            job_stages = self.job.stages.filter(is_deleted=False).order_by('sequence')
            
            # در صورت وجود مراحل، مرحله اول به عنوان مرحله جاری تنظیم می‌شود
            if job_stages.exists():
                self.current_stage = job_stages.first()
                # ذخیره مجدد فیلد current_stage
                super().save(update_fields=['current_stage'])
                
            for stage in job_stages:
                ApplicationStageState.objects.create(
                    application=self,
                    stage=stage,
                    status=ApplicationStageState.STATUS_PENDING,
                    score=0.0
                )
        
        if self.job:
            self.job.update_status()


class ApplicationStageState(SoftDeleteModel):
    STATUS_PENDING = 'PENDING'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_FAILED = 'FAILED'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'در انتظار ارزیابی'),
        (STATUS_COMPLETED, 'قبول شده در این مرحله'),
        (STATUS_FAILED, 'مردود شده در این مرحله'),
    ]

    application = models.ForeignKey(JobApplication, on_delete=models.CASCADE, related_name='stage_states', verbose_name="درخواست همکاری")
    stage = models.ForeignKey(JobOpportunityStage, on_delete=models.CASCADE, related_name='candidate_states', verbose_name="مرحله ارزیابی شغل")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, verbose_name="وضعیت مرحله")
    score = models.FloatField(default=0.0, verbose_name="امتیاز کسب شده")
    evaluator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='evaluated_stages', verbose_name="ثبت‌کننده نمره")
    notes = models.TextField(blank=True, verbose_name="توضیحات ارزیاب")
    score_discrepancy_alert = models.BooleanField(default=False, verbose_name="هشدار اختلاف فاحش نمرات")
    is_conditional_pass = models.BooleanField(default=False, verbose_name="قبول ارفاقی / ارجاع مشروط")
    evaluation_date = models.DateField(null=True, blank=True, verbose_name="تاریخ ارزیابی")
    is_manually_edited = models.BooleanField(default=False, verbose_name="ویرایش شده به صورت دستی")

    class Meta:
        verbose_name = "وضعیت مرحله ارزیابی متقاضی"
        verbose_name_plural = "وضعیت‌های مراحل ارزیابی متقاضیان"
        unique_together = ('application', 'stage')
        ordering = ['stage__sequence']

    def __str__(self):
        return f"وضعیت {self.stage.name} برای {self.application.candidate.last_name}"

    @property
    def is_accessible(self):
        # The stage state is accessible (editable) if all prior stages (by sequence) are COMPLETED or is_conditional_pass.
        prior_states = self.application.stage_states.filter(
            stage__sequence__lt=self.stage.sequence,
            is_deleted=False
        )
        return all(state.status == ApplicationStageState.STATUS_COMPLETED or state.is_conditional_pass for state in prior_states)

    @property
    def has_failed_prior_stages(self):
        if hasattr(self, 'has_failed_prior'):
            return self.has_failed_prior
        prior_states = self.application.stage_states.filter(
            stage__sequence__lt=self.stage.sequence,
            is_deleted=False
        )
        return any(state.status == self.STATUS_FAILED and not state.is_conditional_pass for state in prior_states)

    @property
    def prev_stage_state(self):
        return self.application.stage_states.filter(
            stage__sequence__lt=self.stage.sequence,
            is_deleted=False
        ).order_by('-stage__sequence').first()

    @property
    def actual_evaluation_date(self):
        if self.evaluation_date:
            return self.evaluation_date
        
        from apps.recruitment_planning.models import JobStagePlan
        stage_plan = JobStagePlan.objects.filter(
            plan__job=self.application.job,
            stage=self.stage,
            is_deleted=False
        ).first()
        if stage_plan and stage_plan.planned_end_date:
            return stage_plan.planned_end_date
            
        return None

    @property
    def days_since_prev_stage(self):
        if self.status == self.STATUS_PENDING:
            return None
        prev = self.prev_stage_state
        if not prev or prev.status == self.STATUS_PENDING:
            return None
        
        curr_date = self.actual_evaluation_date
        prev_date = prev.actual_evaluation_date
        
        if curr_date and prev_date:
            return (curr_date - prev_date).days
        return None

    def save(self, *args, **kwargs):
        # Calculate score and status based on individual interviewer scores (assigned, external or competency)
        # Skip this for screening stages as they do not have numeric scores
        if self.stage.stage_type == 'SCREENING':
            pass
        elif self.pk and not getattr(self, '_bypass_status_calculation', False) and not getattr(self, '_bypass_stage_score_calculation', False):
            external_scores = self.external_interviewer_scores.filter(is_deleted=False)
            if external_scores.exists():
                total_weight = sum(es.weight for es in external_scores)
                weighted_sum = sum(es.score * es.weight for es in external_scores)
                self.score = round(weighted_sum / total_weight, 2) if total_weight > 0 else 0.0
                
                # Auto pass/fail detection based on stage passing cutoff
                if self.score >= self.stage.passing_score:
                    self.status = self.STATUS_COMPLETED
                else:
                    self.status = self.STATUS_FAILED
            else:
                assigned_intv = self.stage.interviewers.filter(is_deleted=False)
                if assigned_intv.exists():
                    scores_qs = self.interviewer_scores.filter(is_deleted=False).exclude(status='PENDING')
                    if scores_qs.exists():
                        total_weight = 0
                        weighted_sum = 0.0
                        for iscore in scores_qs:
                            mapping = assigned_intv.filter(user=iscore.interviewer).first()
                            weight = mapping.weight if mapping else 100
                            weighted_sum += iscore.score * weight
                            total_weight += weight
                        self.score = round(weighted_sum / total_weight, 2) if total_weight > 0 else 0.0
                        
                        if scores_qs.count() == assigned_intv.count():
                            # Discrepancy alert calculation (max - min >= 20.0)
                            scores_list = [iscore.score for iscore in scores_qs]
                            if len(scores_list) > 1 and (max(scores_list) - min(scores_list)) >= 20.0:
                                self.score_discrepancy_alert = True
                            else:
                                self.score_discrepancy_alert = False
                            
                            # Auto pass/fail detection based on stage passing cutoff
                            if self.score >= self.stage.passing_score:
                                self.status = self.STATUS_COMPLETED
                            else:
                                self.status = self.STATUS_FAILED
                        else:
                            self.status = self.STATUS_PENDING
                            self.score_discrepancy_alert = False
                else:
                    # If no interviewers are assigned, but interviewer scores exist (e.g. from competency sheet)
                    scores_qs = self.interviewer_scores.filter(is_deleted=False).exclude(status='PENDING')
                    if scores_qs.exists():
                        total_score = sum(iscore.score for iscore in scores_qs)
                        self.score = round(total_score / scores_qs.count(), 2)
                        
                        if self.score >= self.stage.passing_score:
                            self.status = self.STATUS_COMPLETED
                        else:
                            self.status = self.STATUS_FAILED
                    else:
                        # Fallback to manual score evaluation if evaluator is set
                        if self.evaluator:
                            if self.score >= self.stage.passing_score:
                                self.status = self.STATUS_COMPLETED
                            else:
                                self.status = self.STATUS_FAILED

        super().save(*args, **kwargs)
        
        # Calculate final weighted score for the application
        # این بلاک هم مثل بلاک بالا باید bypass شود تا در ایمپورت تاریخچه وضعیت app به‌هم نریزد
        if not getattr(self, '_bypass_status_calculation', False):
            app = self.application
            update_fields = ['final_score']
            
            # 1. Update application status based on stage status
            if self.status == self.STATUS_FAILED and not self.is_conditional_pass:
                if app.status != JobApplication.STATUS_REJECTED:
                    app.status = JobApplication.STATUS_REJECTED
                    update_fields.append('status')
            elif (self.status == self.STATUS_COMPLETED or self.is_conditional_pass) and app.status == JobApplication.STATUS_REJECTED:
                # Revert to IN_PROGRESS if no other stages are failed
                other_failed = app.stage_states.filter(
                    status=self.STATUS_FAILED,
                    is_conditional_pass=False,
                    is_deleted=False
                ).exclude(pk=self.pk).exists()
                if not other_failed:
                    app.status = JobApplication.STATUS_IN_PROGRESS
                    update_fields.append('status')

            # 2. Recalculate current_stage of the application
            app.recalculate_current_stage(save=False)
            if 'current_stage' not in update_fields:
                update_fields.append('current_stage')

            total_weighted_score = 0.0
            # Get all active stage states
            states = app.stage_states.filter(is_deleted=False)
            for state in states:
                # We multiply score by the weight of the stage (which is in stage.weight)
                total_weighted_score += (state.score * state.stage.weight) / 100.0
            app.final_score = round(total_weighted_score, 2)
            app.save(update_fields=update_fields)


class CandidateLanguage(SoftDeleteModel):
    PROFICIENCY_CHOICES = [
        ('ELEMENTARY', 'مقدماتی'),
        ('INTERMEDIATE', 'متوسط'),
        ('ADVANCED', 'پیشرفته'),
        ('NATIVE', 'زبان مادری'),
    ]
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='languages', verbose_name="متقاضی")
    name = models.CharField(max_length=100, verbose_name="نام زبان")
    proficiency = models.CharField(max_length=20, choices=PROFICIENCY_CHOICES, default='INTERMEDIATE', verbose_name="سطح تسلط")

    class Meta:
        verbose_name = "زبان متقاضی"
        verbose_name_plural = "زبان‌های متقاضی"

    def __str__(self):
        return f"{self.name} ({self.get_proficiency_display()})"


class CandidateSkill(SoftDeleteModel):
    LEVEL_CHOICES = [
        ('BEGINNER', 'مبتدی'),
        ('INTERMEDIATE', 'متوسط'),
        ('EXPERT', 'متخصص'),
    ]
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='skills', verbose_name="متقاضی")
    name = models.CharField(max_length=100, verbose_name="نام مهارت")
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='INTERMEDIATE', verbose_name="سطح مهارت")

    class Meta:
        verbose_name = "مهارت متقاضی"
        verbose_name_plural = "مهارت‌های متقاضی"

    def __str__(self):
        return f"{self.name} ({self.get_level_display()})"


class CandidateCertificate(SoftDeleteModel):
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name='certificates', verbose_name="متقاضی")
    name = models.CharField(max_length=200, verbose_name="عنوان گواهینامه / دوره")
    issuer = models.CharField(max_length=200, verbose_name="موسسه صادرکننده")
    issue_date = models.DateField(verbose_name="تاریخ اخذ")
    expiration_date = models.DateField(null=True, blank=True, verbose_name="تاریخ انقضا")

    class Meta:
        verbose_name = "گواهینامه متقاضی"
        verbose_name_plural = "گواهینامه‌های متقاضی"

    def __str__(self):
        return f"{self.name} - {self.issuer}"


class InterviewerScore(SoftDeleteModel):
    stage_state = models.ForeignKey(ApplicationStageState, on_delete=models.CASCADE, related_name='interviewer_scores', verbose_name="وضعیت مرحله")
    interviewer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='given_scores', verbose_name="مصاحبه‌گر")
    score = models.FloatField(default=0.0, verbose_name="نمره ثبت شده")
    status = models.CharField(
        max_length=20, 
        choices=ApplicationStageState.STATUS_CHOICES, 
        default=ApplicationStageState.STATUS_PENDING, 
        verbose_name="وضعیت مرحله"
    )
    notes = models.TextField(blank=True, verbose_name="توضیحات مصاحبه‌گر")

    class Meta:
        verbose_name = "نمره مصاحبه‌گر"
        verbose_name_plural = "نمرات مصاحبه‌گران"
        unique_together = ('stage_state', 'interviewer')

    def __str__(self):
        return f"نمره {self.interviewer.username} برای {self.stage_state.application.candidate.last_name}: {self.score}"

    def save(self, *args, **kwargs):
        # Calculate weighted average from competency scores if they exist
        if self.pk:
            comp_scores = self.competency_scores.filter(is_deleted=False)
            if comp_scores.exists():
                total_weight = 0
                weighted_sum = 0.0
                for cs in comp_scores:
                    weighted_sum += cs.score * cs.competency.weight
                    total_weight += cs.competency.weight
                self.score = round(weighted_sum / total_weight, 2) if total_weight > 0 else 0.0

        super().save(*args, **kwargs)
        # Trigger recalculation of overall stage state score
        self.stage_state.save()


class AssessorCompetencyScore(SoftDeleteModel):
    interviewer_score = models.ForeignKey(InterviewerScore, on_delete=models.CASCADE, related_name='competency_scores', verbose_name="نمره مصاحبه‌گر")
    competency = models.ForeignKey(AssessmentCompetency, on_delete=models.CASCADE, related_name='given_scores', verbose_name="شایستگی")
    score = models.FloatField(default=0.0, verbose_name="نمره")
    notes = models.TextField(blank=True, verbose_name="یادداشت")

    class Meta:
        verbose_name = "نمره شایستگی ارزیاب"
        verbose_name_plural = "سوابق نمرات شایستگی کانون"
        unique_together = ('interviewer_score', 'competency')

    def __str__(self):
        return f"{self.competency.name}: {self.score}"


class ExternalInterviewerScore(SoftDeleteModel):
    stage_state = models.ForeignKey(
        ApplicationStageState, 
        on_delete=models.CASCADE, 
        related_name='external_interviewer_scores', 
        verbose_name="وضعیت مرحله"
    )
    interviewer_name = models.CharField(max_length=255, verbose_name="نام مصاحبه‌گر")
    score = models.FloatField(default=0.0, verbose_name="نمره ثبت شده")
    weight = models.PositiveIntegerField(default=100, verbose_name="وزن نمره")
    notes = models.TextField(blank=True, verbose_name="توضیحات")

    class Meta:
        verbose_name = "نمره مصاحبه‌گر خارجی"
        verbose_name_plural = "نمرات مصاحبه‌گران خارجی"

    def __str__(self):
        return f"{self.interviewer_name}: {self.score} (وزن: {self.weight})"


class JobDefaultInterviewer(SoftDeleteModel):
    """
    مصاحبه‌گران پیش‌فرض یک فرصت شغلی.
    یک‌بار برای هر فرصت شغلی تعریف می‌شوند و در تمام دوره‌های مصاحبه
    به‌عنوان ردیف‌های آماده نمایش داده می‌شوند.
    """
    job = models.ForeignKey(
        JobOpportunity,
        on_delete=models.CASCADE,
        related_name='default_interviewers',
        verbose_name="فرصت شغلی"
    )
    interviewer_name = models.CharField(max_length=255, verbose_name="نام مصاحبه‌گر")
    weight = models.PositiveIntegerField(default=100, verbose_name="وزن نمره")
    notes = models.TextField(blank=True, verbose_name="توضیحات")

    class Meta:
        verbose_name = "مصاحبه‌گر پیش‌فرض فرصت شغلی"
        verbose_name_plural = "مصاحبه‌گران پیش‌فرض فرصت شغلی"
        ordering = ['job', 'interviewer_name']

    def __str__(self):
        return f"{self.interviewer_name} — {self.job.title} (وزن: {self.weight})"

