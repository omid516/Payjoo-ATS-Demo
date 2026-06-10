import re
import datetime
import jdatetime
import openpyxl
from django.db import transaction
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from .models import ImportSession, StagingJobOpportunity, StagingCandidate, ImportSessionLog

def normalize_persian_digits(s):
    """
    تبدیل ارقام فارسی و عربی به انگلیسی
    """
    if s is None:
        return ""
    s = str(s).strip()
    persian_to_english = {
        '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
        '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
        '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
        '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9'
    }
    for k, v in persian_to_english.items():
        s = s.replace(k, v)
    return s


def parse_date_safely(val):
    """
    تبدیل تاریخ دریافتی به تاریخ میلادی استاندارد.
    پشتیبانی از انواع فرمت‌های تاریخ شمسی (متنی) و اشیاء datetime/date پایتون.
    """
    if val is None:
        return None

    # اگر از قبل شیء تاریخ بود
    if isinstance(val, (datetime.date, datetime.datetime)):
        if isinstance(val, datetime.datetime):
            return val.date()
        return val

    # تبدیل به رشته و نرمال‌سازی اعداد
    date_str = normalize_persian_digits(val).strip()
    if not date_str or date_str.lower() in ['none', 'null', '']:
        return None

    # بررسی اگر شبیه به تاریخ اکسل عددی باشد
    if date_str.isdigit() and len(date_str) in [4, 5]:
        try:
            # تبدیل عدد سریال اکسل به تاریخ میلادی
            excel_epoch = datetime.date(1899, 12, 30)
            return excel_epoch + datetime.timedelta(days=int(date_str))
        except Exception:
            pass

    # الگوهای تاریخ شمسی: e.g. 1402/05/12 or 1401-12-05
    match = re.match(r'^(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?:\s+.*)?$', date_str)
    if match:
        year, month, day = map(int, match.groups())
        # تصحیح سال‌های دو رقمی
        if year < 100:
            year += 1300 if year > 50 else 1400
        try:
            return jdatetime.date(year, month, day).togregorian()
        except ValueError:
            return None

    # حالت‌های متفرقه: فقط سال و ماه یا تاریخ ناقص
    match_partial = re.match(r'^(\d{4})[/-](\d{1,2})$', date_str)
    if match_partial:
        year, month = map(int, match_partial.groups())
        try:
            return jdatetime.date(year, month, 1).togregorian()
        except ValueError:
            return None

    return None


def validate_national_id(national_id):
    """
    بررسی معتبر بودن کد ملی ایران (۱۰ رقم و بررسی رقم کنترلی)
    """
    if not national_id:
        return False
    nid = normalize_persian_digits(national_id).zfill(10)
    if not nid.isdigit() or len(nid) != 10:
        return False
    
    # الگوهای تکراری مانند 1111111111 نامعتبر هستند
    if re.match(r'^(\d)\1{9}$', nid):
        return False

    check = int(nid[9])
    s = sum(int(nid[i]) * (10 - i) for i in range(9))
    r = s % 11
    return (r < 2 and check == r) or (r >= 2 and check == 11 - r)


def analyze_excel_structure(import_session, main_sheet_name=None, workflow_col_name=None):
    """
    تحلیل ساختار فایل اکسل بارگذاری شده جهت استخراج نام شیت‌ها، ردیف‌ها و الگوهای استخدام
    """
    try:
        wb = openpyxl.load_workbook(import_session.excel_file.path, read_only=True)
        sheet_names = wb.sheetnames
        if not sheet_names:
            raise ValidationError("فایل اکسل فاقد هرگونه شیت است.")

        # انتخاب شیت اصلی به صورت هوشمند
        if not main_sheet_name:
            # جستجو برای شیت "وضعیت" یا موارد مشابه
            for name in sheet_names:
                if 'وضعیت' in name or 'status' in name.lower() or 'فرصت' in name:
                    main_sheet_name = name
                    break
            if not main_sheet_name:
                main_sheet_name = sheet_names[-1] # به عنوان زاپاس آخرین شیت

        if main_sheet_name not in sheet_names:
            main_sheet_name = sheet_names[-1]

        # خواندن شیت اصلی برای استخراج هدرها و الگوها
        ws = wb[main_sheet_name]
        headers = []
        rows_count = 0
        workflow_patterns = set()

        # خواندن سطر اول برای هدرها
        rows_iterator = ws.iter_rows(values_only=True)
        try:
            first_row = next(rows_iterator)
            headers = [str(cell).strip() for cell in first_row if cell is not None]
        except StopIteration:
            headers = []

        # تشخیص هوشمند ستون الگوی استخدام
        if not workflow_col_name and headers:
            for h in headers:
                if any(kw in h for kw in ['مسیر پیشنهادی', 'الگوی استخدام', 'الگو', 'فرآیند', 'workflow', 'pattern']):
                    workflow_col_name = h
                    break

        # یافتن ایندکس ستون الگو
        wf_col_idx = None
        if workflow_col_name in headers:
            wf_col_idx = headers.index(workflow_col_name)

        # اگر تا الان ستون الگو پیدا نشده، نمونه داده‌ها را اسکن کنیم تا ستونی که حاوی کاراکتر + است را پیدا کنیم
        # این کار همزمان با شمارش ردیف‌ها انجام می‌شود
        scan_wf_by_values = (wf_col_idx is None)
        detected_wf_col_idx = None

        rows_count = 0
        for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if idx == 1:
                continue
            if any(cell is not None for cell in row):
                rows_count += 1
                
                # اسکن هوشمند ستون الگو از روی مقادیر در صورت نیاز
                if scan_wf_by_values and detected_wf_col_idx is None:
                    for col_idx, cell in enumerate(row):
                        if cell and isinstance(cell, str) and '+' in cell:
                            if any(k in cell for k in ['کتبی', 'مصاحبه', 'کانون', 'مهارتی', 'ارزیابی', 'غربال']):
                                detected_wf_col_idx = col_idx
                                if col_idx < len(headers):
                                    workflow_col_name = headers[col_idx]
                                break
                    if detected_wf_col_idx is not None:
                        wf_col_idx = detected_wf_col_idx

                # استخراج الگو
                if wf_col_idx is not None and wf_col_idx < len(row):
                    pattern = row[wf_col_idx]
                    if pattern:
                        workflow_patterns.add(str(pattern).strip())

        # اگر هنوز هم پیدا نشده، آخرین ستون را در نظر بگیریم
        if wf_col_idx is None and headers:
            wf_col_idx = len(headers) - 1
            workflow_col_name = headers[-1]
            for row in ws.iter_rows(values_only=True):
                if len(row) > wf_col_idx:
                    pattern = row[wf_col_idx]
                    if pattern:
                        workflow_patterns.add(str(pattern).strip())

        # تحلیل بقیه شیت‌ها (مراحل)
        stage_sheets = []
        for name in sheet_names:
            if name == main_sheet_name:
                continue
            stage_ws = wb[name]
            stage_headers = []
            stage_rows = 0
            for s_idx, s_row in enumerate(stage_ws.iter_rows(values_only=True), start=1):
                if s_idx == 1:
                    stage_headers = [str(cell).strip() for cell in s_row if cell is not None]
                else:
                    if any(cell is not None for cell in s_row):
                        stage_rows += 1
            
            stage_sheets.append({
                'name': name,
                'rows_count': stage_rows,
                'headers': stage_headers
            })

        summary = {
            'main_sheet': main_sheet_name,
            'main_headers': headers,
            'main_rows_count': rows_count,
            'workflow_col': workflow_col_name,
            'workflow_patterns': sorted(list(workflow_patterns)),
            'stage_sheets': stage_sheets,
            'all_sheets': sheet_names
        }
        
        import_session.summary_data = summary
        import_session.status = 'ANALYZED'
        import_session.save(update_fields=['summary_data', 'status'])
        
        ImportSessionLog.objects.create(
            import_session=import_session,
            level='INFO',
            message=f"ساختار فایل با موفقیت تحلیل شد. شیت اصلی '{main_sheet_name}'، {rows_count} فرصت شغلی و {len(stage_sheets)} شیت دیگر یافت شد."
        )
        return summary
    except Exception as e:
        import_session.status = 'FAILED'
        import_session.save(update_fields=['status'])
        ImportSessionLog.objects.create(
            import_session=import_session,
            level='ERROR',
            message=f"خطا در تحلیل ساختار فایل: {str(e)}"
        )
        raise e


@transaction.atomic
def parse_and_stage_data(import_session, mapping_config):
    """
    استخراج داده‌های خام از اکسل بر اساس پیکربندی نگاشت و ثبت در جداول موقت (Staging Tables) همراه با اعتبارسنجی
    """
    # پاکسازی داده‌های قبلی نشست در صورت تلاش مجدد
    import_session.staging_jobs.all().delete()
    import_session.staging_candidates.all().delete()
    import_session.logs.all().delete()

    import_session.mapping_config = mapping_config
    import_session.status = 'MAPPED'
    import_session.save(update_fields=['mapping_config', 'status'])

    wb = openpyxl.load_workbook(import_session.excel_file.path, data_only=True)
    
    # ۱. پردازش شیت اصلی (فرصت‌های شغلی)
    main_sheet_name = mapping_config.get('main_sheet')
    if main_sheet_name not in wb.sheetnames:
        raise ValidationError(f"شیت اصلی '{main_sheet_name}' یافت نشد.")
    
    main_ws = wb[main_sheet_name]
    job_fields = mapping_config.get('job_fields', {})
    
    # یافتن ایندکس ستون‌ها بر اساس هدرها
    main_rows = list(main_ws.iter_rows(values_only=True))
    if not main_rows:
        raise ValidationError("شیت اصلی فاقد اطلاعات است.")
    
    main_headers = [str(h).strip() for h in main_rows[0]]
    
    def get_col_idx(header_name):
        if not header_name:
            return None
        try:
            return main_headers.index(str(header_name).strip())
        except ValueError:
            return None

    col_indices = {field: get_col_idx(col_name) for field, col_name in job_fields.items()}

    # جمع‌آوری کدهای شغل برای اعتبارسنجی ارجاع کاندیداها
    job_codes_in_excel = set()
    
    from apps.jobs.models import JobOpportunity

    for idx, row in enumerate(main_rows[1:], start=2):
        if not any(cell is not None for cell in row):
            continue

        raw_data = {main_headers[i]: row[i] for i in range(min(len(row), len(main_headers)))}
        
        job_code = normalize_persian_digits(row[col_indices['job_code']]).strip() if col_indices.get('job_code') is not None else None
        title = str(row[col_indices['title']]).strip() if col_indices.get('title') is not None else None
        department = str(row[col_indices['department']]).strip() if col_indices.get('department') is not None else ""
        headcount_raw = row[col_indices['headcount']] if col_indices.get('headcount') is not None else "1"
        status_raw = str(row[col_indices['status']]).strip() if col_indices.get('status') is not None else ""
        start_date_raw = row[col_indices['start_date']] if col_indices.get('start_date') is not None else None
        workflow_raw = str(row[col_indices['workflow_pattern']]).strip() if col_indices.get('workflow_pattern') is not None else ""

        errors = []
        warnings = []

        if not job_code:
            errors.append("کد فرصت شغلی نمی‌تواند خالی باشد.")
        else:
            job_codes_in_excel.add(job_code)

        if not title:
            errors.append("عنوان فرصت شغلی نمی‌تواند خالی باشد.")

        # اعتبارسنجی تعداد ظرفیت
        headcount = 1
        if headcount_raw:
            try:
                headcount = int(normalize_persian_digits(headcount_raw))
            except ValueError:
                warnings.append(f"فرمت ظرفیت استخدام '{headcount_raw}' نامعتبر است. مقدار پیش‌فرض ۱ در نظر گرفته شد.")
        
        # اعتبارسنجی و تبدیل تاریخ شروع
        start_date_parsed = parse_date_safely(start_date_raw)
        if start_date_raw and not start_date_parsed:
            warnings.append(f"امکان تبدیل تاریخ شروع '{start_date_raw}' به میلادی وجود نداشت.")
        
        # تشخیص تعارض با داده‌های دیتابیس فعلی
        final_job = None
        if job_code:
            existing_job = JobOpportunity.objects.filter(code=job_code, is_deleted=False).first()
            if existing_job:
                final_job = existing_job
                warnings.append(f"فرصت شغلی با کد '{job_code}' از قبل در سیستم وجود دارد (احتمال تعارض).")

        staging_job = StagingJobOpportunity.objects.create(
            import_session=import_session,
            row_index=idx,
            job_code=job_code,
            title=title,
            department=department,
            headcount=str(headcount),
            status=status_raw,
            start_date_str=str(start_date_raw) if start_date_raw else "",
            workflow_pattern=workflow_raw,
            raw_data=raw_data,
            is_valid=(len(errors) == 0),
            validation_errors=errors,
            validation_warnings=warnings,
            final_job=final_job
        )

        if errors:
            ImportSessionLog.objects.create(
                import_session=import_session,
                level='ERROR',
                sheet_name=main_sheet_name,
                row_index=idx,
                message=f"خطا در ردیف {idx}: " + " | ".join(errors)
            )
        elif warnings:
            ImportSessionLog.objects.create(
                import_session=import_session,
                level='WARNING',
                sheet_name=main_sheet_name,
                row_index=idx,
                message=f"هشدار در ردیف {idx}: " + " | ".join(warnings)
            )

    # ۲. پردازش شیت‌های مراحل ارزیابی (متقاضیان)
    stage_sheet_mappings = mapping_config.get('stage_sheet_mappings', {})
    from apps.candidates.models import Candidate

    for sheet_name, sheet_config in stage_sheet_mappings.items():
        if sheet_name not in wb.sheetnames:
            ImportSessionLog.objects.create(
                import_session=import_session,
                level='WARNING',
                message=f"شیت ارزیابی '{sheet_name}' در اکسل یافت نشد و نادیده گرفته شد."
            )
            continue
        
        ws = wb[sheet_name]
        stage_type = sheet_config.get('stage_type')
        c_fields = sheet_config.get('candidate_fields', {})
        
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        
        headers = [str(h).strip() for h in rows[0]]
        
        def get_sheet_col_idx(header_name):
            if not header_name:
                return None
            try:
                return headers.index(str(header_name).strip())
            except ValueError:
                return None

        c_indices = {field: get_sheet_col_idx(col_name) for field, col_name in c_fields.items()}

        for idx, row in enumerate(rows[1:], start=2):
            if not any(cell is not None for cell in row):
                continue
            
            raw_data = {headers[i]: row[i] for i in range(min(len(row), len(headers)))}
            
            job_code = normalize_persian_digits(row[c_indices['job_code']]).strip() if c_indices.get('job_code') is not None else None
            national_id = normalize_persian_digits(row[c_indices['national_id']]).strip() if c_indices.get('national_id') is not None else None
            first_name = str(row[c_indices['first_name']]).strip() if c_indices.get('first_name') is not None else ""
            last_name = str(row[c_indices['last_name']]).strip() if c_indices.get('last_name') is not None else ""
            phone_number = normalize_persian_digits(row[c_indices['phone_number']]).strip() if c_indices.get('phone_number') is not None else ""
            email = str(row[c_indices['email']]).strip() if c_indices.get('email') is not None else ""
            score_raw = row[c_indices['score']] if c_indices.get('score') is not None else "0"
            date_raw = row[c_indices['date']] if c_indices.get('date') is not None else None

            errors = []
            warnings = []

            # اعتبارسنجی کد ملی
            if not national_id:
                errors.append("کد ملی متقاضی نمی‌تواند خالی باشد.")
            elif not validate_national_id(national_id):
                warnings.append(f"قالب کد ملی '{national_id}' نامعتبر یا غیر استاندارد است.")

            if not first_name or not last_name:
                errors.append("نام و نام خانوادگی متقاضی الزامی است.")

            if not job_code:
                errors.append("کد فرصت شغلی برای متقاضی الزامی است.")
            elif job_code not in job_codes_in_excel:
                # بررسی تعارض کد شغل با کدهای شیت اصلی
                errors.append(f"فرصت شغلی با کد '{job_code}' در شیت اصلی وضعیت یافت نشد.")

            # بررسی امتیاز
            score = "0.0"
            if score_raw:
                try:
                    score = str(float(normalize_persian_digits(score_raw)))
                except ValueError:
                    warnings.append(f"امتیاز مرحله '{score_raw}' عددی نیست. مقدار ۰ ثبت شد.")

            # اعتبارسنجی تاریخ ارزیابی
            date_parsed = parse_date_safely(date_raw)
            if date_raw and not date_parsed:
                warnings.append(f"امکان تبدیل تاریخ ارزیابی '{date_raw}' به میلادی وجود نداشت.")

            # بررسی تطابق کد ملی متقاضی در پایگاه داده
            final_candidate = None
            if national_id:
                existing_candidate = Candidate.objects.filter(national_id=national_id, is_deleted=False).first()
                if existing_candidate:
                    final_candidate = existing_candidate
                    warnings.append(f"متقاضی با کد ملی '{national_id}' از قبل در سیستم ثبت شده است.")

            staging_candidate = StagingCandidate.objects.create(
                import_session=import_session,
                sheet_name=sheet_name,
                row_index=idx,
                job_code=job_code,
                national_id=national_id,
                first_name=first_name,
                last_name=last_name,
                phone_number=phone_number,
                email=email,
                score=score,
                evaluation_date_str=str(date_raw) if date_raw else "",
                stage_type=stage_type,
                raw_data=raw_data,
                is_valid=(len(errors) == 0),
                validation_errors=errors,
                validation_warnings=warnings,
                final_candidate=final_candidate
            )

            if errors:
                ImportSessionLog.objects.create(
                    import_session=import_session,
                    level='ERROR',
                    sheet_name=sheet_name,
                    row_index=idx,
                    message=f"خطا در ردیف {idx}: " + " | ".join(errors)
                )
            elif warnings:
                ImportSessionLog.objects.create(
                    import_session=import_session,
                    level='WARNING',
                    sheet_name=sheet_name,
                    row_index=idx,
                    message=f"هشدار در ردیف {idx}: " + " | ".join(warnings)
                )

    # به‌روزرسانی وضعیت نشست
    import_session.status = 'PREVIEWED'
    import_session.save(update_fields=['status'])
    
    ImportSessionLog.objects.create(
        import_session=import_session,
        level='INFO',
        message="فرآیند استخراج داده‌ها و اعتبارسنجی با موفقیت به پایان رسید. پیش‌نمایش آماده بازدید است."
    )


@transaction.atomic
def execute_final_import(import_session, conflict_strategy, user):
    """
    اجرای تراکنشی درون‌ریزی نهایی داده‌ها از جداول موقت به دیتابیس اصلی
    """
    from apps.jobs.models import JobOpportunity, JobOpportunityStage, WorkflowTemplate
    from apps.candidates.models import Candidate, JobApplication, ApplicationStageState
    
    logs = []
    def log_info(msg, sheet=None, row=None):
        ImportSessionLog.objects.create(import_session=import_session, level='INFO', message=msg, sheet_name=sheet, row_index=row)
    def log_warn(msg, sheet=None, row=None):
        ImportSessionLog.objects.create(import_session=import_session, level='WARNING', message=msg, sheet_name=sheet, row_index=row)
    def log_err(msg, sheet=None, row=None):
        ImportSessionLog.objects.create(import_session=import_session, level='ERROR', message=msg, sheet_name=sheet, row_index=row)

    log_info("شروع فرآیند تراکنشی ایمپورت سوابق تاریخی جذب...")

    mapping_config = import_session.mapping_config
    main_sheet = mapping_config.get('main_sheet')
    workflow_mappings = mapping_config.get('workflow_mappings', {})

    # ۱. پردازش فرصت‌های شغلی موقت
    staging_jobs = import_session.staging_jobs.filter(is_valid=True)
    job_map = {} # نقشه‌برداری کد شغل به شیء JobOpportunity واقعی
    
    for sj in staging_jobs:
        # بررسی وجود فرصت شغلی در سیستم
        existing_job = JobOpportunity.objects.filter(code=sj.job_code, is_deleted=False).first()
        job = None

        if existing_job:
            if conflict_strategy == 'SKIP':
                log_info(f"فرصت شغلی '{sj.title}' ({sj.job_code}) از قبل وجود دارد. طبق تنظیمات، نادیده گرفته شد.", main_sheet, sj.row_index)
                job_map[sj.job_code] = existing_job
                continue
            elif conflict_strategy == 'REPLACE':
                log_warn(f"فرصت شغلی '{sj.title}' ({sj.job_code}) از قبل وجود دارد. در حال حذف سوابق قبلی جهت جایگزینی...", main_sheet, sj.row_index)
                # حذف نرم درخواست‌های قبلی متصل به این شغل
                existing_job.applications.all().delete()
                # حذف نرم خود شغل
                existing_job.delete()
                # ایجاد مجدد
                job = None
            elif conflict_strategy == 'UPDATE':
                log_info(f"فرصت شغلی '{sj.title}' ({sj.job_code}) ویرایش و بروزرسانی شد.", main_sheet, sj.row_index)
                job = existing_job
                job.title = sj.title
                job.department = sj.department
                job.headcount = int(sj.headcount)
                job.save()

        if not job:
            # ایجاد فرصت شغلی جدید
            log_info(f"در حال ایجاد فرصت شغلی جدید: '{sj.title}' ({sj.job_code})", main_sheet, sj.row_index)
            
            # تعیین الگو
            wf_template = None
            wf_mapped_val = workflow_mappings.get(sj.workflow_pattern)
            
            if wf_mapped_val == 'auto_create':
                # ایجاد خودکار الگو بر اساس متن الگوی استخدام
                wf_name = f"الگوی خودکار - {sj.workflow_pattern}"
                wf_template = WorkflowTemplate.objects.filter(name=wf_name, is_deleted=False).first()
                if not wf_template:
                    wf_template = WorkflowTemplate.objects.create(name=wf_name, description="ایجاد شده خودکار توسط سیستم ایمپورت سوابق")
                    # تقسیم الگو به مراحل
                    parts = [p.strip() for p in sj.workflow_pattern.split('+')]
                    for seq, part in enumerate(parts, start=1):
                        # تشخیص نوع مرحله بر اساس کلمات کلیدی
                        s_type = 'OTHER'
                        part_lower = part.lower()
                        if any(kw in part_lower for kw in ["غربال", "screening"]):
                            s_type = 'SCREENING'
                        elif any(kw in part_lower for kw in ["آزمون", "کتبی", "exam", "test"]):
                            s_type = 'EXAM'
                        elif any(kw in part_lower for kw in ["مصاحبه", "interview"]):
                            s_type = 'INTERVIEW'
                        elif any(kw in part_lower for kw in ["کانون", "ارزیابی", "assessment"]):
                            s_type = 'ASSESSMENT'
                        
                        from apps.jobs.models import WorkflowStageTemplate
                        WorkflowStageTemplate.objects.create(
                            workflow=wf_template,
                            name=part,
                            sequence=seq,
                            stage_type=s_type,
                            default_weight=100 // len(parts) # تقسیم مساوی وزن
                        )
            elif wf_mapped_val:
                try:
                    wf_template = WorkflowTemplate.objects.get(id=int(wf_mapped_val), is_deleted=False)
                except (ValueError, WorkflowTemplate.DoesNotExist):
                    pass

            # پارس تاریخ شروع
            start_date = parse_date_safely(sj.start_date_str)

            job = JobOpportunity.objects.create(
                code=sj.job_code,
                request_number=sj.job_code,
                title=sj.title,
                department=sj.department,
                headcount=int(sj.headcount),
                workflow=wf_template,
                start_date=start_date,
                status=JobOpportunity.STATUS_RECEIVED, # وضعیت اولیه، بعداً بروزرسانی می‌شود
                assigned_recruiter=user,
                description=f"فرصت شغلی ایمپورت شده تاریخی از اکسل. الگوی اولیه: {sj.workflow_pattern}"
            )
            # متد JobOpportunity.save به طور خودکار مراحل را از الگو به JobOpportunityStage کپی می‌کند
            
        job_map[sj.job_code] = job
        sj.final_job = job
        sj.save(update_fields=['final_job'])

    # ۲. پردازش متقاضیان موقت
    staging_candidates = import_session.staging_candidates.filter(is_valid=True)
    
    # گروه‌بندی کاندیداها بر اساس کد ملی
    candidates_by_nid = {}
    for sc in staging_candidates:
        if sc.national_id not in candidates_by_nid:
            candidates_by_nid[sc.national_id] = []
        candidates_by_nid[sc.national_id].append(sc)

    for nid, sc_list in candidates_by_nid.items():
        sc_first = sc_list[0]
        
        # دریافت یا ایجاد متقاضی
        candidate = Candidate.objects.filter(national_id=nid, is_deleted=False).first()
        if not candidate:
            log_info(f"در حال ایجاد متقاضی جدید: {sc_first.first_name} {sc_first.last_name} ({nid})", sc_first.sheet_name, sc_first.row_index)
            candidate = Candidate.objects.create(
                national_id=nid,
                first_name=sc_first.first_name,
                last_name=sc_first.last_name,
                phone_number=sc_first.phone_number,
                email=sc_first.email
            )
        else:
            log_info(f"متقاضی '{candidate.first_name} {candidate.last_name}' با کد ملی '{nid}' از قبل وجود دارد. استفاده مجدد.", sc_first.sheet_name, sc_first.row_index)
            if sc_first.phone_number and not candidate.phone_number:
                candidate.phone_number = sc_first.phone_number
            if sc_first.email and not candidate.email:
                candidate.email = sc_first.email
            candidate.save()

        # ثبت درخواست همکاری
        jobs_for_cand = set(sc.job_code for sc in sc_list if sc.job_code in job_map)
        
        for jcode in jobs_for_cand:
            job = job_map[jcode]
            
            application = JobApplication.objects.filter(job=job, candidate=candidate, is_deleted=False).first()
            if not application:
                application = JobApplication.objects.create(
                    job=job,
                    candidate=candidate,
                    status=JobApplication.STATUS_IN_PROGRESS
                )
            
            # ثبت نمرات و وضعیت مراحل
            stages_for_job_and_cand = [sc for sc in sc_list if sc.job_code == jcode]
            
            for sc in stages_for_job_and_cand:
                # یافتن مرحله مربوط به فرصت شغلی
                job_stage = job.stages.filter(stage_type=sc.stage_type, is_deleted=False).first()
                if not job_stage:
                    job_stage = job.stages.filter(name__icontains=sc.sheet_name, is_deleted=False).first()

                if not job_stage:
                    log_warn(f"مرحله ارزیابی متناظر با شیت '{sc.sheet_name}' (نوع: {sc.stage_type}) برای فرصت شغلی '{job.title}' یافت نشد.", sc.sheet_name, sc.row_index)
                    continue

                stage_state, _ = ApplicationStageState.objects.get_or_create(
                    application=application,
                    stage=job_stage
                )
                
                stage_state.status = ApplicationStageState.STATUS_COMPLETED
                stage_state.score = float(sc.score) if sc.score else 0.0
                
                # تعیین تاریخ ارزیابی
                eval_date = parse_date_safely(sc.evaluation_date_str)
                if not eval_date:
                    eval_date = job.start_date
                
                stage_state.evaluation_date = eval_date
                stage_state.evaluator = user
                stage_state.save()

                log_info(f"ثبت موفق نمره {stage_state.score} در مرحله '{job_stage.name}' برای متقاضی '{candidate}'", sc.sheet_name, sc.row_index)

                # پاس کردن خودکار مراحل قبلی
                prior_stages = job.stages.filter(sequence__lt=job_stage.sequence, is_deleted=False)
                for ps in prior_stages:
                    ps_state, _ = ApplicationStageState.objects.get_or_create(
                        application=application,
                        stage=ps
                    )
                    if ps_state.status == ApplicationStageState.STATUS_PENDING:
                        ps_state.status = ApplicationStageState.STATUS_COMPLETED
                        ps_state.score = ps.passing_score
                        ps_state.evaluation_date = eval_date or job.start_date
                        ps_state.evaluator = user
                        ps_state.save()
                        log_info(f"پاس‌کردن خودکار مرحله قبلی '{ps.name}' به علت حضور متقاضی در مرحله بالاتر.", sc.sheet_name, sc.row_index)

            application.save()
            
            for sc in stages_for_job_and_cand:
                sc.final_candidate = candidate
                sc.save(update_fields=['final_candidate'])

    # ۳. بروزرسانی وضعیت نهایی کل فرصت‌های شغلی
    for job in job_map.values():
        job.update_status()

    log_info("فرآیند ایمپورت سوابق تاریخی جذب با موفقیت به پایان رسید.")
    import_session.status = 'COMPLETED'
    import_session.save(update_fields=['status'])

