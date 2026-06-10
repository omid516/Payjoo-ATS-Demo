from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from apps.accounts.permissions import RoleRequiredMixin
from apps.accounts.models import UserProfile
from apps.jobs.models import WorkflowTemplate
from .models import ImportSession, StagingJobOpportunity, StagingCandidate, ImportSessionLog
from .utils import analyze_excel_structure, parse_and_stage_data, execute_final_import

class UploadExcelView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN]
    template_name = 'historical_import/upload.html'

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            return render(request, self.template_name, {'error': 'لطفاً فایل اکسل را بارگذاری کنید.'})
        
        # بررسی فرمت فایل
        if not (excel_file.name.endswith('.xlsx') or excel_file.name.endswith('.xls')):
            return render(request, self.template_name, {'error': 'فرمت فایل باید Excel (.xlsx or .xls) باشد.'})

        # ایجاد نشست جدید
        import_session = ImportSession.objects.create(
            excel_file=excel_file,
            created_by=request.user,
            status='PENDING'
        )

        try:
            # تحلیل ساختار فایل به صورت همزمان
            analyze_excel_structure(import_session)
            return redirect('import_mapping', session_id=import_session.id)
        except Exception as e:
            return render(request, self.template_name, {'error': f'خطا در تحلیل ساختار فایل اکسل: {str(e)}'})


class MappingView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN]
    template_name = 'historical_import/mapping.html'

    def get(self, request, session_id):
        import_session = get_object_or_404(ImportSession, id=session_id)
        if import_session.status not in ['ANALYZED', 'MAPPED', 'PREVIEWED', 'COMPLETED', 'FAILED']:
            return redirect('import_upload')

        # بررسی اینکه آیا کاربر شیت اصلی یا ستون الگو را تغییر داده است
        selected_main_sheet = request.GET.get('main_sheet')
        selected_workflow_col = request.GET.get('workflow_col')

        if selected_main_sheet or selected_workflow_col:
            try:
                # تحلیل مجدد با پارامترهای ارسالی
                analyze_excel_structure(
                    import_session,
                    main_sheet_name=selected_main_sheet,
                    workflow_col_name=selected_workflow_col
                )
            except Exception:
                pass

        workflow_templates = WorkflowTemplate.objects.filter(is_deleted=False)
        context = {
            'session': import_session,
            'summary': import_session.summary_data,
            'workflow_templates': workflow_templates,
        }
        return render(request, self.template_name, context)

    def post(self, request, session_id):
        import_session = get_object_or_404(ImportSession, id=session_id)
        summary = import_session.summary_data
        
        # ۱. استخراج فیلدهای نگاشت فرصت شغلی
        job_fields = {
            'job_code': request.POST.get('job_code_col'),
            'title': request.POST.get('title_col'),
            'department': request.POST.get('department_col'),
            'headcount': request.POST.get('headcount_col'),
            'status': request.POST.get('status_col'),
            'start_date': request.POST.get('start_date_col'),
            'workflow_pattern': request.POST.get('workflow_pattern_col'),
        }

        # ۲. استخراج نگاشت‌های الگو
        workflow_mappings = {}
        patterns = summary.get('workflow_patterns', [])
        for pattern in patterns:
            key = f"workflow_map_{pattern}"
            val = request.POST.get(key)
            workflow_mappings[pattern] = val

        # ۳. استخراج نگاشت‌های شیت‌های مراحل
        stage_sheet_mappings = {}
        stage_sheets = summary.get('stage_sheets', [])
        for sheet in stage_sheets:
            s_name = sheet['name']
            stage_type = request.POST.get(f"stage_type_{s_name}")
            
            # اگر کاربر برای این شیت نوع مرحله انتخاب کرده باشد
            if stage_type and stage_type != 'IGNORE':
                stage_sheet_mappings[s_name] = {
                    'stage_type': stage_type,
                    'candidate_fields': {
                        'job_code': request.POST.get(f"c_job_code_col_{s_name}"),
                        'national_id': request.POST.get(f"c_national_id_col_{s_name}"),
                        'first_name': request.POST.get(f"c_first_name_col_{s_name}"),
                        'last_name': request.POST.get(f"c_last_name_col_{s_name}"),
                        'phone_number': request.POST.get(f"c_phone_number_col_{s_name}"),
                        'email': request.POST.get(f"c_email_col_{s_name}"),
                        'score': request.POST.get(f"c_score_col_{s_name}"),
                        'date': request.POST.get(f"c_date_col_{s_name}"),
                    }
                }

        # ساختار پیکربندی نگاشت نهایی
        mapping_config = {
            'main_sheet': summary.get('main_sheet'),
            'job_fields': job_fields,
            'workflow_mappings': workflow_mappings,
            'stage_sheet_mappings': stage_sheet_mappings,
        }

        try:
            # شروع استخراج داده‌ها به جداول موقت و اعتبارسنجی
            parse_and_stage_data(import_session, mapping_config)
            return redirect('import_preview', session_id=import_session.id)
        except Exception as e:
            workflow_templates = WorkflowTemplate.objects.filter(is_deleted=False)
            return render(request, self.template_name, {
                'session': import_session,
                'summary': summary,
                'workflow_templates': workflow_templates,
                'error': f'خطا در تحلیل و نگاشت داده‌ها: {str(e)}'
            })


class PreviewView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN]
    template_name = 'historical_import/preview.html'

    def get(self, request, session_id):
        import_session = get_object_or_404(ImportSession, id=session_id)
        if import_session.status != 'PREVIEWED':
            return redirect('import_mapping', session_id=import_session.id)

        # استخراج داده‌های موقت
        staging_jobs = import_session.staging_jobs.all()
        staging_candidates = import_session.staging_candidates.all()
        logs = import_session.logs.all()

        # محاسبه آمار خلاصه
        total_jobs_count = staging_jobs.count()
        valid_jobs_count = staging_jobs.filter(is_valid=True).count()
        invalid_jobs_count = staging_jobs.filter(is_valid=False).count()
        conflict_jobs_count = staging_jobs.filter(final_job__isnull=False).count()

        total_candidates_count = staging_candidates.count()
        valid_candidates_count = staging_candidates.filter(is_valid=True).count()
        invalid_candidates_count = staging_candidates.filter(is_valid=False).count()

        error_logs_count = logs.filter(level='ERROR').count()
        warning_logs_count = logs.filter(level='WARNING').count()

        context = {
            'session': import_session,
            'staging_jobs': staging_jobs,
            'staging_candidates': staging_candidates,
            'logs': logs,
            'stats': {
                'total_jobs': total_jobs_count,
                'valid_jobs': valid_jobs_count,
                'invalid_jobs': invalid_jobs_count,
                'conflict_jobs': conflict_jobs_count,
                'total_candidates': total_candidates_count,
                'valid_candidates': valid_candidates_count,
                'invalid_candidates': invalid_candidates_count,
                'errors': error_logs_count,
                'warnings': warning_logs_count,
            }
        }
        return render(request, self.template_name, context)

    def post(self, request, session_id):
        import_session = get_object_or_404(ImportSession, id=session_id)
        conflict_strategy = request.POST.get('conflict_strategy', 'UPDATE')

        try:
            execute_final_import(import_session, conflict_strategy, request.user)
            return redirect('import_success', session_id=import_session.id)
        except Exception as e:
            staging_jobs = import_session.staging_jobs.all()
            staging_candidates = import_session.staging_candidates.all()
            logs = import_session.logs.all()
            
            ImportSessionLog.objects.create(
                import_session=import_session,
                level='ERROR',
                message=f"خطای بحرانی در زمان اجرای نهایی ایمپورت: {str(e)}. پایگاه داده کاملاً Rollback شد."
            )

            return render(request, self.template_name, {
                'session': import_session,
                'staging_jobs': staging_jobs,
                'staging_candidates': staging_candidates,
                'logs': import_session.logs.all(),
                'error': f'خطای غیرمنتظره در ثبت پایگاه داده: {str(e)}'
            })


class SuccessView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN]
    template_name = 'historical_import/success.html'

    def get(self, request, session_id):
        import_session = get_object_or_404(ImportSession, id=session_id)
        logs = import_session.logs.all().order_by('id')
        
        # آمار نهایی
        imported_jobs = import_session.staging_jobs.filter(final_job__isnull=False).count()
        imported_candidates = import_session.staging_candidates.filter(final_candidate__isnull=False).count()

        context = {
            'session': import_session,
            'logs': logs,
            'stats': {
                'imported_jobs': imported_jobs,
                'imported_candidates': imported_candidates
            }
        }
        return render(request, self.template_name, context)
