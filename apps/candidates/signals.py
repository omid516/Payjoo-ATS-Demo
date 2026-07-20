from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags
from django.urls import reverse
from django.conf import settings
import os

from apps.candidates.models import JobApplication, ApplicationStageState, NotificationLog
from apps.jobs.models import OrganizationSetting

# دایرکتوری و فایل لاگ اعلانات ارسالی
LOGS_DIR = os.path.join(settings.BASE_DIR, 'logs')
LOG_FILE_PATH = os.path.join(LOGS_DIR, 'notifications.log')

def log_notification(channel, recipient, subject, body):
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR, exist_ok=True)
    import jdatetime
    now_str = jdatetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S')
    log_content = (
        f"==================================================\n"
        f"TIME: {now_str}\n"
        f"CHANNEL: {channel}\n"
        f"RECIPIENT: {recipient}\n"
        f"SUBJECT/TYPE: {subject}\n"
        f"CONTENT:\n{body}\n"
        f"==================================================\n\n"
    )
    with open(LOG_FILE_PATH, 'a', encoding='utf-8') as f:
        f.write(log_content)

def send_dynamic_email(org_setting, to_email, subject, html_content):
    if not to_email:
        return
    text_content = strip_tags(html_content)
    
    # در صورت وجود تنظیمات SMTP در مدل تنظیمات سازمان، از آن استفاده پویا می‌کنیم
    if org_setting:
        from django.core.mail import get_connection
        email_provider = getattr(org_setting, 'email_provider', 'CUSTOM')
        
        # مقداردهی تنظیمات بر اساس سرویس‌دهنده انتخابی
        if email_provider == 'GMAIL':
            host = 'smtp.gmail.com'
            port = 587
            use_tls = True
            use_ssl = False
        elif email_provider == 'OUTLOOK':
            host = 'smtp-mail.outlook.com'
            port = 587
            use_tls = True
            use_ssl = False
        else:  # CUSTOM
            host = org_setting.smtp_host
            port = org_setting.smtp_port
            use_tls = org_setting.smtp_use_tls
            use_ssl = org_setting.smtp_use_ssl
            
        if host:
            try:
                connection = get_connection(
                    backend='django.core.mail.backends.smtp.EmailBackend',
                    host=host,
                    port=port,
                    username=org_setting.smtp_user,
                    password=org_setting.smtp_password,
                    use_tls=use_tls,
                    use_ssl=use_ssl,
                )
                from_email = org_setting.smtp_sender_email or getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@payjoo.ir')
                msg = EmailMultiAlternatives(
                    subject,
                    text_content,
                    from_email,
                    [to_email],
                    connection=connection
                )
                msg.attach_alternative(html_content, "text/html")
                msg.send(fail_silently=False)
                
                # ثبت موفقیت در دیتابیس
                NotificationLog.objects.create(
                    notification_type='EMAIL',
                    recipient=to_email,
                    subject=subject,
                    body=text_content,
                    status='SENT'
                )
                return
            except Exception as e:
                err_msg = str(e)
                print(f"SMTP sending failed ({email_provider}): {err_msg}. Falling back to default mail settings.")
                NotificationLog.objects.create(
                    notification_type='EMAIL',
                    recipient=to_email,
                    subject=subject,
                    body=text_content,
                    status='FAILED',
                    error_message=f"SMTP Gateway Error ({email_provider}): {err_msg}"
                )
            
    # استفاده از بک‌اند پیش‌فرض پروژه جنگو
    try:
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@payjoo.ir')
        msg = EmailMultiAlternatives(subject, text_content, from_email, [to_email])
        msg.attach_alternative(html_content, "text/html")
        msg.send(fail_silently=False)
        
        NotificationLog.objects.create(
            notification_type='EMAIL',
            recipient=to_email,
            subject=subject,
            body=text_content,
            status='SENT'
        )
    except Exception as e:
        err_msg = str(e)
        print(f"Fallback email sending failed: {err_msg}")
        NotificationLog.objects.create(
            notification_type='EMAIL',
            recipient=to_email,
            subject=subject,
            body=text_content,
            status='FAILED',
            error_message=f"Fallback System Error: {err_msg}"
        )

def send_kavenegar_sms(api_key, receptor, sender, message):
    import urllib.request
    import urllib.parse
    import json
    
    url = f"https://api.kavenegar.com/v1/{api_key}/sms/send.json"
    data = urllib.parse.urlencode({
        'receptor': receptor,
        'sender': sender,
        'message': message
    }).encode('utf-8')
    
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as response:
            res = response.read().decode('utf-8')
            res_json = json.loads(res)
            return res_json
    except Exception as e:
        print(f"Kavenegar API call failed: {e}")
        return None

def send_gateway_sms(org_setting, phone_number, message):
    provider = org_setting.sms_provider
    api_key = org_setting.sms_api_key
    sender = org_setting.sms_sender_number
    
    # برای سایر پیام‌رسان‌ها / شبیه‌سازها در صورتی که API Key تعریف نشده باشد باز هم لاگ می‌کنیم
    if not api_key and provider not in ['MOCK', 'OTHER']:
        NotificationLog.objects.create(
            notification_type='SMS',
            recipient=phone_number,
            subject=f'پیامک ({provider})',
            body=message,
            status='FAILED',
            error_message="API Key values are not set in organization settings."
        )
        return
        
    if provider == 'KAVENEGAR':
        res = send_kavenegar_sms(api_key, phone_number, sender, message)
        if res:
            NotificationLog.objects.create(
                notification_type='SMS',
                recipient=phone_number,
                subject='پیامک پنل کاوه نگار',
                body=message,
                status='SENT'
            )
        else:
            NotificationLog.objects.create(
                notification_type='SMS',
                recipient=phone_number,
                subject='پیامک پنل کاوه نگار',
                body=message,
                status='FAILED',
                error_message="Kavenegar REST API request failed."
            )
    elif provider in ['MELIPAYAMAK', 'FARAPAYAMAK']:
        import urllib.request
        import urllib.parse
        
        # ساختار فیلد کلید پیامک: username:password
        username = api_key
        password = ""
        if api_key and ":" in api_key:
            username, password = api_key.split(":", 1)
            
        # ملی پیامک و فراپیامک هر دو از وب‌سرویس rest.payamak-panel.com استفاده می‌کنند
        url = "https://rest.payamak-panel.com/api/SendSMS/SendSMS"
        data = urllib.parse.urlencode({
            'username': username,
            'password': password,
            'to': phone_number,
            'from': sender,
            'text': message,
            'isflash': 'false'
        }).encode('utf-8')
        
        try:
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=10) as response:
                pass
            NotificationLog.objects.create(
                notification_type='SMS',
                recipient=phone_number,
                subject=f'پیامک پنل {provider}',
                body=message,
                status='SENT'
            )
        except Exception as e:
            err_msg = str(e)
            print(f"{provider} API call failed: {err_msg}")
            NotificationLog.objects.create(
                notification_type='SMS',
                recipient=phone_number,
                subject=f'پیامک پنل {provider}',
                body=message,
                status='FAILED',
                error_message=err_msg
            )
            
    elif provider == 'CUSTOM' and getattr(org_setting, 'sms_custom_url', None):
        import urllib.request
        import urllib.parse
        import json
        
        url = org_setting.sms_custom_url
        data_dict = {
            'to': phone_number,
            'receptor': phone_number,
            'phone': phone_number,
            'from': sender,
            'sender': sender,
            'message': message,
            'text': message,
            'body': message,
            'api_key': api_key,
            'token': api_key
        }
        
        # تلاش برای ارسال به صورت JSON
        sent = False
        errs = []
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(data_dict).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                pass
            sent = True
        except Exception as e_json:
            errs.append(f"JSON: {e_json}")
            # در صورت ناموفق بودن به عنوان فرم urlencoded تلاش می‌کنیم
            try:
                data_encoded = urllib.parse.urlencode(data_dict).encode('utf-8')
                req = urllib.request.Request(url, data=data_encoded)
                with urllib.request.urlopen(req, timeout=10) as response:
                    pass
                sent = True
            except Exception as e_form:
                errs.append(f"Form: {e_form}")
                print(f"Custom SMS Gateway call failed: JSON error: {e_json}, Form error: {e_form}")
                
        if sent:
            NotificationLog.objects.create(
                notification_type='SMS',
                recipient=phone_number,
                subject='پیامک درگاه اختصاصی',
                body=message,
                status='SENT'
            )
        else:
            NotificationLog.objects.create(
                notification_type='SMS',
                recipient=phone_number,
                subject='پیامک درگاه اختصاصی',
                body=message,
                status='FAILED',
                error_message="; ".join(errs)
            )
                
    elif provider == 'OTHER':
        # صرفاً ثبت لاگ برای پیام‌رسان‌های دیگر (مانند ایتا، بله و غیره) به عنوان لاگ پیامکی
        print(f"[SMS OTHER] Sent to {phone_number} via OTHER messenger: {message}")
        NotificationLog.objects.create(
            notification_type='SMS',
            recipient=phone_number,
            subject='پیامک پیام‌رسان جانبی (ایتا/بله)',
            body=message,
            status='SENT'
        )
    elif provider == 'MOCK':
        NotificationLog.objects.create(
            notification_type='SMS',
            recipient=phone_number,
            subject='پیامک شبیه‌ساز (فرضی)',
            body=message,
            status='SENT'
        )

def render_notification_template(template_text, candidate, job, stage_name=None, date=None, time=None, link=None, recruiter_name=None):
    org_setting = OrganizationSetting.get_active_setting()
    company_name = org_setting.name if org_setting else "سیستم جذب"
    
    candidate_name = f"{candidate.first_name} {candidate.last_name}"
    
    # تعیین مقادیر پیش‌فرض برای متغیرهای کمکی
    if not stage_name:
        stage_name = "- "
    if not recruiter_name and job.assigned_recruiter:
        recruiter_name = job.assigned_recruiter.get_full_name() or job.assigned_recruiter.username
    if not recruiter_name:
        recruiter_name = "کارشناس جذب"
    if not link:
        try:
            link = "http://127.0.0.1:8000" + reverse('candidate_dashboard')
        except Exception:
            link = "http://127.0.0.1:8000/candidates/dashboard/"
            
    context = {
        '{{ candidate_name }}': candidate_name,
        '{{ job_title }}': job.title,
        '{{ company_name }}': company_name,
        '{{ stage_name }}': stage_name,
        '{{ date }}': date or "- ",
        '{{ time }}': time or "- ",
        '{{ link }}': link,
        '{{ recruiter_name }}': recruiter_name,
    }
    
    rendered = template_text
    for key, val in context.items():
        rendered = rendered.replace(key, str(val))
    return rendered


# --- رسیورهای سیگنال مدل درخواست همکاری (JobApplication) ---

@receiver(pre_save, sender=JobApplication)
def track_job_app_old_status(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._old_status = JobApplication.objects.get(pk=instance.pk).status
        except JobApplication.DoesNotExist:
            instance._old_status = None
    else:
        instance._old_status = None

@receiver(post_save, sender=JobApplication)
def handle_job_application_notification(sender, instance, created, **kwargs):
    candidate = instance.candidate
    job = instance.job
    org_setting = OrganizationSetting.get_active_setting()
    if not org_setting:
        return
        
    # سناریو ۱: ثبت درخواست همکاری جدید (ثبت‌نام)
    if created:
        if org_setting.reg_email_enabled:
            email_subject = render_notification_template(org_setting.reg_email_subject, candidate, job)
            email_body = render_notification_template(org_setting.reg_email_body, candidate, job)
            send_dynamic_email(org_setting, candidate.email, email_subject, email_body)
            log_notification("EMAIL", candidate.email, email_subject, email_body)
            
        if org_setting.reg_sms_enabled:
            sms_body = render_notification_template(org_setting.reg_sms_body, candidate, job)
            send_gateway_sms(org_setting, candidate.phone_number, sms_body)
            log_notification("SMS", candidate.phone_number, "REGISTRATION", sms_body)
            
    # سناریوهای ۴ و ۵: تغییر وضعیت نهایی به پذیرش یا مردودی
    elif hasattr(instance, '_old_status') and instance._old_status != instance.status:
        if instance.status == JobApplication.STATUS_SELECTED:
            # قبولی نهایی (Job Offer)
            if org_setting.offer_email_enabled:
                email_subject = render_notification_template(org_setting.offer_email_subject, candidate, job)
                email_body = render_notification_template(org_setting.offer_email_body, candidate, job)
                send_dynamic_email(org_setting, candidate.email, email_subject, email_body)
                log_notification("EMAIL", candidate.email, email_subject, email_body)
                
            if org_setting.offer_sms_enabled:
                sms_body = render_notification_template(org_setting.offer_sms_body, candidate, job)
                send_gateway_sms(org_setting, candidate.phone_number, sms_body)
                log_notification("SMS", candidate.phone_number, "JOB_OFFER", sms_body)
                
        elif instance.status == JobApplication.STATUS_REJECTED:
            # عدم پذیرش و رد رزومه (Rejection)
            if org_setting.reject_email_enabled:
                email_subject = render_notification_template(org_setting.reject_email_subject, candidate, job)
                email_body = render_notification_template(org_setting.reject_email_body, candidate, job)
                send_dynamic_email(org_setting, candidate.email, email_subject, email_body)
                log_notification("EMAIL", candidate.email, email_subject, email_body)
                
            if org_setting.reject_sms_enabled:
                sms_body = render_notification_template(org_setting.reject_sms_body, candidate, job)
                send_gateway_sms(org_setting, candidate.phone_number, sms_body)
                log_notification("SMS", candidate.phone_number, "REJECTION", sms_body)


# --- رسیورهای سیگنال مدل مراحل ارزیابی (ApplicationStageState) ---

@receiver(pre_save, sender=ApplicationStageState)
def track_stage_state_old_values(sender, instance, **kwargs):
    if instance.pk:
        try:
            old_obj = ApplicationStageState.objects.get(pk=instance.pk)
            instance._old_status = old_obj.status
            instance._old_date = old_obj.evaluation_date
            instance._old_time = old_obj.evaluation_time
        except ApplicationStageState.DoesNotExist:
            instance._old_status = None
            instance._old_date = None
            instance._old_time = None
    else:
        instance._old_status = None
        instance._old_date = None
        instance._old_time = None

@receiver(post_save, sender=ApplicationStageState)
def handle_stage_state_notification(sender, instance, created, **kwargs):
    app = instance.application
    candidate = app.candidate
    job = app.job
    org_setting = OrganizationSetting.get_active_setting()
    if not org_setting:
        return
        
    stage = instance.stage
    stage_type = stage.stage_type
    
    # برای جلوگیری از ارسال پیامک/ایمیل تکراری یا بدون زمان‌بندی:
    # شرایط شلیک اعلانات: وضعیت مرحله PENDING باشد، مرحله قابل دسترسی باشد و تاریخ ارزیابی تعیین شده باشد.
    should_notify = False
    if instance.status == ApplicationStageState.STATUS_PENDING and instance.evaluation_date is not None and instance.is_accessible:
        if created:
            should_notify = True
        else:
            status_changed = (hasattr(instance, '_old_status') and instance._old_status != ApplicationStageState.STATUS_PENDING)
            date_changed = (hasattr(instance, '_old_date') and instance._old_date != instance.evaluation_date)
            time_changed = (hasattr(instance, '_old_time') and instance._old_time != instance.evaluation_time)
            
            if status_changed or date_changed or time_changed:
                should_notify = True
                
    if should_notify:
        # قالب‌بندی تاریخ شمسی ارزیابی کاندیدا
        import jdatetime
        jd = jdatetime.date.fromgregorian(date=instance.evaluation_date)
        date_str = jd.strftime('%Y/%m/%d')
        time_str = instance.evaluation_time or "10:00"
        
        stage_name_lower = stage.name.lower()
        is_exam = (stage_type in ['EXAM', 'SKILL_TEST']) or any(kw in stage_name_lower for kw in ['آزمون', 'کتبی', 'مهارتی', 'سنجش', 'تخصصی', 'عمومی', 'عملکردی'])
        is_interview = (stage_type in ['INTERVIEW', 'ASSESSMENT']) or any(kw in stage_name_lower for kw in ['مصاحبه', 'ارزیابی', 'کانون', 'گفتگو', 'حضوری', 'شایستگی'])
        
        # سناریو ۲: دعوت به آزمون کتبی / تخصصی
        if is_exam:
            if org_setting.exam_email_enabled:
                email_subject = render_notification_template(org_setting.exam_email_subject, candidate, job, stage_name=stage.name, date=date_str, time=time_str)
                email_body = render_notification_template(org_setting.exam_email_body, candidate, job, stage_name=stage.name, date=date_str, time=time_str)
                send_dynamic_email(org_setting, candidate.email, email_subject, email_body)
                log_notification("EMAIL", candidate.email, email_subject, email_body)
                
            if org_setting.exam_sms_enabled:
                sms_body = render_notification_template(org_setting.exam_sms_body, candidate, job, stage_name=stage.name, date=date_str, time=time_str)
                send_gateway_sms(org_setting, candidate.phone_number, sms_body)
                log_notification("SMS", candidate.phone_number, "EXAM_INVITE", sms_body)
                
        # سناریو ۳: دعوت به جلسه مصاحبه
        elif is_interview:
            if org_setting.interview_email_enabled:
                email_subject = render_notification_template(org_setting.interview_email_subject, candidate, job, stage_name=stage.name, date=date_str, time=time_str)
                email_body = render_notification_template(org_setting.interview_email_body, candidate, job, stage_name=stage.name, date=date_str, time=time_str)
                send_dynamic_email(org_setting, candidate.email, email_subject, email_body)
                log_notification("EMAIL", candidate.email, email_subject, email_body)
                
            if org_setting.interview_sms_enabled:
                sms_body = render_notification_template(org_setting.interview_sms_body, candidate, job, stage_name=stage.name, date=date_str, time=time_str)
                send_gateway_sms(org_setting, candidate.phone_number, sms_body)
                log_notification("SMS", candidate.phone_number, "INTERVIEW_INVITE", sms_body)
