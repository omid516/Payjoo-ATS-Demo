import hashlib
from django.core.cache import cache
from django.db import transaction, models
from django.apps import apps
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from apps.core.models import AuditLog, SoftDeleteModel
from apps.core.utils import log_action
from apps.candidates.models import JobApplication, ApplicationStageState
from apps.jobs.models import JobOpportunityStage

# Abstract Base Class for Integrity Checks
class BaseIntegrityCheck:
    code = ""
    name = ""
    description = ""
    category = "user"  # 'import' or 'user'
    is_auto_fixable = False

    def scan(self):
        """
        Executes the query and returns a list of discrepancies.
        Each item is a dict with details and possible resolution actions.
        """
        raise NotImplementedError("Integrity checks must implement scan()")


# 1. Missing Stage States Check (Category: import, Auto-fixable)
class MissingStageStatesCheck(BaseIntegrityCheck):
    code = "missing_stages"
    name = "مراحل ارزیابی گم‌شده"
    description = "متقاضیانی که در حال بررسی هستند اما رکوردهای ارزیابی برخی مراحل استخدام برای آن‌ها ساخته نشده است."
    category = "import"
    is_auto_fixable = True

    def scan(self):
        discrepancies = []
        # Query active applications
        apps_qs = JobApplication.objects.filter(
            is_deleted=False,
            status=JobApplication.STATUS_IN_PROGRESS
        ).select_related('candidate', 'job')
        
        for app in apps_qs:
            job_stages = list(app.job.stages.filter(is_deleted=False))
            states_count = app.stage_states.filter(is_deleted=False).count()
            if len(job_stages) > states_count:
                # Find missing stages
                existing_stage_ids = set(app.stage_states.filter(is_deleted=False).values_list('stage_id', flat=True))
                missing_stages = [s for s in job_stages if s.id not in existing_stage_ids]
                
                if missing_stages:
                    issue_id = f"missing_{app.id}"
                    discrepancies.append({
                        'id': issue_id,
                        'code': self.code,
                        'entity_id': app.id,
                        'candidate_name': f"{app.candidate.first_name} {app.candidate.last_name}",
                        'national_id': app.candidate.national_id,
                        'candidate_id': app.candidate.id,
                        'job_title': app.job.title,
                        'job_code': app.job.code,
                        'job_id': app.job.id,
                        'details': f"تعداد {len(missing_stages)} مرحله ارزیابی ({', '.join(s.name for s in missing_stages)}) وجود ندارد.",
                        'is_auto_fixable': self.is_auto_fixable,
                        'actions': [
                            {
                                'key': 'create_missing',
                                'label': 'ایجاد رکوردهای مراحل گم‌شده (خودکار)',
                                'type': 'auto_fix'
                            }
                        ]
                    })
        return discrepancies

    @staticmethod
    def resolve(app_id, action_key, choice_val=None, user=None):
        app = JobApplication.objects.filter(pk=app_id, is_deleted=False).first()
        if not app:
            return False, "درخواست مورد نظر یافت نشد."
        
        created_states = []
        job_stages = app.job.stages.filter(is_deleted=False)
        
        with transaction.atomic():
            # Create Audit Log metadata
            changes = {"action": "auto_create_missing_stages", "stages": []}
            for stage in job_stages:
                state, created = ApplicationStageState.objects.get_or_create(
                    application=app,
                    stage=stage,
                    defaults={'status': ApplicationStageState.STATUS_PENDING, 'score': 0.0}
                )
                if created:
                    changes["stages"].append(stage.name)
                    created_states.append(state)
            
            if created_states:
                # Log manually in AuditLog using utility to enable undo action (it records creation list)
                log = AuditLog(
                    user=user,
                    action_type=AuditLog.ACTION_CREATE,
                    model_name="applicationstagestate_bulk",
                    object_id=str(app.pk),
                    changes={"created_ids": [s.pk for s in created_states]},
                )
                log.save()
                return True, f"رکوردهای گم‌شده با موفقیت ایجاد شدند."
        
        return True, "تمامی مراحل از قبل وجود داشتند."


# 2. Status Sync Failed Check (Category: user, Auto-fixable)
class StatusSyncFailedCheck(BaseIntegrityCheck):
    code = "status_sync_failed"
    name = "نقص وضعیت در متقاضیان مردود"
    description = "متقاضیانی که در یکی از مراحل ارزیابی مردود شده‌اند اما وضعیت کلی درخواست همکاری آنان همچنان 'در حال بررسی' است."
    category = "user"
    is_auto_fixable = True

    def scan(self):
        discrepancies = []
        # Find applications marked IN_PROGRESS but having any non-conditional FAILED stage state
        failed_states = ApplicationStageState.objects.filter(
            status=ApplicationStageState.STATUS_FAILED,
            is_conditional_pass=False,
            is_deleted=False,
            application__status=JobApplication.STATUS_IN_PROGRESS,
            application__is_deleted=False
        ).select_related('application__candidate', 'application__job', 'stage')

        processed_apps = set()
        for state in failed_states:
            app = state.application
            if app.id in processed_apps:
                continue
            processed_apps.add(app.id)
            
            issue_id = f"sync_fail_{app.id}"
            discrepancies.append({
                'id': issue_id,
                'code': self.code,
                'entity_id': app.id,
                'candidate_name': f"{app.candidate.first_name} {app.candidate.last_name}",
                'national_id': app.candidate.national_id,
                'candidate_id': app.candidate.id,
                'job_title': app.job.title,
                'job_code': app.job.code,
                'job_id': app.job.id,
                'details': f"مردود شده در مرحله «{state.stage.name}» اما وضعیت کلی درخواست 'در حال بررسی' است.",
                'is_auto_fixable': self.is_auto_fixable,
                'actions': [
                    {
                        'key': 'reject_app',
                        'label': 'تغییر وضعیت کلی درخواست به «مردود شده»',
                        'type': 'auto_fix'
                    }
                ]
            })
        return discrepancies

    @staticmethod
    def resolve(app_id, action_key, choice_val=None, user=None):
        app = JobApplication.objects.filter(pk=app_id, is_deleted=False).first()
        if not app:
            return False, "درخواست مورد نظر یافت نشد."
        
        with transaction.atomic():
            old_status = app.status
            app.status = JobApplication.STATUS_REJECTED
            app.save(update_fields=['status'])
            # SoftDeleteModel logging will automatically log the status change.
            return True, f"وضعیت درخواست {app.candidate} به مردود شده تغییر یافت."


# 3. Grade Cutoff Contradiction (Category: import, Suggestion + Manual Approval)
class CutoffContradictionCheck(BaseIntegrityCheck):
    code = "cutoff_contradiction"
    name = "تناقض نمره و قبولی مرحله"
    description = "رکوردهایی که نمره متقاضی بالاتر از کف قبولی است ولی مردود ثبت شده، یا برعکس، نمره کمتر از کف قبولی ولی قبول ثبت شده است."
    category = "import"
    is_auto_fixable = False

    def scan(self):
        discrepancies = []
        states_qs = ApplicationStageState.objects.filter(
            is_deleted=False
        ).select_related('application__candidate', 'application__job', 'stage')

        for state in states_qs:
            if state.stage.stage_type == 'SCREENING':
                continue
            passing = state.stage.passing_score
            has_contradiction = False
            details = ""
            choices = []

            if state.status == ApplicationStageState.STATUS_COMPLETED and state.score < passing:
                has_contradiction = True
                details = f"مرحله قبول ثبت شده اما نمره ({state.score}) کمتر از حد نصاب قبولی ({passing}) است."
                choices = [
                    {'value': 'set_failed', 'label': "تغییر وضعیت ارزیابی مرحله به «مردود شده»"},
                    {'value': 'raise_score', 'label': f"افزایش نمره به حد نصاب قبولی ({passing})"}
                ]
            elif state.status == ApplicationStageState.STATUS_FAILED and not state.is_conditional_pass and state.score >= passing:
                has_contradiction = True
                details = f"مرحله مردود ثبت شده اما نمره ({state.score}) بزرگتر یا مساوی حد نصاب قبولی ({passing}) است."
                choices = [
                    {'value': 'set_completed', 'label': "تغییر وضعیت ارزیابی مرحله به «قبول شده»"},
                    {'value': 'lower_score', 'label': f"کاهش نمره به زیر حد نصاب قبولی (مثال: {passing - 1.0})"}
                ]

            if has_contradiction:
                issue_id = f"cutoff_{state.id}"
                discrepancies.append({
                    'id': issue_id,
                    'code': self.code,
                    'entity_id': state.id,
                    'candidate_name': f"{state.application.candidate.first_name} {state.application.candidate.last_name}",
                    'national_id': state.application.candidate.national_id,
                    'candidate_id': state.application.candidate.id,
                    'job_title': state.application.job.title,
                    'job_code': state.application.job.code,
                    'job_id': state.application.job.id,
                    'details': f"مرحله «{state.stage.name}»: {details}",
                    'is_auto_fixable': self.is_auto_fixable,
                    'actions': [
                        {
                            'key': 'resolve_cutoff',
                            'label': 'انتخاب نحوه رفع مغایرت',
                            'type': 'suggestion',
                            'choices': choices
                        }
                    ]
                })
        return discrepancies

    @staticmethod
    def resolve(state_id, action_key, choice_val=None, user=None):
        state = ApplicationStageState.objects.filter(pk=state_id, is_deleted=False).first()
        if not state:
            return False, "رکورد وضعیت مرحله یافت نشد."
        
        passing = state.stage.passing_score
        with transaction.atomic():
            state.evaluator = user
            state._bypass_stage_score_calculation = True  # Prevent interviewer reset override
            
            if choice_val == 'set_failed':
                state.status = ApplicationStageState.STATUS_FAILED
                state.save()
                return True, "وضعیت مرحله به «مردود شده» تغییر یافت."
            elif choice_val == 'raise_score':
                state.score = passing
                state.status = ApplicationStageState.STATUS_COMPLETED
                state.save()
                return True, f"نمره مرحله به {passing} افزایش یافت و وضعیت «قبول» شد."
            elif choice_val == 'set_completed':
                state.status = ApplicationStageState.STATUS_COMPLETED
                state.save()
                return True, "وضعیت مرحله به «قبول شده» تغییر یافت."
            elif choice_val == 'lower_score':
                state.score = max(0.0, passing - 1.0)
                state.status = ApplicationStageState.STATUS_FAILED
                state.save()
                return True, f"نمره مرحله به {max(0.0, passing - 1.0)} کاهش یافت و وضعیت «مردود» شد."
                
        return False, "گزینه نامعتبر انتخاب شده است."


# 4. Interviewer Score Variance Check (Category: user, Suggestion + Manual Approval)
class InterviewerScoreVarianceCheck(BaseIntegrityCheck):
    code = "score_variance"
    name = "مغایرت فاحش نمرات ارزیابان"
    description = "رکوردهای ارزیابی که اختلاف نمره ارزیابان مختلف برای متقاضی بیش از ۲۰ نمره است و نیاز به بازبینی دارد."
    category = "user"
    is_auto_fixable = False

    def scan(self):
        discrepancies = []
        states_qs = ApplicationStageState.objects.filter(
            score_discrepancy_alert=True,
            is_deleted=False
        ).select_related('application__candidate', 'application__job', 'stage')

        for state in states_qs:
            issue_id = f"variance_{state.id}"
            discrepancies.append({
                'id': issue_id,
                'code': self.code,
                'entity_id': state.id,
                'candidate_name': f"{state.application.candidate.first_name} {state.application.candidate.last_name}",
                'national_id': state.application.candidate.national_id,
                'candidate_id': state.application.candidate.id,
                'job_title': state.application.job.title,
                'job_code': state.application.job.code,
                'job_id': state.application.job.id,
                'details': f"مرحله «{state.stage.name}»: اختلاف نمرات ارزیابان فاحش است (بیش از ۲۰ امتیاز).",
                'is_auto_fixable': self.is_auto_fixable,
                'actions': [
                    {
                        'key': 'resolve_variance',
                        'label': 'اقدام برای رفع هشدار',
                        'type': 'suggestion',
                        'choices': [
                            {'value': 'clear_alert', 'label': "نادیده گرفتن و رفع هشدار اختلاف نمرات"},
                        ]
                    }
                ]
            })
        return discrepancies

    @staticmethod
    def resolve(state_id, action_key, choice_val=None, user=None):
        state = ApplicationStageState.objects.filter(pk=state_id, is_deleted=False).first()
        if not state:
            return False, "رکورد وضعیت مرحله یافت نشد."
        
        if choice_val == 'clear_alert':
            with transaction.atomic():
                state.score_discrepancy_alert = False
                state._bypass_stage_score_calculation = True
                state.save(update_fields=['score_discrepancy_alert'])
                return True, "هشدار اختلاف نمرات برطرف شد."
        return False, "گزینه نامعتبر انتخاب شده است."


# 5. Logical Date Anomaly Check (Category: import, Flag Only)
class LogicalDateAnomalyCheck(BaseIntegrityCheck):
    code = "date_anomaly"
    name = "تناقض در تاریخ مراحل استخدام"
    description = "رکوردهای ارزیابی که تاریخ ثبت ارزیابی آن‌ها از تاریخ مراحل قبلی همان متقاضی عقب‌تر است."
    category = "import"
    is_auto_fixable = False  # Flag only

    def scan(self):
        discrepancies = []
        states_qs = ApplicationStageState.objects.filter(
            evaluation_date__isnull=False,
            is_deleted=False
        ).select_related('application__candidate', 'application__job', 'stage')

        for state in states_qs:
            # Check for prior stage states with evaluation_date > state.evaluation_date
            prior_anomaly = state.application.stage_states.filter(
                stage__sequence__lt=state.stage.sequence,
                evaluation_date__gt=state.evaluation_date,
                is_deleted=False
            ).select_related('stage').first()

            if prior_anomaly:
                issue_id = f"date_{state.id}"
                discrepancies.append({
                    'id': issue_id,
                    'code': self.code,
                    'entity_id': state.id,
                    'candidate_name': f"{state.application.candidate.first_name} {state.application.candidate.last_name}",
                    'national_id': state.application.candidate.national_id,
                    'candidate_id': state.application.candidate.id,
                    'job_title': state.application.job.title,
                    'job_code': state.application.job.code,
                    'job_id': state.application.job.id,
                    'details': f"تاریخ مرحله «{state.stage.name}» ({state.evaluation_date}) از تاریخ مرحله قبلی «{prior_anomaly.stage.name}» ({prior_anomaly.evaluation_date}) عقب‌تر است.",
                    'is_auto_fixable': self.is_auto_fixable,
                    'actions': [
                        {
                            'key': 'flag_only',
                            'label': 'فقط به عنوان هشدار (نیاز به تصحیح دستی تاریخ)',
                            'type': 'flag'
                        }
                    ]
                })
        return discrepancies

    @staticmethod
    def resolve(state_id, action_key, choice_val=None, user=None):
        return False, "تناقض تاریخ فاقد راهکار خودکار است و باید به صورت دستی تصحیح گردد."


# 6. Status Sync Completed Check (Category: user, Suggestion + Manual Approval)
class StatusSyncCompletedCheck(BaseIntegrityCheck):
    code = "status_sync_completed"
    name = "نقص وضعیت در متقاضیان قبول شده"
    description = "متقاضیانی که تمامی مراحل استخدام را با موفقیت پشت سر گذاشته‌اند اما وضعیت کلی درخواست آنها همچنان 'در حال بررسی' است."
    category = "user"
    is_auto_fixable = False

    def scan(self):
        discrepancies = []
        apps_qs = JobApplication.objects.filter(
            is_deleted=False,
            status=JobApplication.STATUS_IN_PROGRESS
        ).select_related('candidate', 'job')

        for app in apps_qs:
            stages_list = list(app.job.stages.filter(is_deleted=False))
            if not stages_list:
                continue
                
            states = list(app.stage_states.filter(is_deleted=False))
            if len(states) == len(stages_list):
                all_passed = all(
                    state.status == ApplicationStageState.STATUS_COMPLETED or state.is_conditional_pass
                    for state in states
                )
                if all_passed:
                    issue_id = f"sync_complete_{app.id}"
                    discrepancies.append({
                        'id': issue_id,
                        'code': self.code,
                        'entity_id': app.id,
                        'candidate_name': f"{app.candidate.first_name} {app.candidate.last_name}",
                        'national_id': app.candidate.national_id,
                        'candidate_id': app.candidate.id,
                        'job_title': app.job.title,
                        'job_code': app.job.code,
                        'job_id': app.job.id,
                        'details': "تمامی مراحل ارزیابی را با قبولی گذرانده اما وضعیت درخواست 'در حال بررسی' باقی مانده است.",
                        'is_auto_fixable': self.is_auto_fixable,
                        'actions': [
                            {
                                'key': 'resolve_completed',
                                'label': 'تغییر وضعیت کلی متقاضی',
                                'type': 'suggestion',
                                'choices': [
                                    {'value': 'set_selected', 'label': "پذیرش نهایی (قبول نهایی)"},
                                    {'value': 'set_reserve', 'label': "قرار دادن در لیست ذخیره"}
                                ]
                            }
                        ]
                    })
        return discrepancies

    @staticmethod
    def resolve(app_id, action_key, choice_val=None, user=None):
        app = JobApplication.objects.filter(pk=app_id, is_deleted=False).first()
        if not app:
            return False, "درخواست مورد نظر یافت نشد."
        
        with transaction.atomic():
            if choice_val == 'set_selected':
                app.status = JobApplication.STATUS_SELECTED
                app.save(update_fields=['status'])
                app.job.update_status()
                return True, "وضعیت درخواست متقاضی به «قبول نهایی» تغییر کرد."
            elif choice_val == 'set_reserve':
                app.status = JobApplication.STATUS_RESERVE
                app.save(update_fields=['status'])
                app.job.update_status()
                return True, "وضعیت درخواست متقاضی به «ذخیره» تغییر کرد."
        return False, "گزینه نامعتبر انتخاب شده است."


# 7. Completed Stage Without Date Check (Category: import, Flag Only)
class CompletedStageWithoutDateCheck(BaseIntegrityCheck):
    code = "completed_no_date"
    name = "مراحل ارزیابی تکمیل‌شده بدون تاریخ"
    description = "رکوردهای ارزیابی که وضعیت آن‌ها قبول یا مردود ثبت شده است ولی فاقد تاریخ ارزیابی هستند."
    category = "import"
    is_auto_fixable = False

    def scan(self):
        discrepancies = []
        states_qs = ApplicationStageState.objects.filter(
            status__in=[ApplicationStageState.STATUS_COMPLETED, ApplicationStageState.STATUS_FAILED],
            evaluation_date__isnull=True,
            is_deleted=False
        ).select_related('application__candidate', 'application__job', 'stage')

        for state in states_qs:
            issue_id = f"no_date_{state.id}"
            discrepancies.append({
                'id': issue_id,
                'code': self.code,
                'entity_id': state.id,
                'candidate_name': f"{state.application.candidate.first_name} {state.application.candidate.last_name}",
                'national_id': state.application.candidate.national_id,
                'candidate_id': state.application.candidate.id,
                'job_title': state.application.job.title,
                'job_code': state.application.job.code,
                'job_id': state.application.job.id,
                'details': f"مرحلۀ «{state.stage.name}» تکمیل شده (وضعیت: {state.get_status_display()}) اما فاقد تاریخ ارزیابی است.",
                'is_auto_fixable': self.is_auto_fixable,
                'actions': [
                    {
                        'key': 'flag_only',
                        'label': 'نیاز به ثبت دستی تاریخ در پایپلاین یا ویرایش سلول',
                        'type': 'flag'
                    }
                ]
            })
        return discrepancies

    @staticmethod
    def resolve(state_id, action_key, choice_val=None, user=None):
        return False, "این مغایرت باید با ثبت دستی تاریخ ارزیابی برطرف گردد."


# 8. Stage Completed Without Plan Date Check (Category: import, Flag Only)
class StageCompletedWithoutPlanDateCheck(BaseIntegrityCheck):
    code = "stage_completed_no_date"
    name = "مراحل تکمیل‌شده بدون برنامه زمان‌بندی"
    description = "مراحل ارزیابی فرصت‌های شغلی که تکمیل شده‌اند اما فاقد برنامه زمان‌بندی (تاریخ شروع و پایان) در پایپلاین هستند."
    category = "import"
    is_auto_fixable = False

    def scan(self):
        discrepancies = []
        stages = JobOpportunityStage.objects.filter(
            is_deleted=False,
            job__is_deleted=False
        ).select_related('job')
        
        for stage in stages:
            if stage.is_completed:
                from apps.recruitment_planning.models import JobStagePlan
                stage_plan = JobStagePlan.objects.filter(
                    plan__job=stage.job,
                    stage=stage,
                    is_deleted=False
                ).first()
                
                if not stage_plan or not stage_plan.planned_end_date or not stage_plan.planned_start_date:
                    issue_id = f"stage_no_date_{stage.id}"
                    discrepancies.append({
                        'id': issue_id,
                        'code': self.code,
                        'entity_id': stage.id,
                        'candidate_name': None,
                        'national_id': None,
                        'candidate_id': None,
                        'job_title': stage.job.title,
                        'job_code': stage.job.code,
                        'job_id': stage.job.id,
                        'details': f"مرحله «{stage.name}» تکمیل شده است اما فاقد برنامه زمان‌بندی (تاریخ شروع/پایان) در پایپلاین است.",
                        'is_auto_fixable': self.is_auto_fixable,
                        'actions': [
                            {
                                'key': 'flag_only',
                                'label': 'نیاز به ثبت تاریخ برای این مرحله در پایپلاین',
                                'type': 'flag'
                            }
                        ]
                    })
        return discrepancies

    @staticmethod
    def resolve(stage_id, action_key, choice_val=None, user=None):
        return False, "این مغایرت باید با ثبت تاریخ ارزیابی مرحله در بالای پایپلاین برطرف گردد."


# Integrity Scanner Manager
class IntegrityScanner:
    _checks = [
        MissingStageStatesCheck(),
        StatusSyncFailedCheck(),
        CutoffContradictionCheck(),
        InterviewerScoreVarianceCheck(),
        LogicalDateAnomalyCheck(),
        StatusSyncCompletedCheck(),
        CompletedStageWithoutDateCheck(),
        StageCompletedWithoutPlanDateCheck()
    ]

    @classmethod
    def get_scanner_classes(cls):
        return {check.code: check for check in cls._checks}

    @classmethod
    def run_scan(cls, force=False):
        cache_key = "data_integrity_scan_cache"
        if not force:
            cached_data = cache.get(cache_key)
            if cached_data is not None:
                return cached_data

        results = {
            'import_issues': [],
            'user_issues': [],
            'total_count': 0,
            'clean_percentage': 100
        }

        # Run all scanners
        for check in cls._checks:
            issue_list = check.scan()
            if check.category == 'import':
                results['import_issues'].extend(issue_list)
            else:
                results['user_issues'].extend(issue_list)

        total_issues = len(results['import_issues']) + len(results['user_issues'])
        results['total_count'] = total_issues
        
        # Calculate clean percentage estimate
        total_candidates = JobApplication.objects.filter(is_deleted=False).count() or 1
        results['clean_percentage'] = max(0, min(100, int((1 - (total_issues / (total_candidates * 6))) * 100)))

        # Cache results for 10 minutes
        cache.set(cache_key, results, 600)
        return results

    @classmethod
    def resolve_issue(cls, issue_code, entity_id, action_key, choice_val=None, user=None):
        scanners = cls.get_scanner_classes()
        scanner = scanners.get(issue_code)
        if not scanner:
            return False, "نوع مغایرت نامعتبر است."

        success, msg = scanner.resolve(entity_id, action_key, choice_val, user)
        if success:
            # Force cache invalidation to ensure clean updates
            cls.run_scan(force=True)
        return success, msg


# Generic Undo Audit Log Action Helper
def undo_audit_log_action(log_id):
    log = AuditLog.objects.filter(pk=log_id).first()
    if not log:
        return False, "لاگ حسابرسی با شناسه مشخص شده یافت نشد."

    try:
        with transaction.atomic():
            # Special case for bulk stage creations
            if log.model_name == "applicationstagestate_bulk":
                created_ids = log.changes.get("created_ids", [])
                deleted_count = ApplicationStageState.objects.filter(pk__in=created_ids).hard_delete()
                
                # Delete the audit log entry inside the transaction
                AuditLog.objects.filter(pk=log_id).delete()
                # Refresh cache
                IntegrityScanner.run_scan(force=True)
                return True, f"لغو شد: تعداد {deleted_count[0] if deleted_count else 0} مرحله استخدام اضافه شده حذف گردیدند."

            # Find target model
            model = None
            for app_config in apps.get_app_configs():
                if log.model_name in app_config.models:
                    model = app_config.get_model(log.model_name)
                    break
            
            if not model:
                return False, f"مدل داده '{log.model_name}' در سیستم یافت نشد."

            manager = getattr(model, 'all_objects', model.objects)
            instance = manager.filter(pk=log.object_id).first()
            if not instance:
                return False, "رکورد داده برای لغو عملیات یافت نشد."

            if log.action_type == AuditLog.ACTION_CREATE:
                # To undo creation, we hard delete the instance
                instance.hard_delete()
                AuditLog.objects.filter(pk=log_id).delete()
                IntegrityScanner.run_scan(force=True)
                return True, "عملیات ایجاد با موفقیت بازگردانده و حذف شد."

            elif log.action_type == AuditLog.ACTION_DELETE:
                # To undo deletion, restore it
                instance.is_deleted = False
                instance.deleted_at = None
                instance.save()
                AuditLog.objects.filter(pk=log_id).delete()
                IntegrityScanner.run_scan(force=True)
                return True, "رکورد حذف شده با موفقیت بازیابی شد."

            elif log.action_type in [AuditLog.ACTION_UPDATE, AuditLog.ACTION_SCORE_CHANGE, AuditLog.ACTION_STATUS_CHANGE]:
                # Revert change logs
                for field_name, delta in log.changes.items():
                    if isinstance(delta, dict) and 'old' in delta:
                        old_val = delta['old']
                        if old_val == 'None' or old_val is None:
                            old_val = None
                        elif old_val == 'True':
                            old_val = True
                        elif old_val == 'False':
                            old_val = False
                        
                        field = instance._meta.get_field(field_name)
                        if old_val is not None:
                            if isinstance(field, (models.IntegerField, models.PositiveIntegerField)):
                                old_val = int(old_val)
                            elif isinstance(field, (models.FloatField, models.DecimalField)):
                                old_val = float(old_val)
                            elif isinstance(field, models.BooleanField):
                                old_val = old_val in [True, 'True', '1', 1]
                                
                        setattr(instance, field_name, old_val)
                
                # Use bypass flag to avoid model triggers overwriting scores
                if hasattr(instance, '_bypass_stage_score_calculation'):
                    instance._bypass_stage_score_calculation = True
                
                instance.save()
                AuditLog.objects.filter(pk=log_id).delete()
                IntegrityScanner.run_scan(force=True)
                return True, "تغییرات با موفقیت به مقادیر اولیه بازگردانده شدند."
                
    except Exception as e:
        return False, f"لغو عملیات با خطا مواجه شد: {str(e)}"
    return False, "عملیات لغو پشتیبانی نمی‌شود."
