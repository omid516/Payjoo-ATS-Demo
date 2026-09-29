import logging
from django.utils import timezone
from django.template.loader import render_to_string
from django.db.models import Q
from apps.jobs.models import JobOpportunity, JobOpportunityStage, OrganizationSetting, AreaCoordinator
from apps.candidates.models import JobApplication, ApplicationStageState
from apps.candidates.signals import send_dynamic_email

logger = logging.getLogger(__name__)

def get_distinct_departments():
    """
    دریافت فهرست یکتا از تمامی دپارتمان‌ها و نواحی ثبت‌شده در فرصت‌های شغلی و هماهنگ‌کنندگان
    """
    job_deps = set(
        d.strip() for d in JobOpportunity.objects.filter(is_deleted=False).values_list('department', flat=True)
        if d and d.strip()
    )
    for c in AreaCoordinator.objects.filter(is_deleted=False):
        if isinstance(c.departments, list):
            for d in c.departments:
                if d and d.strip():
                    job_deps.add(d.strip())
    return sorted(list(job_deps))


def get_coordinator_jobs(coordinator, specific_job_id=None):
    """
    دریافت فرصت‌های شغلی فعال مربوط به نواحی تحت پوشش یک هماهنگ‌کننده
    """
    if not coordinator or not coordinator.departments:
        return JobOpportunity.objects.none()
    
    qs = JobOpportunity.objects.filter(
        is_deleted=False,
        department__in=coordinator.departments
    ).exclude(status__in=[JobOpportunity.STATUS_CANCELLED])
    
    if specific_job_id:
        qs = qs.filter(pk=specific_job_id)
        
    return qs.order_by('-created_at')


def build_job_report_summary(job):
    """
    استخراج ساختاریافته خلاصه وضعیت یک اعلان شغلی، مراحل، و برگزیدگان مرحله جاری
    """
    stages = list(job.stages.filter(is_deleted=False).order_by('sequence'))
    applications = list(job.applications.filter(is_deleted=False).select_related('candidate').prefetch_related('stage_states__stage'))
    total_candidates = len(applications)
    
    # تعیین مرحله جاری فرصت شغلی
    current_stage = job.current_stage
    if not current_stage and stages:
        current_stage = stages[0]

    # ساخت اطلاعات نوار پیشرفت مراحل
    stages_progress = []
    curr_seq = current_stage.sequence if current_stage else 1
    for st in stages:
        st_states = ApplicationStageState.objects.filter(application__job=job, stage=st, is_deleted=False)
        passed_cnt = st_states.filter(status=ApplicationStageState.STATUS_COMPLETED).count()
        failed_cnt = st_states.filter(status=ApplicationStageState.STATUS_FAILED).count()
        absent_cnt = st_states.filter(status=ApplicationStageState.STATUS_ABSENT).count()
        pending_cnt = st_states.filter(status=ApplicationStageState.STATUS_PENDING).count()
        
        is_completed = (st.sequence < curr_seq) or (pending_cnt == 0 and (passed_cnt + failed_cnt + absent_cnt) > 0 and st.sequence <= curr_seq)
        is_current = (current_stage and st.id == current_stage.id)
        
        stages_progress.append({
            'stage': st,
            'name': st.name,
            'sequence': st.sequence,
            'weight': st.weight,
            'is_current': is_current,
            'is_completed': is_completed,
            'passed_count': passed_cnt,
            'failed_count': failed_cnt,
            'pending_count': pending_cnt,
        })

    # استخراج داوطلبان برگزیده / راه‌یافته به این مرحله
    # کسانی که در مراحل قبلی رد یا غایب نشده‌اند
    shortlisted_candidates = []
    # داوطلبانی که وضعیت فعال دارند (SELECTED یا IN_PROGRESS یا RESERVE)
    active_apps = [app for app in applications if app.effective_status in ['IN_PROGRESS', 'SELECTED', 'RESERVE']]
    
    # اولویت مرتب‌سازی: قبولی نهایی، سپس نمره کل، سپس شناسه
    active_apps.sort(key=lambda a: (0 if a.status == 'SELECTED' else 1, -a.final_score, -a.id))
    
    for idx, app in enumerate(active_apps, start=1):
        st_state = None
        if current_stage:
            for s in app.stage_states.all():
                if s.stage_id == current_stage.id and not s.is_deleted:
                    st_state = s
                    break
                    
        st_status_display = "در انتظار ارزیابی"
        score = 0.0
        if st_state:
            st_status_display = st_state.get_status_display()
            score = st_state.score
        elif app.status == 'SELECTED':
            st_status_display = "پذیرفته‌شده نهایی"
            score = app.final_score

        shortlisted_candidates.append({
            'row_num': idx,
            'candidate_id': app.candidate.id,
            'name': f"{app.candidate.first_name} {app.candidate.last_name}",
            'national_id': app.candidate.national_id,
            'personnel_number': app.candidate.personnel_number or "-",
            'score': score,
            'final_score': app.final_score,
            'stage_status': st_status_display,
            'overall_status': app.get_status_display(),
            'is_selected': app.status == 'SELECTED',
        })

    return {
        'job': job,
        'title': job.title,
        'code': job.code,
        'request_number': job.request_number,
        'department': job.department,
        'unit': job.unit,
        'headcount': job.headcount,
        'status_display': job.get_status_display(),
        'current_stage': current_stage,
        'stages_progress': stages_progress,
        'total_candidates': total_candidates,
        'shortlisted_candidates': shortlisted_candidates,
        'shortlisted_count': len(shortlisted_candidates),
    }


def send_area_coordinator_email_report(coordinator, jobs=None, request=None):
    """
    تولید و ارسال گزارش جامع وضعیت اعلان‌های شغلی برای هماهنگ‌کننده یک ناحیه
    """
    if not coordinator or not coordinator.email:
        return False, "هماهنگ‌کننده فاقد آدرس پست الکترونیک (ایمیل) است.", 0

    if jobs is None:
        jobs_qs = get_coordinator_jobs(coordinator)
    else:
        jobs_qs = jobs

    jobs_list = list(jobs_qs)
    if not jobs_list:
        return False, f"هیچ اعلان شغلی فعالی برای نواحی تحت پوشش «{coordinator.name}» یافت نشد.", 0

    html_content, subject, context, jobs_data = generate_coordinator_report_payload(coordinator, jobs_qs=jobs_list)
    org_setting = OrganizationSetting.get_active_setting()

    try:
        success, msg = send_dynamic_email(org_setting, coordinator.email, subject, html_content, fail_silently=True)
        if not success:
            logger.error(f"Failed to send email to coordinator {coordinator.email}: {msg}")
            return False, f"خطا در ارسال ایمیل به {coordinator.name}: {msg}", len(jobs_data)
        return True, f"گزارش وضعیت {len(jobs_data)} اعلان شغلی با موفقیت به ایمیل {coordinator.email} ارسال شد.", len(jobs_data)
    except Exception as e:
        logger.error(f"Error sending email to coordinator {coordinator.email}: {e}")
        return False, f"خطا در ارسال ایمیل: {str(e)}", len(jobs_data)


def generate_coordinator_report_payload(coordinator, jobs_qs=None):
    """
    تولید محتوا، عنوان و بافت گزارش هماهنگ‌کننده جهت ارسال یا پیش‌نمایش در سامانه
    """
    if jobs_qs is None:
        jobs_qs = get_coordinator_jobs(coordinator)
        
    jobs_list = list(jobs_qs)
    org_setting = OrganizationSetting.get_active_setting()
    
    jobs_data = []
    for job in jobs_list:
        summary = build_job_report_summary(job)
        jobs_data.append(summary)

    import jdatetime
    now_jalali = jdatetime.datetime.now().strftime('%Y/%m/%d - %H:%M')

    departments_str = "، ".join(coordinator.departments) if (coordinator and coordinator.departments) else "کلیه نواحی"

    context = {
        'coordinator': coordinator,
        'departments_str': departments_str,
        'jobs_data': jobs_data,
        'total_jobs': len(jobs_data),
        'report_date': now_jalali,
        'company_name': org_setting.name if org_setting else "شرکت فولاد مبارکه اصفهان",
    }

    dep_text = departments_str if departments_str.startswith("ناحیه") else f"ناحیه {departments_str}"
    subject = f"گزارش وضعیت اعلان‌های شغلی {dep_text} — {jdatetime.date.today().strftime('%Y/%m/%d')}"
    
    html_content = render_to_string('emails/area_coordinator_report.html', context)
    return html_content, subject, context, jobs_data


def test_smtp_connection(org_setting, recipient_email, custom_params=None):
    """
    تست اتصال و ارسال ایمیل آزمایشی با تنظیمات SMTP سازمان
    """
    if not recipient_email:
        return False, "آدرس ایمیل گیرنده آزمایشی الزامی است."

    import copy
    from .models import OrganizationSetting
    target_setting = copy.copy(org_setting) if org_setting else None
    
    if custom_params:
        if not target_setting:
            target_setting = OrganizationSetting()
        if custom_params.get('email_provider'):
            target_setting.email_provider = custom_params['email_provider']
        if custom_params.get('smtp_host') is not None:
            target_setting.smtp_host = custom_params['smtp_host'].strip()
        if custom_params.get('smtp_port'):
            try:
                target_setting.smtp_port = int(custom_params['smtp_port'])
            except (ValueError, TypeError):
                pass
        if custom_params.get('smtp_user') is not None:
            target_setting.smtp_user = custom_params['smtp_user'].strip()
        if custom_params.get('smtp_password'):
            target_setting.smtp_password = custom_params['smtp_password']
        if custom_params.get('smtp_sender_email') is not None:
            target_setting.smtp_sender_email = custom_params['smtp_sender_email'].strip()
        if 'smtp_use_tls' in custom_params and custom_params['smtp_use_tls'] is not None:
            target_setting.smtp_use_tls = bool(custom_params['smtp_use_tls'])
        if 'smtp_use_ssl' in custom_params and custom_params['smtp_use_ssl'] is not None:
            target_setting.smtp_use_ssl = bool(custom_params['smtp_use_ssl'])

    import jdatetime
    now_str = jdatetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S')
    provider_val = getattr(target_setting, 'email_provider', 'CUSTOM') if target_setting else 'CUSTOM'
    provider_choices = dict(OrganizationSetting.EMAIL_PROVIDER_CHOICES)
    provider_name = provider_choices.get(provider_val, provider_val)
    
    subject = f"✅ تست اتصال موفق سامانه پیجو به سرور ایمیل ({provider_name})"
    html_content = f"""
    <div dir="rtl" style="font-family: Tahoma, Arial, sans-serif; text-align: right; padding: 25px; line-height: 1.8; color: #1e293b; background-color: #f8fafc; border-radius: 12px; border: 1px solid #e2e8f0; max-width: 600px; margin: auto;">
        <h2 style="color: #059669; border-bottom: 2px solid #10b981; padding-bottom: 10px; margin-top: 0;">🎉 تست ارسال ایمیل موفقیت‌آمیز بود</h2>
        <p>با سلام و احترام؛</p>
        <p>این پیام به منظور تأیید صحت تنظیمات سرور پست الکترونیک (SMTP) در سامانه جذب و استخدام <strong>{getattr(target_setting, 'name', '') or 'پیجو'}</strong> برای شما ارسال گردیده است.</p>
        
        <div style="background-color: #ffffff; padding: 15px; border-radius: 8px; border-right: 4px solid #059669; margin: 20px 0;">
            <strong>مشخصات اتصال:</strong>
            <ul style="margin: 10px 0 0 0; padding-right: 20px;">
                <li><strong>سرویس‌دهنده:</strong> {provider_name}</li>
                <li><strong>سرور SMTP:</strong> {getattr(target_setting, 'smtp_host', '') or 'پیش‌فرض'}</li>
                <li><strong>پورت:</strong> {getattr(target_setting, 'smtp_port', '')}</li>
                <li><strong>ایمیل فرستنده:</strong> {getattr(target_setting, 'smtp_sender_email', '') or getattr(target_setting, 'smtp_user', '')}</li>
                <li><strong>زمان ارسال:</strong> {now_str}</li>
            </ul>
        </div>
        
        <p style="color: #64748b; font-size: 13px;">از این پس اعلان‌های شغلی و کارنامه‌های ارزیابی به طور خودکار از طریق این درگاه برای هماهنگ‌کنندگان نواحی و متقاضیان ارسال خواهد شد.</p>
        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;"/>
        <small style="color: #94a3b8;">سامانه جذب و استخدام پیجو (Payjoo ATS) — فولاد مبارکه</small>
    </div>
    """
    
    try:
        success, msg = send_dynamic_email(target_setting, recipient_email, subject, html_content, fail_silently=True)
        if not success:
            return False, f"خطا در ارسال ایمیل آزمایشی: {msg}"
        return True, f"ایمیل آزمایشی با موفقیت به {recipient_email} ارسال شد."
    except Exception as e:
        return False, f"خطا در ارسال ایمیل آزمایشی: {str(e)}"
