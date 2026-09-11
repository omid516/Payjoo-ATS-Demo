import json
import uuid
import re
from datetime import datetime, date
import jdatetime
from django.utils import timezone
from django.db import transaction
from django.contrib.auth.models import User

from apps.jobs.models import (
    JobOpportunity, JobOpportunityStage, JobOpportunityCompetency,
    JobDescriptionTemplate, CompetencyModel, CompetencyModelItem
)
from apps.recruitment_planning.models import JobStagePlan
from apps.candidates.models import (
    Candidate, JobApplication, ApplicationStageState
)
from apps.core.models import AuditLog


def to_jalali_str(val, fmt='%Y/%m/%d %H:%M'):
    """
    تبدیل استاندارد انواع تاریخ و زمان (میلادی، ISO، شیء datetime) به تاریخ شمسی
    """
    if not val:
        return ''
    try:
        if isinstance(val, str):
            val_clean = val.replace('Z', '+00:00').strip()
            if 'T' in val_clean:
                dt = datetime.fromisoformat(val_clean)
            elif '-' in val_clean:
                parts = val_clean.split(' ')
                dpart = parts[0]
                tpart = parts[1] if len(parts) > 1 else '00:00:00'
                dt = datetime.strptime(f"{dpart} {tpart[:8]}", '%Y-%m-%d %H:%M:%S')
            elif '/' in val_clean:
                parts = val_clean.split(' ')
                dpart = parts[0]
                tpart = parts[1] if len(parts) > 1 else '00:00'
                dt = datetime.strptime(f"{dpart} {tpart}", '%Y/%m/%d %H:%M')
            else:
                return val
            val = dt

        if isinstance(val, datetime):
            if timezone.is_aware(val):
                val = timezone.localtime(val)
            jd = jdatetime.datetime.fromgregorian(datetime=val)
            return jd.strftime(fmt)
        elif isinstance(val, date):
            jd = jdatetime.date.fromgregorian(date=val)
            return jd.strftime('%Y/%m/%d')
    except Exception:
        pass
    return str(val)


def convert_text_dates_to_jalali(text):
    """
    جایگزینی هوشمند تاریخ‌های میلادی موجود در متن (مانند عنوان بسته) با معادل شمسی
    مثال: 'بسته تغییرات 2026/09/11 18:54' -> 'بسته تغییرات 1405/06/20 18:54'
    """
    if not text or not isinstance(text, str):
        return text

    def _replace_match(match):
        date_str = match.group(0)
        try:
            sep = '/' if '/' in date_str else '-'
            y, m, d = map(int, date_str.split(sep))
            if 2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
                jd = jdatetime.date.fromgregorian(year=y, month=m, day=d)
                return jd.strftime('%Y/%m/%d')
        except Exception:
            pass
        return date_str

    pattern = r'\b20\d{2}[-/](?:0[1-9]|1[0-2])[-/](?:0[1-9]|[12]\d|3[01])\b'
    return re.sub(pattern, _replace_match, text)


class SyncEngine:
    """
    موتور جامع استخراج، تحلیل تفاوت‌ها، حل تعارض و ادغام بسته‌های تغییرات سامانه
    """

    @classmethod
    def get_exportable_summary(cls, days=30):
        """
        دریافت خلاصه تمام آیتم‌های قابل انتخاب و استخراج برای ارسال به سرور
        همراه با تشخیص وضعیت ارسال قبلی به سرور (ارسال شده / جدید / ویرایش پس از ارسال)
        """
        from .models import SyncPackageHistory

        since = timezone.now() - timezone.timedelta(days=days)

        # استخراج کلیه سوابق بسته‌های همگام‌سازی (ارسالی و دریافتی از سرور)
        all_packages = SyncPackageHistory.objects.all().order_by('created_at')
        exported_job_times = {}
        exported_desc_times = {}
        exported_model_times = {}
        exported_score_times = {}
        exported_job_codes = {}
        exported_job_titles = {}
        exported_desc_codes = {}
        exported_desc_titles = {}
        exported_model_names = {}
        exported_score_keys = {}

        for pkg in all_packages:
            pkg_time = max(pkg.created_at, pkg.applied_at or pkg.created_at)
            payload = pkg.payload or {}
            sel = payload.get('selection', {})

            # ۱. از شناسه رکوردهای انتخاب‌شده
            if isinstance(sel, dict):
                for jid in sel.get('job_ids', []):
                    try:
                        jid_int = int(jid)
                        exported_job_times[jid_int] = max(exported_job_times.get(jid_int, pkg_time), pkg_time)
                    except (ValueError, TypeError): pass
                for did in sel.get('desc_ids', []):
                    try:
                        did_int = int(did)
                        exported_desc_times[did_int] = max(exported_desc_times.get(did_int, pkg_time), pkg_time)
                    except (ValueError, TypeError): pass
                for mid in sel.get('model_ids', []):
                    try:
                        mid_int = int(mid)
                        exported_model_times[mid_int] = max(exported_model_times.get(mid_int, pkg_time), pkg_time)
                    except (ValueError, TypeError): pass
                for sid in sel.get('score_ids', []):
                    try:
                        sid_int = int(sid)
                        exported_score_times[sid_int] = max(exported_score_times.get(sid_int, pkg_time), pkg_time)
                    except (ValueError, TypeError): pass

            # ۲. از بدنه داده‌ها (کدهای یکتا و عناوین) برای تمامی بسته‌های ورودی/خروجی
            pdata = payload.get('data', {}) if isinstance(payload, dict) else {}
            if isinstance(pdata, dict):
                for j in pdata.get('jobs', []):
                    code = j.get('code')
                    title = j.get('title', '').strip()
                    dept = (j.get('department') or '').strip()
                    if code:
                        exported_job_codes[code] = max(exported_job_codes.get(code, pkg_time), pkg_time)
                    if title:
                        exported_job_titles[(title, dept)] = max(exported_job_titles.get((title, dept), pkg_time), pkg_time)
                        exported_job_titles[title] = max(exported_job_titles.get(title, pkg_time), pkg_time)

                for d in pdata.get('job_descriptions', []):
                    jcode = d.get('job_code')
                    dtitle = (d.get('title') or '').strip()
                    if jcode:
                        exported_desc_codes[jcode] = max(exported_desc_codes.get(jcode, pkg_time), pkg_time)
                    if dtitle:
                        exported_desc_titles[dtitle] = max(exported_desc_titles.get(dtitle, pkg_time), pkg_time)

                for m in pdata.get('competency_models', []):
                    mname = (m.get('name') or '').strip()
                    if mname:
                        exported_model_names[mname] = max(exported_model_names.get(mname, pkg_time), pkg_time)

                for s in pdata.get('scores', []):
                    nid = s.get('national_id')
                    stg = s.get('stage_name')
                    if nid and stg:
                        skey = f"{nid}_{stg}"
                        exported_score_keys[skey] = max(exported_score_keys.get(skey, pkg_time), pkg_time)

        def _calc_status(obj_id, code_or_key, title_or_tuple, updated_at, id_map, code_map, title_map=None):
            last_sent = (
                id_map.get(obj_id) or
                (code_map.get(code_or_key) if code_or_key else None) or
                (title_map.get(title_or_tuple) if (title_map and title_or_tuple) else None)
            )
            if not last_sent:
                return {
                    'export_status': 'UNSENT',
                    'is_exported': False,
                    'status_label': '✨ جدید / ارسال نشده',
                    'status_class': 'badge bg-primary bg-opacity-10 text-primary border border-primary border-opacity-25',
                    'last_exported_at': None
                }
            # اگر زمان ویرایش بیش از ۶۰ ثانیه بعد از آخرین همگام‌سازی باشد (ویرایش واقعی پس از همگام‌سازی)
            elif updated_at > (last_sent + timezone.timedelta(seconds=60)):
                return {
                    'export_status': 'MODIFIED',
                    'is_exported': False,
                    'status_label': '🔄 ویرایش پس از ارسال',
                    'status_class': 'badge bg-warning bg-opacity-10 text-warning border border-warning border-opacity-25',
                    'last_exported_at': to_jalali_str(last_sent)
                }
            else:
                return {
                    'export_status': 'SENT',
                    'is_exported': True,
                    'status_label': '📤 ارسال شده',
                    'status_class': 'badge bg-secondary bg-opacity-10 text-secondary border',
                    'last_exported_at': to_jalali_str(last_sent)
                }

        # 1. فرصت‌های شغلی اخیر
        jobs = JobOpportunity.all_objects.filter(updated_at__gte=since).order_by('-updated_at')[:50]
        jobs_list = []
        for j in jobs:
            st = _calc_status(
                j.id,
                j.code,
                (j.title.strip(), (j.department or '').strip()) if j.title else None,
                j.updated_at,
                exported_job_times,
                exported_job_codes,
                exported_job_titles
            )
            jobs_list.append({
                'id': j.id,
                'title': j.title,
                'code': j.code or '',
                'request_number': j.request_number or '',
                'department': j.department or 'نامشخص',
                'capacity': j.headcount,
                'status': j.status,
                'updated_at': to_jalali_str(j.updated_at),
                'is_deleted': j.is_deleted,
                'export_status': st['export_status'],
                'is_exported': st['is_exported'],
                'status_label': st['status_label'],
                'status_class': st['status_class'],
                'last_exported_at': st['last_exported_at'],
            })

        # 2. شناسنامه‌های شغل اخیر
        templates = JobDescriptionTemplate.all_objects.filter(updated_at__gte=since).order_by('-updated_at')[:50]
        templates_list = []
        for t in templates:
            st = _calc_status(
                t.id,
                t.job_code,
                t.title.strip() if t.title else None,
                t.updated_at,
                exported_desc_times,
                exported_desc_codes,
                exported_desc_titles
            )
            templates_list.append({
                'id': t.id,
                'job_code': t.job_code,
                'title': t.title,
                'department': t.department or '',
                'updated_at': to_jalali_str(t.updated_at),
                'export_status': st['export_status'],
                'is_exported': st['is_exported'],
                'status_label': st['status_label'],
                'status_class': st['status_class'],
                'last_exported_at': st['last_exported_at'],
            })

        # 3. مدل‌های شایستگی
        models = CompetencyModel.all_objects.filter(updated_at__gte=since).order_by('-updated_at')[:30]
        models_list = []
        for m in models:
            st = _calc_status(
                m.id,
                m.name.strip() if m.name else None,
                None,
                m.updated_at,
                exported_model_times,
                exported_model_names,
                None
            )
            models_list.append({
                'id': m.id,
                'name': m.name,
                'description': m.description or '',
                'updated_at': to_jalali_str(m.updated_at),
                'export_status': st['export_status'],
                'is_exported': st['is_exported'],
                'status_label': st['status_label'],
                'status_class': st['status_class'],
                'last_exported_at': st['last_exported_at'],
            })

        # 4. نمرات و ارزیابی‌های اخیر
        recent_states = ApplicationStageState.all_objects.filter(
            updated_at__gte=since,
            score__isnull=False
        ).select_related('application__candidate', 'application__job', 'stage').order_by('-updated_at')[:100]

        scores_list = []
        for s in recent_states:
            cand = s.application.candidate if s.application else None
            job = s.application.job if s.application else None
            cand_name = f"{cand.first_name} {cand.last_name}".strip() if cand else 'نامشخص'
            skey = f"{cand.national_id}_{s.stage.name}" if (cand and s.stage) else None
            st = _calc_status(
                s.id,
                skey,
                None,
                s.updated_at,
                exported_score_times,
                exported_score_keys,
                None
            )
            scores_list.append({
                'id': s.id,
                'candidate_name': cand_name,
                'national_id': cand.national_id if cand else '',
                'job_title': job.title if job else '',
                'stage_name': s.stage.name if s.stage else '',
                'score': float(s.score) if s.score is not None else None,
                'status': s.status,
                'updated_at': to_jalali_str(s.updated_at),
                'export_status': st['export_status'],
                'is_exported': st['is_exported'],
                'status_label': st['status_label'],
                'status_class': st['status_class'],
                'last_exported_at': st['last_exported_at'],
            })

        unsent_jobs = sum(1 for j in jobs_list if j['export_status'] in ('UNSENT', 'MODIFIED'))
        unsent_descs = sum(1 for d in templates_list if d['export_status'] in ('UNSENT', 'MODIFIED'))
        unsent_scores = sum(1 for s in scores_list if s['export_status'] in ('UNSENT', 'MODIFIED'))
        total_items = len(jobs_list) + len(templates_list) + len(scores_list)
        total_unsent = unsent_jobs + unsent_descs + unsent_scores

        return {
            'jobs': jobs_list,
            'job_descriptions': templates_list,
            'competency_models': models_list,
            'scores': scores_list,
            'counts': {
                'total': total_items,
                'unsent_total': total_unsent,
                'sent_total': total_items - total_unsent,
                'unsent_jobs': unsent_jobs,
                'unsent_descs': unsent_descs,
                'unsent_scores': unsent_scores,
            }
        }

    @classmethod
    def export_package(cls, author, title, selection=None):
        """
        تولید پکیج ساخت‌یافته JSON شامل موجودیت‌های انتخاب‌شده
        """
        selection = selection or {}
        selected_job_ids = selection.get('job_ids', [])
        selected_desc_ids = selection.get('desc_ids', [])
        selected_model_ids = selection.get('model_ids', [])
        selected_score_ids = selection.get('score_ids', [])

        payload_data = {
            'jobs': [],
            'job_descriptions': [],
            'competency_models': [],
            'scores': [],
        }

        # 1. استخراج فرصت‌های شغلی همراه با مراحل و شایستگی‌ها
        if selected_job_ids:
            jobs_qs = JobOpportunity.all_objects.filter(id__in=selected_job_ids)
            for j in jobs_qs:
                stages_data = []
                for st in j.stages.all().order_by('sequence'):
                    stages_data.append({
                        'name': st.name,
                        'stage_type': st.stage_type,
                        'sequence': st.sequence,
                        'weight': float(st.weight),
                        'passing_score': float(st.passing_score) if st.passing_score else None,
                    })

                competencies_data = []
                for c in j.selected_competencies.all():
                    competencies_data.append({
                        'code': c.code,
                        'title': c.title,
                        'competency_type': c.competency_type,
                    })

                payload_data['jobs'].append({
                    'guid': str(uuid.uuid4()),
                    'title': j.title,
                    'code': j.code or f"JOB-{j.id}",
                    'request_number': j.request_number or f"REQ-{j.id}",
                    'department': j.department,
                    'unit': j.unit or '',
                    'capacity': j.headcount,
                    'status': j.status,
                    'description': j.description,
                    'stages': stages_data,
                    'competencies': competencies_data,
                    'is_deleted': j.is_deleted,
                })

        # 2. استخراج شناسنامه‌های شغل
        if selected_desc_ids:
            descs_qs = JobDescriptionTemplate.all_objects.filter(id__in=selected_desc_ids)
            for d in descs_qs:
                payload_data['job_descriptions'].append({
                    'job_code': d.job_code,
                    'title': d.title,
                    'department': d.department,
                    'deputy': d.deputy,
                    'job_family': d.job_family,
                    'job_category': d.job_category,
                    'description': d.description,
                    'job_type_details': d.job_type_details,
                    'general_goal': d.general_goal,
                    'expected_results': d.expected_results,
                    'is_deleted': d.is_deleted,
                })

        # 3. استخراج مدل‌های شایستگی
        if selected_model_ids:
            models_qs = CompetencyModel.all_objects.filter(id__in=selected_model_ids)
            for m in models_qs:
                items_data = []
                for it in m.items.all():
                    items_data.append({
                        'title': it.title,
                        'competency_type': it.competency_type,
                        'importance': it.importance,
                        'level': it.level,
                    })
                payload_data['competency_models'].append({
                    'name': m.name,
                    'description': m.description,
                    'items': items_data,
                    'is_deleted': m.is_deleted,
                })

        # 4. استخراج نمرات و ارزیابی‌ها بر پایه کد ملی کارجو
        if selected_score_ids:
            scores_qs = ApplicationStageState.all_objects.filter(
                id__in=selected_score_ids
            ).select_related('application__candidate', 'application__job', 'stage')

            for s in scores_qs:
                cand = s.application.candidate if s.application else None
                job = s.application.job if s.application else None
                if cand:
                    cand_name = f"{cand.first_name} {cand.last_name}".strip()
                    payload_data['scores'].append({
                        'national_id': cand.national_id,
                        'candidate_name': cand_name,
                        'job_title': job.title if job else '',
                        'stage_name': s.stage.name if s.stage else '',
                        'stage_sequence': s.stage.sequence if s.stage else 1,
                        'score': float(s.score) if s.score is not None else None,
                        'status': s.status,
                        'notes': s.notes or '',
                    })

        package_id = f"pkg_{uuid.uuid4().hex[:12]}"
        jalali_now_str = to_jalali_str(timezone.now())
        clean_title = convert_text_dates_to_jalali(title) if title else f"بسته تغییرات {jalali_now_str}"

        package = {
            'package_id': package_id,
            'version': '1.0',
            'author': author or 'کارشناس تامین سرمایه انسانی',
            'title': clean_title,
            'created_at': timezone.now().isoformat(),
            'created_at_jalali': jalali_now_str,
            'selection': selection,
            'summary': {
                'jobs': len(payload_data['jobs']),
                'job_descriptions': len(payload_data['job_descriptions']),
                'competency_models': len(payload_data['competency_models']),
                'scores': len(payload_data['scores']),
            },
            'data': payload_data,
        }

        return package

    @classmethod
    def analyze_package_diff(cls, package_data):
        """
        مقایسه هوشمند بسته ورودی با دیتابیس محلی (پایش تغییرات واقعی، کشف تکرارها و ارزیابی نیاز به ثبت)
        """
        data = package_data.get('data', {})
        diff = {
            'jobs': [],
            'job_descriptions': [],
            'competency_models': [],
            'scores': [],
            'has_conflicts': False,
            'total_items': 0,
            'needed_items': 0,
            'identical_items': 0,
            'is_all_identical': False,
            'scan_verdict': '',
        }

        # 1. پایش فرصت‌های شغلی
        for j in data.get('jobs', []):
            diff['total_items'] += 1
            existing = (
                JobOpportunity.objects.filter(code=j.get('code')).first() if j.get('code') else None
            ) or (
                JobOpportunity.objects.filter(title=j.get('title'), department=j.get('department')).first()
            ) or (
                JobOpportunity.all_objects.filter(title=j.get('title'), department=j.get('department')).first()
            )

            if not existing:
                diff['needed_items'] += 1
                diff['jobs'].append({
                    'action': 'NEW',
                    'is_needed': True,
                    'badge': '🟢 جدید',
                    'title': j.get('title'),
                    'department': j.get('department') or 'نامشخص',
                    'capacity': j.get('capacity', 1),
                    'stages_count': len(j.get('stages', [])),
                    'competencies_count': len(j.get('competencies', [])),
                    'details': f"ایجاد فرصت شغلی جدید با {len(j.get('stages', []))} مرحله ارزیابی",
                })
            else:
                is_changed = (
                    existing.headcount != j.get('capacity', 1) or
                    existing.status != j.get('status', 'PLANNING')
                )
                if is_changed:
                    diff['needed_items'] += 1
                    diff['jobs'].append({
                        'action': 'UPDATE',
                        'is_needed': True,
                        'badge': '🔄 تغییر یافته',
                        'title': j.get('title'),
                        'department': j.get('department') or 'نامشخص',
                        'capacity': f"فعلی: {existing.headcount} ← جدید: {j.get('capacity')}",
                        'stages_count': len(j.get('stages', [])),
                        'competencies_count': len(j.get('competencies', [])),
                        'details': f"به‌روزرسانی فرصت شغلی #{existing.id} (ظرفیت یا وضعیت تغییر کرده است)",
                    })
                    diff['has_conflicts'] = True
                else:
                    diff['identical_items'] += 1
                    diff['jobs'].append({
                        'action': 'IDENTICAL',
                        'is_needed': False,
                        'badge': '⚪️ بدون تغییر',
                        'title': j.get('title'),
                        'department': j.get('department') or 'نامشخص',
                        'capacity': f"{existing.headcount} نفر",
                        'stages_count': len(j.get('stages', [])),
                        'competencies_count': len(j.get('competencies', [])),
                        'details': f"این فرصت با همین مشخصات در دیتابیس موجود است (بدون نیاز به ثبت مجدد)",
                    })

        # 2. پایش شناسنامه‌های شغل
        for d in data.get('job_descriptions', []):
            diff['total_items'] += 1
            existing = (
                JobDescriptionTemplate.objects.filter(job_code=d.get('job_code')).first() or
                JobDescriptionTemplate.all_objects.filter(job_code=d.get('job_code')).first()
            )
            if not existing:
                diff['needed_items'] += 1
                diff['job_descriptions'].append({
                    'action': 'NEW',
                    'is_needed': True,
                    'badge': '🟢 جدید',
                    'job_code': d.get('job_code'),
                    'title': d.get('title'),
                    'department': d.get('department') or '',
                    'details': 'ثبت شناسنامه استاندارد شغل جدید',
                })
            else:
                is_changed = (
                    existing.title != d.get('title') or
                    (existing.description or '').strip() != (d.get('description') or '').strip()
                )
                if is_changed:
                    diff['needed_items'] += 1
                    diff['job_descriptions'].append({
                        'action': 'UPDATE',
                        'is_needed': True,
                        'badge': '🔄 ویرایش متن',
                        'job_code': d.get('job_code'),
                        'title': d.get('title'),
                        'department': d.get('department') or '',
                        'details': 'شرح وظایف یا عنوان دارای متن جدید است',
                    })
                else:
                    diff['identical_items'] += 1
                    diff['job_descriptions'].append({
                        'action': 'IDENTICAL',
                        'is_needed': False,
                        'badge': '⚪️ بدون تغییر',
                        'job_code': d.get('job_code'),
                        'title': d.get('title'),
                        'department': d.get('department') or '',
                        'details': 'شناسنامه دقیقاً با همین مشخصات در دیتابیس وجود دارد',
                    })

        # 3. پایش مدل‌های شایستگی
        for m in data.get('competency_models', []):
            diff['total_items'] += 1
            existing = (
                CompetencyModel.objects.filter(name=m.get('name')).first() or
                CompetencyModel.all_objects.filter(name=m.get('name')).first()
            )
            if not existing:
                diff['needed_items'] += 1
                diff['competency_models'].append({
                    'action': 'NEW',
                    'is_needed': True,
                    'badge': '🟢 جدید',
                    'name': m.get('name'),
                    'items_count': len(m.get('items', [])),
                    'details': f"شامل {len(m.get('items', []))} شاخص شایستگی جدید",
                })
            else:
                diff['identical_items'] += 1
                diff['competency_models'].append({
                    'action': 'IDENTICAL',
                    'is_needed': False,
                    'badge': '⚪️ بدون تغییر',
                    'name': m.get('name'),
                    'items_count': len(m.get('items', [])),
                    'details': 'مدل شایستگی در سیستم موجود است',
                })

        # 4. پایش نمرات و ارزیابی‌ها
        for sc in data.get('scores', []):
            diff['total_items'] += 1
            cand = (
                Candidate.objects.filter(national_id=sc.get('national_id')).first() or
                Candidate.all_objects.filter(national_id=sc.get('national_id')).first()
            )
            new_score = sc.get('score')
            new_status = sc.get('status')

            if cand:
                cand_name = f"{cand.first_name} {cand.last_name}".strip()
                job = (
                    JobOpportunity.objects.filter(title=sc.get('job_title')).first() or
                    JobOpportunity.all_objects.filter(title=sc.get('job_title')).first()
                )
                existing_state = None
                if job:
                    stage = job.stages.filter(name=sc.get('stage_name')).first()
                    if stage:
                        app = (
                            JobApplication.objects.filter(candidate=cand, job=job).first() or
                            JobApplication.all_objects.filter(candidate=cand, job=job).first()
                        )
                        if app:
                            existing_state = (
                                ApplicationStageState.objects.filter(application=app, stage=stage).first() or
                                ApplicationStageState.all_objects.filter(application=app, stage=stage).first()
                            )

                if existing_state:
                    current_score = float(existing_state.score) if existing_state.score is not None else None
                    target_score = float(new_score) if new_score is not None else None

                    if current_score == target_score and existing_state.status == new_status:
                        diff['identical_items'] += 1
                        diff['scores'].append({
                            'action': 'IDENTICAL',
                            'is_needed': False,
                            'badge': '⚪️ نمره یکسان',
                            'candidate': f"{cand_name} ({cand.national_id})",
                            'job': sc.get('job_title'),
                            'stage': sc.get('stage_name'),
                            'new_score': new_score,
                            'new_status': new_status,
                            'details': f"این نمره ({new_score}) و وضعیت از قبل در سیستم با همین مقدار ثبت است",
                        })
                    else:
                        diff['needed_items'] += 1
                        diff['scores'].append({
                            'action': 'UPDATE',
                            'is_needed': True,
                            'badge': '🔄 تغییر نمره',
                            'candidate': f"{cand_name} ({cand.national_id})",
                            'job': sc.get('job_title'),
                            'stage': sc.get('stage_name'),
                            'new_score': new_score,
                            'new_status': new_status,
                            'details': f"نمره فعلی: {current_score} ← نمره ارسالی جدید: {new_score}",
                        })
                else:
                    diff['needed_items'] += 1
                    diff['scores'].append({
                        'action': 'NEW',
                        'is_needed': True,
                        'badge': '🎯 ثبت نمره جدید',
                        'candidate': f"{cand_name} ({cand.national_id})",
                        'job': sc.get('job_title'),
                        'stage': sc.get('stage_name'),
                        'new_score': new_score,
                        'new_status': new_status,
                        'details': f"نمره: {new_score} | وضعیت: {new_status}",
                    })
            else:
                diff['needed_items'] += 1
                diff['scores'].append({
                    'action': 'NEW_CANDIDATE',
                    'is_needed': True,
                    'badge': '👤 کارجو و نمره جدید',
                    'candidate': f"{sc.get('candidate_name', '')} ({sc.get('national_id')})",
                    'job': sc.get('job_title'),
                    'stage': sc.get('stage_name'),
                    'new_score': new_score,
                    'new_status': new_status,
                    'details': 'کارجو و نمره ارزیابی در سیستم ایجاد خواهد شد.',
                })

        # نتیجه‌گیری کلی پایش هوشمند
        diff['is_all_identical'] = (diff['total_items'] > 0 and diff['needed_items'] == 0)
        if diff['total_items'] == 0:
            diff['scan_verdict'] = 'بسته فاقد هرگونه داده است.'
        elif diff['is_all_identical']:
            diff['scan_verdict'] = f"💡 نتیجه پایش: تمام {diff['total_items']} مورد این بسته از قبل با همین مشخصات در دیتابیس شما وجود دارند و نیازی به ذخیره‌سازی مجدد نیست."
        else:
            diff['scan_verdict'] = f"🔍 نتیجه پایش هوشمند: از مجموع {diff['total_items']} مورد، {diff['needed_items']} مورد نیازمند ثبت/به‌روزرسانی و {diff['identical_items']} مورد از قبل در سیستم یکسان است."

        return diff

    @classmethod
    @transaction.atomic
    def apply_package(cls, package_data, applied_by='مدیر سیستم'):
        """
        اعمال قطعی و تراکنشی تغییرات پکیج در پایگاه‌داده محلی
        به همراه پیشگیری کامل از خطای MultipleObjectsReturned و همگام‌سازی تمیز
        """
        data = package_data.get('data', {})
        results = {
            'jobs_created': 0,
            'jobs_updated': 0,
            'descriptions_saved': 0,
            'models_saved': 0,
            'scores_applied': 0,
            'candidates_created': 0,
        }

        # 1. اعمال فرصت‌های شغلی
        for j in data.get('jobs', []):
            job_code = j.get('code') or f"JOB-{uuid.uuid4().hex[:6].upper()}"
            req_num = j.get('request_number') or f"REQ-{uuid.uuid4().hex[:6].upper()}"
            title = j.get('title', '').strip()
            department = j.get('department', 'عمومی')

            # جستجوی امن فرصت شغلی موجود (بدون get_or_create تا خطای MultipleObjectsReturned رخ ندهد)
            job_obj = None
            if job_code:
                job_obj = JobOpportunity.objects.filter(code=job_code).first()
            if not job_obj and req_num:
                job_obj = JobOpportunity.objects.filter(request_number=req_num).first()
            if not job_obj and title:
                job_obj = JobOpportunity.objects.filter(title=title, department=department).first()

            # اگر در رکوردهای فعال نبود، در کل رکوردها (حذف نرم شده) بررسی می‌کنیم تا بازیابی شود
            if not job_obj:
                if job_code:
                    job_obj = JobOpportunity.all_objects.filter(code=job_code).first()
                if not job_obj and req_num:
                    job_obj = JobOpportunity.all_objects.filter(request_number=req_num).first()
                if not job_obj and title:
                    job_obj = JobOpportunity.all_objects.filter(title=title, department=department).first()

            if job_obj:
                job_obj.is_deleted = False
                job_obj.headcount = j.get('capacity', job_obj.headcount)
                job_obj.status = j.get('status', job_obj.status)
                if j.get('description'):
                    job_obj.description = j['description']
                if j.get('unit'):
                    job_obj.unit = j['unit']
                job_obj.save()
                results['jobs_updated'] += 1
            else:
                job_obj = JobOpportunity.objects.create(
                    title=title,
                    code=job_code,
                    request_number=req_num,
                    department=department,
                    unit=j.get('unit', ''),
                    headcount=j.get('capacity', 1),
                    status=j.get('status', 'PLANNING'),
                    description=j.get('description', ''),
                )
                results['jobs_created'] += 1

            # افزودن یا به‌روزرسانی مراحل
            for st in j.get('stages', []):
                st_name = st.get('name', '').strip()
                st_seq = st.get('sequence', 1)
                existing_stage = (
                    job_obj.stages.filter(sequence=st_seq).first() or
                    job_obj.stages.filter(name=st_name).first()
                )
                if not existing_stage:
                    JobOpportunityStage.objects.create(
                        job=job_obj,
                        name=st_name,
                        sequence=st_seq,
                        stage_type=st.get('stage_type', 'INTERVIEW'),
                        weight=st.get('weight', 0),
                        passing_score=st.get('passing_score'),
                    )
                else:
                    existing_stage.weight = st.get('weight', existing_stage.weight)
                    if st.get('passing_score') is not None:
                        existing_stage.passing_score = st.get('passing_score')
                    existing_stage.save()

        # 2. اعمال شناسنامه‌های شغل
        for d in data.get('job_descriptions', []):
            jcode = d.get('job_code')
            if not jcode:
                continue
            desc_obj = (
                JobDescriptionTemplate.objects.filter(job_code=jcode).first() or
                JobDescriptionTemplate.all_objects.filter(job_code=jcode).first()
            )
            if desc_obj:
                desc_obj.is_deleted = False
                desc_obj.title = d.get('title', desc_obj.title)
                desc_obj.department = d.get('department', desc_obj.department)
                desc_obj.deputy = d.get('deputy', desc_obj.deputy)
                desc_obj.job_family = d.get('job_family', desc_obj.job_family)
                desc_obj.job_category = d.get('job_category', desc_obj.job_category)
                desc_obj.description = d.get('description', desc_obj.description)
                desc_obj.job_type_details = d.get('job_type_details', desc_obj.job_type_details)
                desc_obj.general_goal = d.get('general_goal', desc_obj.general_goal)
                desc_obj.expected_results = d.get('expected_results', desc_obj.expected_results)
                desc_obj.save()
            else:
                JobDescriptionTemplate.objects.create(
                    job_code=jcode,
                    title=d.get('title', ''),
                    department=d.get('department', ''),
                    deputy=d.get('deputy', ''),
                    job_family=d.get('job_family', ''),
                    job_category=d.get('job_category', ''),
                    description=d.get('description', ''),
                    job_type_details=d.get('job_type_details', ''),
                    general_goal=d.get('general_goal', ''),
                    expected_results=d.get('expected_results', ''),
                )
            results['descriptions_saved'] += 1

        # 3. اعمال مدل‌های شایستگی
        for m in data.get('competency_models', []):
            mname = m.get('name', '').strip()
            if not mname:
                continue
            model_obj = (
                CompetencyModel.objects.filter(name=mname).first() or
                CompetencyModel.all_objects.filter(name=mname).first()
            )
            if not model_obj:
                model_obj = CompetencyModel.objects.create(
                    name=mname,
                    description=m.get('description', '')
                )
            else:
                model_obj.is_deleted = False
                if m.get('description'):
                    model_obj.description = m['description']
                model_obj.save()

            for it in m.get('items', []):
                it_title = it.get('title', '').strip()
                if not it_title:
                    continue
                item_obj = (
                    CompetencyModelItem.objects.filter(competency_model=model_obj, title=it_title).first() or
                    CompetencyModelItem.all_objects.filter(competency_model=model_obj, title=it_title).first()
                )
                if not item_obj:
                    CompetencyModelItem.objects.create(
                        competency_model=model_obj,
                        title=it_title,
                        competency_type=it.get('competency_type', 'GE'),
                        importance=it.get('importance', 1),
                        level=it.get('level', 1),
                    )
                else:
                    item_obj.is_deleted = False
                    item_obj.competency_type = it.get('competency_type', item_obj.competency_type)
                    item_obj.importance = it.get('importance', item_obj.importance)
                    item_obj.level = it.get('level', item_obj.level)
                    item_obj.save()
            results['models_saved'] += 1

        # 4. اعمال نمرات و کارجویان
        for sc in data.get('scores', []):
            nat_code = sc.get('national_id')
            if not nat_code:
                continue

            cand = (
                Candidate.objects.filter(national_id=nat_code).first() or
                Candidate.all_objects.filter(national_id=nat_code).first()
            )
            if not cand:
                cand_name = sc.get('candidate_name', '').strip()
                first_name = cand_name.split(' ')[0] if cand_name else 'کارجو'
                last_name = ' '.join(cand_name.split(' ')[1:]) if (cand_name and len(cand_name.split(' ')) > 1) else nat_code
                cand = Candidate.objects.create(
                    national_id=nat_code,
                    first_name=first_name,
                    last_name=last_name,
                )
                results['candidates_created'] += 1
            else:
                if cand.is_deleted:
                    cand.is_deleted = False
                    cand.save()

            # یافتن فرصت شغلی
            job = None
            if sc.get('job_title'):
                job = (
                    JobOpportunity.objects.filter(title=sc['job_title']).first() or
                    JobOpportunity.all_objects.filter(title=sc['job_title']).first()
                )
            if not job:
                job = JobOpportunity.objects.first() or JobOpportunity.all_objects.first()

            if job:
                app = (
                    JobApplication.objects.filter(candidate=cand, job=job).first() or
                    JobApplication.all_objects.filter(candidate=cand, job=job).first()
                )
                if not app:
                    app = JobApplication.objects.create(
                        candidate=cand,
                        job=job,
                        status='UNDER_REVIEW'
                    )
                else:
                    if app.is_deleted:
                        app.is_deleted = False
                        app.save()

                stage_name = sc.get('stage_name')
                stage = None
                if stage_name:
                    stage = job.stages.filter(name=stage_name).first()
                if not stage:
                    stage = job.stages.first()

                if stage:
                    state = (
                        ApplicationStageState.objects.filter(application=app, stage=stage).first() or
                        ApplicationStageState.all_objects.filter(application=app, stage=stage).first()
                    )
                    if not state:
                        state = ApplicationStageState.objects.create(
                            application=app,
                            stage=stage,
                        )
                    if sc.get('score') is not None:
                        state.score = sc['score']
                    if sc.get('status'):
                        state.status = sc['status']
                    if sc.get('notes'):
                        state.notes = sc['notes']
                    state.save()
                    results['scores_applied'] += 1

        return results
