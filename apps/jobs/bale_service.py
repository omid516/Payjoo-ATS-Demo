import json
import logging
import uuid
import ssl
import urllib.request
import urllib.error
import jdatetime
from django.utils import timezone
from .models import OrganizationSetting, AreaCoordinator
from .pdf_service import generate_coordinator_report_pdf
from apps.candidates.models import NotificationLog

logger = logging.getLogger(__name__)

DEFAULT_BALE_API = "https://tapi.bale.ai/bot"

def _get_ssl_context():
    """
    ایجاد context ایمن و سازگار با سرورهای ملی بله (جلوگیری از خطاهای handshake و گواهی موقت)
    """
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    except Exception:
        return None

def sanitize_bale_chat_id(raw_id):
    """
    استانداردسازی شناسه یا یوزرنیم بله:
    تبدیل اعداد فارسی به انگلیسی، اصلاح خط‌تیره (برای شناسه‌های گروهی)، حذف فواصل و کاراکترهای مخفی.
    """
    if not raw_id:
        return ""
    s = str(raw_id).strip()
    persian_arabic = {
        '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
        '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
        '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
        '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
        '−': '-', '–': '-', '—': '-', 'ـ': ''
    }
    for k, v in persian_arabic.items():
        s = s.replace(k, v)
    return s.strip()

def is_numeric_chat_id(val):
    """
    بررسی اینکه آیا مقدار داده‌شده شناسه عددی چت بله است یا خیر (شامل شناسه‌های مثبت کاربر و منفی گروه‌ها)
    """
    if not val:
        return False
    s = str(val).strip()
    if s.startswith('-'):
        s = s[1:]
    return s.isdigit()

def resolve_bale_chat_id(raw_id, token=None, api_url=None):
    """
    بررسی و استخراج شناسه عددی کاربر (Chat ID):
    در پیام‌رسان بله، ربات‌ها اجازه ارسال پیام به نام کاربری خصوصی (@username) را ندارند
    و منحصراً باید به شناسه عددی (Numeric Chat ID) ارسال کنند.
    اگر کاربر نام کاربری وارد کرده باشد، سیستم با بررسی پیام‌های دریافتی اخیر ربات (getUpdates)
    سعی می‌کند شناسه عددی وی را به شکل خودکار پیدا کند.
    خروجی: (success: bool, chat_id: str, message: str)
    """
    cleaned = sanitize_bale_chat_id(raw_id)
    if not cleaned:
        return False, None, "شناسه بله وارد نشده است."

    if is_numeric_chat_id(cleaned):
        return True, cleaned, "شناسه عددی معتبر است."

    # اگر نام کاربری متنی باشد
    clean_username = cleaned.lstrip('@').lower()
    org_setting = OrganizationSetting.get_active_setting()
    token = token or (org_setting.bale_bot_token if org_setting else "")
    token = token.strip() if token else ""

    if not token:
        return False, None, "توکن ربات بله در تنظیمات سازمان ثبت نشده است."

    api_url = (api_url or (org_setting.bale_api_url if org_setting else "") or DEFAULT_BALE_API).rstrip('/')
    url = f"{api_url}{token}/getUpdates" if api_url.endswith('/bot') else f"{api_url}/{token}/getUpdates"

    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Payjoo-ATS-Server/2.0',
            'Accept': 'application/json'
        }
    )

    try:
        ctx = _get_ssl_context()
        with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('ok'):
                for item in reversed(data.get('result', [])):
                    msg = item.get('message') or item.get('edited_message') or item.get('channel_post') or {}
                    from_user = msg.get('from') or msg.get('chat') or {}
                    u_name = (from_user.get('username') or '').lower()
                    if u_name == clean_username and from_user.get('id'):
                        num_id = str(from_user.get('id'))
                        return True, num_id, f"شناسه عددی کاربر ({num_id}) با موفقیت از تاریخچه ربات استخراج شد."
    except Exception as e:
        logger.warning(f"Failed to query getUpdates for username resolution: {e}")

    return False, None, (
        f"ارسال به نام کاربری متنی «@{clean_username}» در پیام‌رسان بله امکان‌پذیر نیست. "
        "ربات‌های بله فقط با «شناسه عددی» (Chat ID عددی) می‌توانند به افراد پیام ارسال نمایند. "
        "هماهنگ‌کننده باید ابتدا ربات بله را در چت خصوصی استارت (/start) کند و شناسه عددی خود را در فرم اطلاعات هماهنگ‌کننده ثبت نماید."
    )


def build_multipart_payload(fields, files):
    """
    ساخت بدنه فرم multipart/form-data استاندارد با کتابخانه پیش‌فرض پایتون
    """
    boundary = f"----PayjooATSBoundary{uuid.uuid4().hex}"
    body = bytearray()
    
    # افزودن فیلدهای متنی
    for key, val in fields.items():
        if val is None:
            continue
        body.extend(f"--{boundary}\r\n".encode('utf-8'))
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode('utf-8'))
        body.extend(str(val).encode('utf-8'))
        body.extend(b"\r\n")
        
    # افزودن فایل‌ها
    for key, (filename, file_bytes, mime_type) in files.items():
        body.extend(f"--{boundary}\r\n".encode('utf-8'))
        # نام فایل به صورت هدر rfc2231 / utf-8 ایمن
        body.extend(f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode('utf-8'))
        body.extend(f'Content-Type: {mime_type}\r\n\r\n'.encode('utf-8'))
        body.extend(file_bytes)
        body.extend(b"\r\n")
        
    body.extend(f"--{boundary}--\r\n".encode('utf-8'))
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def test_bale_bot_connection(token=None, api_url=None):
    """
    بررسی صحت توکن ربات بله و دریافت اطلاعات کاربری آن (getMe)
    """
    org_setting = OrganizationSetting.get_active_setting()
    token = token or (org_setting.bale_bot_token if org_setting else "")
    token = token.strip() if token else ""
    
    if not token:
        return False, "توکن ربات بله در تنظیمات وارد نشده است.", {}
        
    api_url = (api_url or (org_setting.bale_api_url if org_setting else "") or DEFAULT_BALE_API).rstrip('/')
    url = f"{api_url}{token}/getMe" if api_url.endswith('/bot') else f"{api_url}/{token}/getMe"

    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Payjoo-ATS-Server/2.0',
            'Accept': 'application/json'
        }
    )
    ctx = _get_ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('ok'):
                bot_info = data.get('result', {})
                first_name = bot_info.get('first_name', '')
                username = bot_info.get('username', '')
                return True, f"اتصال به ربات بله برقرار است: {first_name} (@{username})", bot_info
            else:
                desc = data.get('description', 'خطای ناشناخته از سرور بله')
                return False, f"خطای ربات بله: {desc}", {}
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode('utf-8'))
            desc = err_body.get('description', e.reason)
        except Exception:
            desc = str(e)
        return False, f"خطای احراز هویت بله (کد {e.code}): {desc}", {}
    except urllib.error.URLError as e:
        err_str = str(e)
        if "SSL" in err_str or "timed out" in err_str or "UNEXPECTED_EOF" in err_str:
            return False, f"خطای اتصال به سرور بله ({err_str}): لطفاً بررسی کنید VPN/فیلترشکن خاموش باشد زیرا سرور بله فقط روی شبکه داخلی ایران پاسخگو است.", {}
        return False, f"خطا در برقراری ارتباط با سرور بله: {err_str}", {}
    except Exception as e:
        return False, f"خطا در برقراری ارتباط با سرور بله: {str(e)}", {}


def send_bale_document(chat_id, file_bytes, filename, caption=None, token=None, api_url=None):
    """
    ارسال فایل سند (PDF) به یک کاربر، گروه یا کانال در پیام‌رسان بله
    """
    clean_chat_id = sanitize_bale_chat_id(chat_id)
    if not clean_chat_id:
        return False, "شناسه بله (Chat ID) نامعتبر یا خالی است."

    org_setting = OrganizationSetting.get_active_setting()
    token = token or (org_setting.bale_bot_token if org_setting else "")
    token = token.strip() if token else ""
    
    if not token:
        return False, "توکن ربات بله در سامانه تعریف نشده است. لطفاً ابتدا در تنظیمات سازمان توکن ربات بله را ثبت نمایید."

    api_url = (api_url or (org_setting.bale_api_url if org_setting else "") or DEFAULT_BALE_API).rstrip('/')
    url = f"{api_url}{token}/sendDocument" if api_url.endswith('/bot') else f"{api_url}/{token}/sendDocument"

    fields = {
        'chat_id': clean_chat_id,
    }
    if caption:
        # حداکثر طول کپشن در تلگرام و بله ۱۰۲۴ کاراکتر است
        fields['caption'] = caption[:1024]

    files = {
        'document': (filename, file_bytes, 'application/pdf')
    }

    body, content_type = build_multipart_payload(fields, files)

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            'Content-Type': content_type,
            'User-Agent': 'Payjoo-ATS-Server/2.0',
            'Accept': 'application/json'
        }
    )

    ctx = _get_ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('ok'):
                return True, "فایل با موفقیت در بله ارسال شد."
            else:
                desc = data.get('description', 'خطای ناشناخته از پیام‌رسان بله')
                return False, f"خطای ارسال در بله: {desc}"
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode('utf-8'))
            desc = err_body.get('description', e.reason)
        except Exception:
            desc = str(e)
        if e.code == 404 and "no such group or user" in desc.lower():
            desc = f"{desc} (شناسه کاربری {clean_chat_id} در بله یافت نشد یا کاربر هنوز ربات را استارت نکرده است)"
        return False, f"خطای ارسال سند در بله (کد {e.code}): {desc}"
    except urllib.error.URLError as e:
        err_str = str(e)
        if "SSL" in err_str or "timed out" in err_str or "UNEXPECTED_EOF" in err_str:
            return False, f"خطای شبکه با سرور بله ({err_str}): سرور بله فقط روی شبکه داخلی ایران پاسخگو است؛ لطفاً بررسی نمایید فیلترشکن (VPN) خاموش باشد."
        return False, f"خطا در ارسال به بله: {err_str}"
    except Exception as e:
        return False, f"خطا در ارسال به بله: {str(e)}"


def send_area_coordinator_bale_report(coordinator, jobs=None, request=None):
    """
    تولید فایل PDF گزارش اعلان‌های شغلی و ارسال مستقیم آن به شناسه بله هماهنگ‌کننده
    خروجی: (success: bool, message: str, filename: str)
    """
    if not coordinator:
        return False, "هماهنگ‌کننده مشخص نشده است.", ""

    raw_bale_id = coordinator.bale_id
    if not raw_bale_id or not str(raw_bale_id).strip():
        return False, f"شناسه بله برای «{coordinator.name}» ثبت نشده است. لطفاً ابتدا در اطلاعات هماهنگ‌کننده، آیدی بله را وارد کنید.", ""

    org_setting = OrganizationSetting.get_active_setting()
    if not org_setting or not org_setting.bale_bot_token:
        return False, "توکن ربات بله در «تنظیمات سازمان > درگاه‌های ارتباطی» پیکربندی نشده است.", ""

    # بررسی و استخراج شناسه عددی چت
    ok_resolve, target_chat_id, resolve_msg = resolve_bale_chat_id(
        raw_bale_id,
        token=org_setting.bale_bot_token,
        api_url=org_setting.bale_api_url
    )
    if not ok_resolve:
        return False, resolve_msg, ""

    # در صورتی که شناسه از روی نام کاربری حل شده باشد، هماهنگ‌کننده را با Chat ID ذخیره می‌کنیم
    if target_chat_id != coordinator.bale_id and is_numeric_chat_id(target_chat_id):
        coordinator.bale_id = target_chat_id
        coordinator.save(update_fields=['bale_id'])

    # ۱. تولید فایل PDF گزارش
    try:
        pdf_bytes, filename = generate_coordinator_report_pdf(coordinator, jobs_qs=jobs)
        if not pdf_bytes or len(pdf_bytes) == 0:
            return False, "خطا در تولید فایل PDF گزارش.", ""
    except Exception as e:
        logger.error(f"Failed to generate PDF for coordinator {coordinator.name}: {e}")
        return False, f"خطا در ایجاد فایل PDF: {str(e)}", ""

    # ۲. ساخت متن کپشن (توضیح فایل)
    today_jalali = jdatetime.date.today().strftime('%Y/%m/%d')
    dep_text = " و ".join(coordinator.departments) if coordinator.departments else "کلیه نواحی"
    caption = (
        f"📊 {filename.replace('.pdf', '')}\n"
        f"👤 گیرنده: {coordinator.name}\n"
        f"🏢 ناحیه: {dep_text}\n"
        f"📅 تاریخ صدور: {today_jalali}\n"
        f"---------------------------\n"
        f"سامانه جذب و استخدام پیجو (Payjoo ATS)"
    )

    # ۳. ارسال به بله
    success, msg = send_bale_document(
        chat_id=target_chat_id,
        file_bytes=pdf_bytes,
        filename=filename,
        caption=caption,
        token=org_setting.bale_bot_token,
        api_url=org_setting.bale_api_url
    )

    # ۴. ثبت در تاریخچه اعلان‌ها
    status_str = 'SENT' if success else 'FAILED'
    NotificationLog.objects.create(
        notification_type='BALE',
        recipient=f"{target_chat_id} ({coordinator.name})",
        subject=filename,
        body=caption,
        status=status_str,
        error_message=None if success else msg
    )

    if success:
        return True, f"گزارش وضعیت با موفقیت در قالب PDF ({filename}) به پیام‌رسان بله {coordinator.name} ارسال شد.", filename
    else:
        return False, msg, filename

