# Payjoo ATS - Applicant Tracking System / سامانه جذب و استخدام پیجو

Payjoo ATS is a modern, responsive, and bilingual (Persian & English) Applicant Tracking System built with Python, Django, and HTMX. It provides recruiters and managers with tools to manage job opportunities, define custom evaluation stages with dynamic weights, assign recruiters, track candidate progress through pipeline workflows, and generate printable audit-ready exam documents.

**Note**: This system is specifically designed and optimized for **Internal Job Postings / Internal Recruitment Processes** (اعلان‌های شغلی داخلی) within an organization, supporting attributes like personnel numbers, national IDs, and direct regional manager approvals.

سامانه «پیجو» یک سیستم مدیریت و فرآیند جذب و استخدام مدرن، ریسپانسیو و دوزبانه (فارسی و انگلیسی) است که با استفاده از پایتون، جنگو و HTMX طراحی شده است. این سامانه به کارشناسان جذب و مدیران اجازه می‌دهد فرصت‌های شغلی را ثبت کنند، مراحل ارزیابی پویا با وزن‌های مختلف بسازند، کارشناسان جذب را تخصیص دهند، فرآیند مصاحبه‌ها و نمرات متقاضیان را در پایپلاین دنبال کنند و در نهایت سند آزمون آماده چاپ دریافت نمایند.

**نکته مهم**: این سامانه به طور ویژه برای **اعلان‌های شغلی داخلی (فرآیندهای جذب داخلی از میان پرسنل موجود سازمان)** طراحی و بهینه‌سازی شده است و امکاناتی همچون ثبت کد پرسنلی، تطبیق با کدهای ملی، و گردش امضای تایید مدیران ناحیه را در خود دارد.

---

## Language Toggle / انتخاب زبان
- [English Documentation](#english)
- [راهنمای فارسی](#persian)

---

<a name="english"></a>

## English Documentation

### Key Features
- **Bilingual Interface (RTL & LTR)**: Fully localized in Persian and English with responsive styling, customized typography (Vazirmatn font) and standard CSS layouts.
- **Internal Recruitment Optimization**: Tailored fields including *Personnel Number* (شماره پرسنلی), *National ID* (کد ملی), and regional department/unit groupings.
- **Dynamic Job Opportunities**: Create and manage job roles categorized by job category choices (Operator-Repairman, Associate, Associate Lead, Specialist, Specialist Lead, Management Specialist) with separate Job Description (شرح شغل) and Requirements (شرایط احراز).
- **Dynamic Evaluation Workflows**:
  - Automatically apply pre-defined workflow templates to job opportunities.
  - Dynamically preview template stages and weights in the creation form.
  - Customize evaluation stages (e.g. written exam, technical interview, assessment center) ensuring the sum of all stage weights equals exactly 100%.
- **Recruitment Pipeline Kanban Board**:
  - Drag and drop or state-select to progress applicants through stages.
  - Filter user selections so candidates are never selectable as system users (recruiters/interviewers).
  - Quick-edit interviewer scores directly inside the pipeline grid using HTMX AJAX.
- **Printable Exam Document**: Generates an A4 print-optimized document for job specifications and evaluation metrics with a list of assigned stage interviewers and custom signature blocks for the *Human Capital Recruitment Specialist*, *Head of Recruitment Unit*, and *Area Manager*.
- **Excel Import/Export**: 
  - Bulk import candidates from Excel (automatically generates passwords using National ID as username and Phone Number with leading zero as password).
  - Export job status reports and stats to Excel files.
- **Audit Trails**: Full auditing mechanism (`AuditLog` model) tracking all model creations, status updates, score modifications, and deletes.
- **Comprehensive Dashboard**: Dashboard metrics showing active candidate count per stage, department job requests, bottlenecks, and average time-to-hire.
- **Robust Testing Suite**: 66 unit tests covering RBAC, metrics, form validations, and status constraints.

### Tech Stack
- **Backend**: Python 3.10+, Django 5.2+
- **Frontend**: HTML5, Vanilla CSS, Bootstrap 5.3 RTL, JavaScript, HTMX (for fast partial page updates without full page reloads)
- **Database**: SQLite3

### Installation & Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/omid516/Payjoo-ATS.git
   cd Payjoo-ATS
   ```

2. **Create a Virtual Environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run Database Migrations**:
   ```bash
   python manage.py migrate
   ```

5. **Create a Superuser**:
   ```bash
   python manage.py createsuperuser
   ```
   *Follow the prompts to enter a username, email, and password.*

6. **Start the Development Server**:
   ```bash
   python manage.py runserver
   ```
   *The site will be live at `http://127.0.0.1:8000/`.*

7. **Run Unit Tests**:
   ```bash
   python manage.py test apps
   ```

---

<a name="persian"></a>

## راهنمای فارسی (Persian)

### ویژگی‌های کلیدی
- **واسط کاربری کاملاً فارسی و راست‌چین**: بومی‌سازی شده با فونت خوانای وزیرمتن و طراحی واکنش‌گرا (Responsive).
- **بهینه‌شده برای جذب داخلی**: پشتیبانی کامل از فیلدهای سازمانی مانند *شماره پرسنلی*، *کد ملی* و هماهنگی بر اساس ساختار دپارتمان‌ها و واحدهای داخلی سازمان.
- **فرصت‌های شغلی منعطف**: ثبت فرصت‌های شغلی با قابلیت انتخاب رده‌های شغلی استاندارد (اپراتور - تعمیرکار، کاردان، کاردان مسئول، کارشناس، کارشناس مسئول، کارشناس مدیریت) و تفکیک فیلدهای شرح شغل و شرایط احراز.
- **الگوهای فرآیند ارزیابی پویا**:
  - انتساب الگوهای فرآیند کاری آماده به فرصت‌های شغلی به همراه پیش‌نمایش درجا و زنده مراحل الگو در فرم ثبت شغل.
  - امکان شخصی‌سازی درصد اوزان هر مرحله به طوری که مجموع اوزان دقیقاً برابر ۱۰۰٪ باشد.
- **پایپلاین ارزیابی متقاضیان (برد کانبان)**:
  - مدیریت وضعیت و جابجایی متقاضیان در مراحل مختلف ارزیابی.
  - عدم نمایش متقاضیان در دراپ‌داون‌های کاربری سیستم (از جمله کارشناسان جذب و مصاحبه‌گران).
  - امکان ثبت و ویرایش سریع نمرات مصاحبه‌گران به صورت Ajax بر روی جدول پایپلاین با استفاده از HTMX.
- **سند آزمون چاپی جهت تایید نهایی**:
  - صدور سند چاپی بهینه‌سازی شده برای کاغذ A4 به همراه لیست مصاحبه‌گران هر مرحله.
  - باکس‌های امضا و تایید رسمی برای: *کارشناس تامین سرمایه انسانی*، *رئیس واحد تامین سرمایه انسانی*، و *مدیر ناحیه*.
- **ورود و خروج اکسل (Excel Import/Export)**:
  - درون‌ریزی گروهی متقاضیان از فایل اکسل (با تخصیص خودکار نام کاربری برابر با کد ملی و رمز عبور برابر با شماره موبایل همراه با صفر اول آن).
  - برون‌بری گزارش‌ها و اطلاعات آماری فرصت‌های شغلی به فایل اکسل.
- **ثبت لاگ‌های ممیزی (Audit Log)**: ردیابی و ثبت غیرقابل تغییر هرگونه ایجاد، ویرایش نمره، تغییر وضعیت و حذف ردیف‌ها در سیستم برای مدیران.
- **داشبورد آماری جامع**: نمایش لحظه‌ای تعداد متقاضیان فعال در هر مرحله ارزیابی، درخواست‌های دپارتمان‌ها، شناسایی گلوگاه‌های فرآیند و میانگین روز تعیین تکلیف فرصت‌های شغلی.
- **مجموعه تست خودکار**: شامل ۶۶ تست واحد برای صحت عملکرد دسترسی‌ها (RBAC)، فرم‌ها و فیلترها.

### پیش‌نیازها و راه‌اندازی

۱. **کلون کردن پروژه**:
   ```bash
   git clone https://github.com/omid516/Payjoo-ATS.git
   cd Payjoo-ATS
   ```

۲. **ایجاد محیط مجازی پایتون (Virtual Environment)**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # در ویندوز: .venv\Scripts\activate
   ```

۳. **نصب پکیج‌های مورد نیاز**:
   ```bash
   pip install -r requirements.txt
   ```

۴. **اجرای مایگریشن‌های پایگاه داده**:
   ```bash
   python manage.py migrate
   ```

۵. **ایجاد کاربر ارشد (Superuser) سیستم**:
   ```bash
   python manage.py createsuperuser
   ```
   *نام کاربری، ایمیل و رمز عبور خود را وارد کنید.*

۶. **راه‌اندازی سرور توسعه**:
   ```bash
   python manage.py runserver
   ```
   *سامانه از طریق آدرس `http://127.0.0.1:8000/` در دسترس خواهد بود.*

۷. **اجرای تست‌های واحد**:
   ```bash
   python manage.py test apps
   ```
