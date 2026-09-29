import os
import shutil
import base64
import subprocess
import tempfile
import logging
import pathlib
import jdatetime
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_EMBEDDED_FONT_CSS = None


def get_embedded_font_css():
    """
    تولید CSS حاوی فونت فارسی استاندارد (Shabnam / Vazirmatn) به صورت base64
    جهت تضمین نمایش ۱۰۰٪ فونت فارسی در کلیه سیستم‌عامل‌ها (حتی در صورت عدم نصب فونت در سیستم یا آفلاین بودن)
    """
    global _EMBEDDED_FONT_CSS
    if _EMBEDDED_FONT_CSS is not None:
        return _EMBEDDED_FONT_CSS

    css_parts = []
    try:
        shabnam_reg = os.path.join(settings.BASE_DIR, 'static', 'fonts', 'shabnam', 'Shabnam.ttf')
        shabnam_bold = os.path.join(settings.BASE_DIR, 'static', 'fonts', 'shabnam', 'Shabnam-Bold.ttf')

        if os.path.exists(shabnam_reg):
            with open(shabnam_reg, 'rb') as f:
                b64_reg = base64.b64encode(f.read()).decode('ascii')
            css_parts.append(f"""
            @font-face {{
                font-family: 'Vazirmatn';
                src: url('data:font/truetype;charset=utf-8;base64,{b64_reg}') format('truetype');
                font-weight: normal;
                font-style: normal;
            }}
            @font-face {{
                font-family: 'Shabnam';
                src: url('data:font/truetype;charset=utf-8;base64,{b64_reg}') format('truetype');
                font-weight: normal;
                font-style: normal;
            }}
            """)

        if os.path.exists(shabnam_bold):
            with open(shabnam_bold, 'rb') as f:
                b64_bold = base64.b64encode(f.read()).decode('ascii')
            css_parts.append(f"""
            @font-face {{
                font-family: 'Vazirmatn';
                src: url('data:font/truetype;charset=utf-8;base64,{b64_bold}') format('truetype');
                font-weight: bold;
                font-style: normal;
            }}
            @font-face {{
                font-family: 'Shabnam';
                src: url('data:font/truetype;charset=utf-8;base64,{b64_bold}') format('truetype');
                font-weight: bold;
                font-style: normal;
            }}
            """)
    except Exception as e:
        logger.warning(f"Could not load embedded TTF font: {e}")

    _EMBEDDED_FONT_CSS = "\n".join(css_parts)
    return _EMBEDDED_FONT_CSS


def find_chrome_binary():
    """
    یافتن مسیر اجرایی مرورگر کروم یا مایکروسافت اج برای تبدیل هدلس HTML به PDF.
    پشتیبانی جامع و کامل از Windows (کروم و مایکروسافت اج پیش‌فرض ویندوز)، macOS و Linux.
    """
    # ۱. جستجو در متغیر PATH سیستم
    commands = [
        "chrome", "chrome.exe",
        "msedge", "msedge.exe",
        "google-chrome", "google-chrome-stable",
        "chromium", "chromium-browser",
        "brave", "brave.exe"
    ]
    for cmd in commands:
        found = shutil.which(cmd)
        if found and os.path.exists(found):
            return found

    # ۲. جستجو در رجیستری ویندوز (برای ویندوزهای سرور و کلاینت)
    try:
        import winreg
        for app in ("chrome.exe", "msedge.exe", "brave.exe"):
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    key = winreg.OpenKey(root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{app}")
                    val, _ = winreg.QueryValueEx(key, "")
                    winreg.CloseKey(key)
                    if val and os.path.exists(val):
                        return val
                except OSError:
                    pass
    except ImportError:
        pass

    # ۳. مسیرهای استاندارد نصب در ویندوز بر اساس متغیرهای محیطی
    candidate_paths = []
    for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "PROGRAMDATA"):
        base_dir = os.environ.get(env_var)
        if base_dir:
            candidate_paths.extend([
                os.path.join(base_dir, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(base_dir, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(base_dir, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
            ])

    # ۴. درایوهای پیش‌فرض ویندوز
    for drive in ("C", "D", "E", "F"):
        candidate_paths.extend([
            rf"{drive}:\Program Files\Google\Chrome\Application\chrome.exe",
            rf"{drive}:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            rf"{drive}:\Program Files\Microsoft\Edge\Application\msedge.exe",
            rf"{drive}:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            rf"{drive}:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        ])

    # ۵. مسیرهای macOS
    candidate_paths.extend([
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ])

    # ۶. مسیرهای لینوکس
    candidate_paths.extend([
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/microsoft-edge",
        "/usr/bin/microsoft-edge-stable",
        "/snap/bin/chromium",
        "/snap/bin/chromium-browser",
    ])

    for p in candidate_paths:
        if p and os.path.exists(p) and (not p.startswith("/") or os.access(p, os.X_OK)):
            return p

    return None


def generate_coordinator_report_filename(department=None, report_date=None):
    """
    تولید نام فایل استاندارد بر اساس دستور کاربر:
    «گزارش اعلان شغلی ناحیه [نام ناحیه] - [تاریخ].pdf»
    """
    if not report_date:
        report_date = jdatetime.date.today().strftime('%Y-%m-%d')
    else:
        # استخراج بخش تاریخ و پاکسازی کاراکترهای نامعتبر
        report_date = str(report_date).split(' - ')[0].replace('/', '-').strip()

    if not department:
        dep_str = "عمومی"
    elif isinstance(department, (list, tuple)):
        dep_str = " و ".join(str(d).strip() for d in department if d and str(d).strip())
    else:
        dep_str = str(department).strip()

    # حذف کاراکترهای غیرمجاز در نام فایل سیستم‌عامل
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        dep_str = dep_str.replace(ch, '-')
        
    dep_str = " ".join(dep_str.split()) # حذف فاصله‌های اضافی
    
    # جلوگیری از تکرار کلمه ناحیه
    prefix = "" if dep_str.startswith("ناحیه") else "ناحیه "
    filename = f"گزارش اعلان شغلی {prefix}{dep_str} - {report_date}.pdf"
    return filename


def render_html_to_pdf_chrome(html_content, chrome_bin):
    """
    تبدیل HTML به PDF با استفاده از موتور کروم / مایکروسافت اج هدلس
    (پشتیبانی کامل از فونت فارسی، جداول، راست‌به‌چپ RTL و رنگ‌ها در کلیه سیستم‌عامل‌ها)
    """
    font_css = get_embedded_font_css()

    # تزریق استایل‌های چاپ و فونت‌های فارسی جاسازی‌شده
    print_styles = f"""
    <style>
        {font_css}
        @page {{
            size: A4;
            margin: 10mm 10mm 10mm 10mm;
        }}
        html, body {{
            font-family: 'Vazirmatn', 'Shabnam', Tahoma, Arial, sans-serif !important;
            direction: rtl !important;
            text-align: right !important;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
            font-size: 11px !important;
        }}
        table {{
            page-break-inside: auto;
        }}
        tr {{
            page-break-inside: avoid;
            page-break-after: auto;
        }}
    </style>
    """
    if "</head>" in html_content:
        html_with_styles = html_content.replace("</head>", f"{print_styles}</head>")
    else:
        html_with_styles = print_styles + html_content

    with tempfile.NamedTemporaryFile(suffix=".html", mode="w", encoding="utf-8", delete=False) as html_file:
        html_file.write(html_with_styles)
        html_file_path = html_file.name

    pdf_file_path = html_file_path.replace(".html", ".pdf")
    # آدرس فایل محلی سازگار با استانداردهای Windows و Unix
    file_uri = pathlib.Path(os.path.abspath(html_file_path)).as_uri()

    try:
        cmd = [
            chrome_bin,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            f"--print-to-pdf={pdf_file_path}",
            file_uri
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if os.path.exists(pdf_file_path) and os.path.getsize(pdf_file_path) > 0:
            with open(pdf_file_path, "rb") as f:
                pdf_bytes = f.read()
            return pdf_bytes
        else:
            logger.warning(f"Browser PDF generation failed or empty output: {res.stderr.decode(errors='ignore')}")
            return None
    except Exception as e:
        logger.error(f"Error during browser headless execution: {e}")
        return None
    finally:
        if os.path.exists(html_file_path):
            try:
                os.remove(html_file_path)
            except OSError:
                pass
        if os.path.exists(pdf_file_path):
            try:
                os.remove(pdf_file_path)
            except OSError:
                pass


def _register_reportlab_fonts():
    """ثبت فونت فارسی در ReportLab جهت جلوگیری از چاپ مربع در صورت عدم وجود کروم"""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        shabnam_reg = os.path.join(settings.BASE_DIR, 'static', 'fonts', 'shabnam', 'Shabnam.ttf')
        shabnam_bold = os.path.join(settings.BASE_DIR, 'static', 'fonts', 'shabnam', 'Shabnam-Bold.ttf')

        if os.path.exists(shabnam_reg):
            pdfmetrics.registerFont(TTFont('Shabnam', shabnam_reg))
        if os.path.exists(shabnam_bold):
            pdfmetrics.registerFont(TTFont('Shabnam-Bold', shabnam_bold))
        return True
    except Exception as e:
        logger.warning(f"Could not register ReportLab fonts: {e}")
        return False


def render_html_to_pdf_reportlab(context, filename):
    """
    تولید پشتیبان (Fallback) فایل PDF ساختاریافته از طریق ReportLab با فونت فارسی
    """
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    _register_reportlab_fonts()
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # کشیدن سربرگ
    p.setFillColorRGB(0.12, 0.23, 0.54) # رنگ سازمانی #1e3a8a
    p.rect(0, height - 60, width, 60, fill=1, stroke=0)
    
    font_title = "Shabnam-Bold" if "Shabnam-Bold" in p.getAvailableFonts() else ("Shabnam" if "Shabnam" in p.getAvailableFonts() else "Helvetica-Bold")
    font_body = "Shabnam" if "Shabnam" in p.getAvailableFonts() else "Helvetica"

    p.setFillColorRGB(1, 1, 1)
    p.setFont(font_title, 14)
    p.drawString(40, height - 38, "واحد تامین سرمایه انسانی - گزارش اعلان شغلی هماهنگ‌کننده")
    
    p.setFillColorRGB(0.2, 0.2, 0.2)
    p.setFont(font_body, 10)
    y = height - 90
    p.drawString(40, y, f"موضوع: {context.get('subject', 'گزارش هماهنگ‌کننده ناحیه')}")
    y -= 20
    p.drawString(40, y, f"هماهنگ‌کننده: {getattr(context.get('coordinator'), 'name', '')}")
    y -= 20
    p.drawString(40, y, f"تعداد کل اعلان‌ها: {context.get('total_jobs', 0)}")
    y -= 30
    
    for j_data in context.get('jobs_data', []):
        if y < 80:
            p.showPage()
            y = height - 50
        p.setFont(font_title, 11)
        p.drawString(40, y, f"• عنوان شغل: {j_data.get('title')} (کد: {j_data.get('code')})")
        y -= 16
        p.setFont(font_body, 9)
        p.drawString(55, y, f"ناحیه: {j_data.get('department')} | ظرفیت: {j_data.get('headcount')}")
        y -= 16
        p.drawString(55, y, f"تعداد برگزیدگان: {len(j_data.get('shortlisted_candidates', []))}")
        y -= 25

    p.showPage()
    p.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generate_coordinator_report_pdf(coordinator, jobs_qs=None):
    """
    تولید فایل PDF کامل گزارش هماهنگ‌کننده به همراه نام استاندارد آن
    خروجی: (pdf_bytes: bytes, filename: str)
    """
    from .coordinator_service import generate_coordinator_report_payload

    html_content, subject, context, jobs_data = generate_coordinator_report_payload(coordinator, jobs_qs=jobs_qs)

    # تعیین بخش دپارتمان برای نام فایل
    if jobs_qs and len(jobs_qs) == 1:
        dep_name = jobs_qs[0].department
    elif coordinator and coordinator.departments:
        dep_name = " و ".join(coordinator.departments)
    else:
        dep_name = "کلیه نواحی"

    report_date = context.get('report_date') or jdatetime.date.today().strftime('%Y-%m-%d')
    filename = generate_coordinator_report_filename(dep_name, report_date)

    chrome_bin = find_chrome_binary()
    pdf_bytes = None
    if chrome_bin:
        pdf_bytes = render_html_to_pdf_chrome(html_content, chrome_bin)

    if not pdf_bytes:
        logger.warning(f"Browser not found or failed, falling back to ReportLab for {filename}")
        pdf_bytes = render_html_to_pdf_reportlab(context, filename)

    return pdf_bytes, filename

