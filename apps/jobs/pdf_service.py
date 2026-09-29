import os
import subprocess
import tempfile
import logging
import jdatetime
from django.utils import timezone

logger = logging.getLogger(__name__)

CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
    "chromium-browser",
]

def find_chrome_binary():
    """یافتن مسیر اجرایی مرورگر کروم برای تبدیل هدلس HTML به PDF"""
    for path in CHROME_PATHS:
        if path.startswith("/"):
            if os.path.exists(path) and os.access(path, os.X_OK):
                return path
        else:
            import shutil
            found = shutil.which(path)
            if found:
                return found
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
    تبدیل HTML به PDF با استفاده از موتور کروم هدلس (پشتیبانی کامل از فونت فارسی، جداول و RTL)
    """
    # تزریق استایل‌های چاپ اختصاصی برای جلوگیری از شکستگی جداول در صفحه و چاپ رنگ‌های پس‌زمینه
    print_styles = """
    <style>
        @page {
            size: A4;
            margin: 12mm 10mm 12mm 10mm;
        }
        body {
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
            font-size: 11px !important;
        }
        table {
            page-break-inside: auto;
        }
        tr {
            page-break-inside: avoid;
            page-break-after: auto;
        }
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

    try:
        cmd = [
            chrome_bin,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_file_path}",
            f"file://{html_file_path}"
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
        if os.path.exists(pdf_file_path) and os.path.getsize(pdf_file_path) > 0:
            with open(pdf_file_path, "rb") as f:
                pdf_bytes = f.read()
            return pdf_bytes
        else:
            logger.warning(f"Chrome PDF generation failed or empty output: {res.stderr.decode(errors='ignore')}")
            return None
    except Exception as e:
        logger.error(f"Error during Chrome headless execution: {e}")
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


def render_html_to_pdf_reportlab(context, filename):
    """
    تولید پشتیبان (Fallback) فایل PDF ساختاریافته از طریق ReportLab در صورتی که کروم در سرور نصب نباشد.
    """
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # کشیدن سربرگ ساده
    p.setFillColorRGB(0.12, 0.23, 0.54) # رنگ سازمانی #1e3a8a
    p.rect(0, height - 60, width, 60, fill=1, stroke=0)
    
    p.setFillColorRGB(1, 1, 1)
    p.setFont("Helvetica-Bold", 14)
    p.drawString(40, height - 38, "Human Resources - Area Coordinator Report")
    
    p.setFillColorRGB(0.2, 0.2, 0.2)
    p.setFont("Helvetica", 10)
    y = height - 90
    p.drawString(40, y, f"Subject: {context.get('subject', 'Area Coordinator Report')}")
    y -= 20
    p.drawString(40, y, f"Recipient: {getattr(context.get('coordinator'), 'name', '')}")
    y -= 20
    p.drawString(40, y, f"Total Jobs: {context.get('total_jobs', 0)}")
    y -= 30
    
    for j_data in context.get('jobs_data', []):
        if y < 80:
            p.showPage()
            y = height - 50
        p.setFont("Helvetica-Bold", 11)
        p.drawString(40, y, f"- Job: {j_data.get('title')} (Code: {j_data.get('code')})")
        y -= 16
        p.setFont("Helvetica", 9)
        p.drawString(55, y, f"Department: {j_data.get('department')} | Headcount: {j_data.get('headcount')}")
        y -= 16
        p.drawString(55, y, f"Shortlisted candidates: {len(j_data.get('shortlisted_candidates', []))}")
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
        pdf_bytes = render_html_to_pdf_reportlab(context, filename)

    return pdf_bytes, filename
