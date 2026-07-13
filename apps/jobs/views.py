from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, CreateView, UpdateView
from django.views import View
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.db import transaction
from django.utils import timezone

from apps.accounts.permissions import RoleRequiredMixin
from apps.accounts.models import UserProfile
from .models import JobOpportunity, JobOpportunityStage, WorkflowTemplate, WorkflowStageTemplate, CompetencyModel
from .forms import JobOpportunityForm, JobOpportunityFormSet, WorkflowTemplateForm, WorkflowStageTemplateFormSet

def normalize_digits(s):
    if not s:
        return ''
    s = str(s).strip()
    for fa, en in zip('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'):
        s = s.replace(fa, en)
    return s


def apply_job_filters(queryset, params):
    from django.db.models import Q
    
    q = params.get('q', '').strip()
    
    def get_clean_list(key):
        vals = params.getlist(key)
        if len(vals) == 1 and ',' in vals[0]:
            vals = vals[0].split(',')
        return [v.strip() for v in vals if v.strip()]

    statuses = get_clean_list('status')
    departments = get_clean_list('department')
    units = get_clean_list('unit')
    sources = get_clean_list('source')
    recruitment_types = get_clean_list('recruitment_type')
    job_categories = get_clean_list('job_category')
    
    if q:
        q_norm = normalize_digits(q)
        queryset = queryset.filter(
            Q(title__icontains=q) | 
            Q(code__icontains=q) | 
            Q(code__icontains=q_norm) |
            Q(request_number__icontains=q) |
            Q(request_number__icontains=q_norm)
        )
    if statuses:
        queryset = queryset.filter(status__in=statuses)
    if departments:
        queryset = queryset.filter(department__in=departments)
    if units:
        queryset = queryset.filter(unit__in=units)
    if sources:
        queryset = queryset.filter(source__in=sources)
    if recruitment_types:
        queryset = queryset.filter(recruitment_type__in=recruitment_types)
    if job_categories:
        queryset = queryset.filter(job_category__in=job_categories)
        
    return queryset


class JobOpportunityListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = JobOpportunity
    template_name = 'jobs/job_list.html'
    context_object_name = 'jobs'
    paginate_by = 10
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
        UserProfile.ROLE_DEPARTMENT_USER,
        UserProfile.ROLE_READ_ONLY_AUDITOR,
    ]

    def dispatch(self, request, *args, **kwargs):
        from django.urls import reverse
        from django.shortcuts import redirect

        # 1. Clear filters if explicitly requested
        if 'clear' in request.GET:
            request.session.pop('jobs_filter_params', None)
            return redirect('job_list')

        # 2. Check if request has any query parameters
        has_params = any(k for k in request.GET.keys())

        if has_params:
            # Save query params to session
            request.session['jobs_filter_params'] = request.GET.urlencode()
        else:
            # Restore saved query params from session if available
            saved_params = request.session.get('jobs_filter_params')
            if saved_params:
                return redirect(f"{reverse('job_list')}?{saved_params}")

        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        from django.db.models import Count, Q
        queryset = JobOpportunity.objects.filter(is_deleted=False)
        queryset = apply_job_filters(queryset, self.request.GET)
        
        sort_by = self.request.GET.get('sort', 'created_at').strip()
        order = self.request.GET.get('order', 'desc').strip()
        
        sort_mapping = {
            'code': ['code'],
            'title': ['title'],
            'department': ['department', 'unit'],
            'headcount': ['headcount'],
            'recruitment_type': ['recruitment_type'],
            'candidate_count': ['candidate_count'],
            'status': ['status'],
            'created_at': ['created_at'],
        }
        
        db_fields = sort_mapping.get(sort_by, ['created_at'])
        
        ordering = []
        for field in db_fields:
            if order == 'asc':
                ordering.append(field)
            else:
                ordering.append(f'-{field}')
                
        if 'created_at' not in db_fields:
            ordering.append('-created_at')
        ordering.append('-id')
        
        return queryset.annotate(
            candidate_count=Count('applications', filter=Q(applications__is_deleted=False))
        ).prefetch_related('stages').order_by(*ordering)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Pass current sorting details to template
        context['current_sort'] = self.request.GET.get('sort', 'created_at').strip()
        context['current_order'] = self.request.GET.get('order', 'desc').strip()
        
        # Clean current parameters to attach to pagination links
        query_params = self.request.GET.copy()
        if 'page' in query_params:
            del query_params['page']
        context['query_params'] = query_params.urlencode()
        
        # Get unique departments/units for filter dropdowns (only non-empty)
        context['departments'] = JobOpportunity.objects.filter(is_deleted=False).exclude(department='').values_list('department', flat=True).distinct().order_by('department')
        context['units'] = JobOpportunity.objects.filter(is_deleted=False).exclude(unit='').values_list('unit', flat=True).distinct().order_by('unit')
        
        # Pass filter choices to template
        context['status_choices'] = JobOpportunity.STATUS_CHOICES
        context['source_choices'] = JobOpportunity.SOURCE_CHOICES
        context['recruitment_choices'] = JobOpportunity.RECRUITMENT_TYPE_CHOICES
        context['category_choices'] = JobOpportunity.CATEGORY_CHOICES
        
        def get_clean_list(key):
            vals = self.request.GET.getlist(key)
            if len(vals) == 1 and ',' in vals[0]:
                vals = vals[0].split(',')
            return [v.strip() for v in vals if v.strip()]

        # Keep current filter values to populate form fields
        context['filters'] = {
            'q': self.request.GET.get('q', ''),
            'status': get_clean_list('status'),
            'department': get_clean_list('department'),
            'unit': get_clean_list('unit'),
            'source': get_clean_list('source'),
            'recruitment_type': get_clean_list('recruitment_type'),
            'job_category': get_clean_list('job_category'),
        }
        
        # Count active filters
        context['active_filters_count'] = sum(
            1 for k, val in context['filters'].items() 
            if (isinstance(val, list) and len(val) > 0) or (not isinstance(val, list) and val)
        )
        
        return context



class JobOpportunityCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = JobOpportunity
    form_class = JobOpportunityForm
    template_name = 'jobs/job_form.html'
    
    def dispatch(self, request, *args, **kwargs):
        from apps.core.license import get_system_license_limits
        limits = get_system_license_limits(request)
        current_jobs = JobOpportunity.objects.filter(is_deleted=False).count()
        if current_jobs >= limits['max_jobs']:
            from django.contrib import messages
            from django.shortcuts import redirect
            messages.error(request, "تعداد فرصت‌های شغلی فعال شما به حداکثر حد مجاز نسخه جاری رسیده است. برای تعریف فرصت جدید، لطفاً لایسنس خود را ارتقا دهید.")
            return redirect('job_list')
        return super().dispatch(request, *args, **kwargs)
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def get_success_url(self):
        from django.urls import reverse
        if self.object.status == JobOpportunity.STATUS_PLANNING:
            return reverse('job_planning', kwargs={'job_id': self.object.pk}) + '?next=print_doc'
        return reverse('job_competency_config', kwargs={'job_id': self.object.pk})

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        if self.request.POST:
            data['stages'] = JobOpportunityFormSet(self.request.POST)
        else:
            data['stages'] = JobOpportunityFormSet()
        return data

    def form_valid(self, form):
        context = self.get_context_data()
        stages = context['stages']
        
        # If a workflow template is selected, we automatically copy its default stages and skip formset
        if form.cleaned_data.get('workflow'):
            self.object = form.save()
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(self.get_success_url())

        if stages.is_valid():
            self.object = form.save()
            stages.instance = self.object
            stages.save()
            return super().form_valid(form)
        else:
            return self.form_invalid(form)


class JobOpportunityUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = JobOpportunity
    form_class = JobOpportunityForm
    template_name = 'jobs/job_form.html'
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def get_success_url(self):
        from django.urls import reverse
        return reverse('job_competency_config', kwargs={'job_id': self.object.pk})

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        if self.request.POST:
            data['stages'] = JobOpportunityFormSet(self.request.POST, instance=self.object)
        else:
            data['stages'] = JobOpportunityFormSet(
                instance=self.object,
                queryset=JobOpportunityStage.objects.filter(is_deleted=False).order_by('sequence')
            )
        return data

    def form_valid(self, form):
        # Check if workflow has changed
        workflow_changed = False
        if self.object and self.object.pk:
            old_instance = JobOpportunity.objects.filter(pk=self.object.pk).first()
            if old_instance and form.cleaned_data.get('workflow') != old_instance.workflow:
                workflow_changed = True

        context = self.get_context_data()
        stages = context['stages']
        
        # If workflow has changed, bypass formset validation, save parent (JobOpportunity.save will recreate stages)
        if workflow_changed:
            self.object = form.save()
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(self.get_success_url())

        # If workflow has not changed, but the job has no stages and a workflow is selected,
        # copy template stages automatically.
        workflow = form.cleaned_data.get('workflow')
        has_no_stages = not self.object.stages.filter(is_deleted=False).exists()
        if workflow and has_no_stages:
            self.object = form.save()
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(self.get_success_url())

        # Otherwise validate and save formset normally
        if stages.is_valid():
            self.object = form.save()
            stages.instance = self.object
            stages.save()
            self.object.sync_application_stages()
            return super().form_valid(form)
        else:
            return self.form_invalid(form)


class JobOpportunityDeleteConfirmView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def get(self, request, pk):
        job = get_object_or_404(JobOpportunity, pk=pk)
        applications = job.applications.filter(is_deleted=False)
        candidate_count = applications.count()
        
        exclusive_candidates_count = 0
        for app in applications:
            candidate = app.candidate
            other_apps_count = candidate.applications.filter(is_deleted=False).exclude(job=job).count()
            if other_apps_count == 0:
                exclusive_candidates_count += 1
                
        context = {
            'job': job,
            'candidate_count': candidate_count,
            'exclusive_candidates_count': exclusive_candidates_count,
        }
        return render(request, 'jobs/job_delete_confirm.html', context)


class JobOpportunityDeleteView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def delete(self, request, pk):
        return self._do_delete(request, pk, cleanup_option='keep')

    def post(self, request, pk):
        cleanup_option = request.POST.get('cleanup_option', 'keep')
        return self._do_delete(request, pk, cleanup_option=cleanup_option)

    def _do_delete(self, request, pk, cleanup_option):
        from django.db import transaction
        from django.utils import timezone
        
        job = get_object_or_404(JobOpportunity, pk=pk)
        
        with transaction.atomic():
            # Soft delete applications and handle candidates
            applications = job.applications.filter(is_deleted=False)
            for app in applications:
                candidate = app.candidate
                other_apps_count = candidate.applications.filter(is_deleted=False).exclude(job=job).count()
                
                if other_apps_count == 0 and cleanup_option == 'delete_exclusive':
                    candidate.delete()
                    
                app.delete()
                app.stage_states.filter(is_deleted=False).update(is_deleted=True, deleted_at=timezone.now())
                
            # Soft delete stages
            job.stages.filter(is_deleted=False).update(is_deleted=True, deleted_at=timezone.now())
            
            # Soft delete the job opportunity itself
            job.delete()
            
        response = HttpResponse("")
        response["HX-Trigger"] = "close-modal"
        return response


class WorkflowTemplateListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = WorkflowTemplate
    template_name = 'jobs/workflow_list.html'
    context_object_name = 'workflows'
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get_queryset(self):
        return WorkflowTemplate.objects.filter(is_deleted=False).prefetch_related('stages')


class WorkflowTemplateCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = WorkflowTemplate
    form_class = WorkflowTemplateForm
    template_name = 'jobs/workflow_form.html'
    success_url = reverse_lazy('workflow_list')
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        if self.request.POST:
            data['stages'] = WorkflowStageTemplateFormSet(self.request.POST)
        else:
            data['stages'] = WorkflowStageTemplateFormSet()
        return data

    def form_valid(self, form):
        context = self.get_context_data()
        stages = context['stages']
        if stages.is_valid():
            self.object = form.save()
            stages.instance = self.object
            stages.save()
            return super().form_valid(form)
        else:
            return self.form_invalid(form)


class WorkflowTemplateUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = WorkflowTemplate
    form_class = WorkflowTemplateForm
    template_name = 'jobs/workflow_form.html'
    success_url = reverse_lazy('workflow_list')
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        if self.request.POST:
            data['stages'] = WorkflowStageTemplateFormSet(self.request.POST, instance=self.object)
        else:
            data['stages'] = WorkflowStageTemplateFormSet(
                instance=self.object,
                queryset=WorkflowStageTemplate.objects.filter(is_deleted=False).order_by('sequence')
            )
        return data

    def form_valid(self, form):
        context = self.get_context_data()
        stages = context['stages']
        if stages.is_valid():
            self.object = form.save()
            stages.instance = self.object
            stages.save()
            return super().form_valid(form)
        else:
            return self.form_invalid(form)


class WorkflowTemplateDeleteView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def delete(self, request, pk):
        workflow = get_object_or_404(WorkflowTemplate, pk=pk)
        workflow.delete()  # Soft delete
        return HttpResponse("")


class ExportJobsExcelView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
        UserProfile.ROLE_DEPARTMENT_USER,
        UserProfile.ROLE_READ_ONLY_AUDITOR,
    ]

    def get(self, request):
        from django.db.models import Count, Q
        queryset = JobOpportunity.objects.filter(is_deleted=False)
        queryset = apply_job_filters(queryset, request.GET)
        jobs = queryset.annotate(
            candidate_count=Count('applications', filter=Q(applications__is_deleted=False))
        ).prefetch_related('stages').order_by('-created_at')

        headers = [
            "شناسه", "عنوان شغل", "کد شغل", "شماره درخواست", "دپارتمان", 
            "مسئول جذب", "تعداد مراحل", "مراحل فرآیند", "تعداد متقاضیان", "وضعیت", "تاریخ ایجاد"
        ]
        
        rows = []
        for job in jobs:
            stages_list = [stage.name for stage in job.stages.filter(is_deleted=False).order_by('sequence')]
            stages_str = " -> ".join(stages_list)
            recruiter_name = job.assigned_recruiter.get_full_name() if job.assigned_recruiter else str(job.assigned_recruiter or '')
            
            rows.append([
                job.id,
                job.title,
                job.code or "",
                job.request_number or "",
                job.department or "",
                recruiter_name,
                len(stages_list),
                stages_str,
                job.candidate_count,
                job.get_status_display(),
                job.created_at.strftime('%Y-%m-%d %H:%M') if job.created_at else ""
            ])
            
        from apps.core.utils import export_to_excel_response
        return export_to_excel_response("jobs_report.xlsx", headers, rows)


from django.views.generic import DetailView

class WorkflowStagesPreviewView(LoginRequiredMixin, View):
    def get(self, request, pk):
        workflow = get_object_or_404(WorkflowTemplate, pk=pk, is_deleted=False)
        stages = workflow.stages.filter(is_deleted=False).order_by('sequence')
        
        html = '<div class="d-flex flex-column gap-2">'
        html += '<span class="text-xs text-muted font-bold d-block mb-1">📋 مراحل ارزیابی این الگو:</span>'
        for stage in stages:
            html += f'<div class="d-flex justify-content-between align-items-center text-xs p-2 bg-white border border-light rounded">' \
                    f'<span class="font-semibold text-secondary">{stage.sequence}. {stage.name}</span>' \
                    f'<span class="badge bg-primary bg-opacity-10 text-primary font-bold">{stage.default_weight}٪</span>' \
                    f'</div>'
        html += '</div>'
        return HttpResponse(html)


class JobOpportunityPrintDocView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = JobOpportunity
    template_name = 'jobs/job_print_doc.html'
    context_object_name = 'job'
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def get_queryset(self):
        return JobOpportunity.objects.filter(is_deleted=False).prefetch_related('stages', 'stages__interviewers__user')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['selected_competencies'] = self.object.selected_competencies.filter(is_deleted=False)
        return context


class JobOpportunityPrintAdView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = JobOpportunity
    template_name = 'jobs/job_print_ad.html'
    context_object_name = 'job'
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
        UserProfile.ROLE_DEPARTMENT_USER,
        UserProfile.ROLE_READ_ONLY_AUDITOR,
    ]

    def get_queryset(self):
        return JobOpportunity.objects.filter(is_deleted=False).prefetch_related('stages')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        competencies = self.object.selected_competencies.filter(is_deleted=False)
        context['selected_competencies'] = competencies
        
        # Group competencies for modern, structured UI sections
        context['grouped_competencies'] = {
            'knowledge': competencies.filter(competency_type='KN'),
            'skills': competencies.filter(competency_type='SK'),
            'abilities': competencies.filter(competency_type='AB'),
            'behavioral': competencies.filter(competency_type='GE'),
            'others': competencies.exclude(competency_type__in=['KN', 'SK', 'AB', 'GE'])
        }
        
        from django.urls import reverse
        relative_url = reverse('careers_apply', args=[self.object.pk])
        context['apply_url'] = self.request.build_absolute_uri(relative_url)

        from apps.jobs.models import OrganizationSetting
        context['org_setting'] = OrganizationSetting.get_active_setting()
        return context





class JobOpportunityBulkStatusView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def post(self, request):
        from django.contrib import messages
        from django.shortcuts import redirect
        import re
        
        job_codes_text = request.POST.get('job_codes', '').strip()
        new_status = request.POST.get('new_status', '').strip()
        
        status_keys = [choice[0] for choice in JobOpportunity.STATUS_CHOICES]
        if new_status not in status_keys:
            messages.error(request, "وضعیت انتخاب شده معتبر نیست.")
            return redirect('job_list')
            
        codes = [normalize_digits(c.strip()) for c in re.split(r'[\n,\s]+', job_codes_text) if c.strip()]
        
        if not codes:
            messages.error(request, "لطفاً حداقل یک کد فرصت شغلی وارد کنید.")
            return redirect('job_list')
            
        jobs = JobOpportunity.objects.filter(code__in=codes, is_deleted=False)
        updated_count = 0
        not_found = []
        
        found_codes = set(j.code for j in jobs)
        for code in codes:
            if code not in found_codes:
                not_found.append(code)
                
        for job in jobs:
            if job.status != new_status:
                job.status = new_status
                job.save(update_fields=['status'])
                # Also ensure update_status does not conflict, but it checks CANCELLED/SUSPENDED which is fine.
                updated_count += 1
                
        if updated_count > 0:
            msg = f"وضعیت {updated_count} فرصت شغلی با موفقیت به «{dict(JobOpportunity.STATUS_CHOICES).get(new_status)}» تغییر یافت."
            if not_found:
                msg += f" (کدهای یافت نشده: {', '.join(not_found)})"
            messages.success(request, msg)
        else:
            if not_found:
                messages.warning(request, f"هیچ فرصت شغلی با کدهای وارد شده یافت نشد. کدهای بررسی شده: {', '.join(not_found)}")
            else:
                messages.info(request, "وضعیت فرصت‌های شغلی مورد نظر از قبل با وضعیت انتخابی یکسان بود.")
                
        return redirect('job_list')


# Competency-Based Assessment Views

from django.contrib import messages
from django.shortcuts import redirect
from django.db.models import Q, Count, Avg
from django.views.generic import TemplateView, DetailView
from django.core.files.storage import FileSystemStorage
import os

from .models import CentralCompetency, JobOpportunityCompetency, JobOpportunity, JobOpportunityStage, AssessmentCompetency
from .utils import parse_competencies_excel, calculate_assessment_plan, normalize_persian_digits


class CentralCompetencyUploadView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]
    template_name = 'jobs/competency_upload.html'

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        if 'competency_file' not in request.FILES:
            messages.error(request, "لطفاً یک فایل اکسل انتخاب کنید.")
            return render(request, self.template_name)

        excel_file = request.FILES['competency_file']
        if not excel_file.name.endswith(('.xlsx', '.xls')):
            messages.error(request, "فرمت فایل باید اکسل (.xlsx, .xls) باشد.")
            return render(request, self.template_name)

        # Save temporarily
        fs = FileSystemStorage(location=os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../scratch'))
        filename = fs.save(excel_file.name, excel_file)
        file_path = fs.path(filename)

        try:
            stats = parse_competencies_excel(file_path)
            msg = (f"بانک شایستگی‌ها با موفقیت به‌روزرسانی شد. "
                   f"جدید: {stats['created']} | ویرایش شده: {stats['updated']} | "
                   f"حذف شده: {stats['deleted']} | نادیده گرفته شده: {stats['skipped']}")
            messages.success(request, msg)
            return redirect('competency_list')
        except Exception as e:
            messages.error(request, f"خطا در پردازش فایل اکسل: {str(e)}")
            return render(request, self.template_name)
        finally:
            # Cleanup temp file
            if os.path.exists(file_path):
                os.remove(file_path)


class CentralCompetencyListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = CentralCompetency
    template_name = 'jobs/competency_list.html'
    context_object_name = 'competencies'
    paginate_by = 25
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
        UserProfile.ROLE_DEPARTMENT_USER,
        UserProfile.ROLE_READ_ONLY_AUDITOR,
    ]

    def get_queryset(self):
        queryset = CentralCompetency.objects.filter(is_deleted=False)
        
        # Search query
        q = self.request.GET.get('q', '').strip()
        if q:
            q_norm = normalize_persian_digits(q)
            queryset = queryset.filter(
                Q(code__icontains=q) | 
                Q(code__icontains=q_norm) |
                Q(post_code__icontains=q) |
                Q(post_code__icontains=q_norm) |
                Q(title__icontains=q) |
                Q(post_title__icontains=q)
            )

        # Filters
        comp_type = self.request.GET.get('competency_type', '').strip()
        if comp_type:
            queryset = queryset.filter(competency_type=comp_type)

        importance = self.request.GET.get('importance', '').strip()
        if importance:
            queryset = queryset.filter(importance=importance)

        level = self.request.GET.get('level', '').strip()
        if level:
            queryset = queryset.filter(level=level)

        return queryset.order_by('post_code', 'code')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '').strip()
        context['competency_type'] = self.request.GET.get('competency_type', '').strip()
        context['importance'] = self.request.GET.get('importance', '').strip()
        context['level'] = self.request.GET.get('level', '').strip()
        
        # Type display choices mapping
        context['type_choices'] = [
            ('KN', 'دانش (KN)'),
            ('SK', 'مهارت (SK)'),
            ('AB', 'توانایی (AB)'),
            ('GE', 'رفتاری (GE)'),
            ('ST', 'ارزش‌ها و سبک‌ها (ST)'),
            ('PR', 'گردشکار (PR)'),
            ('CQ', 'گواهینامه و صلاحیت (CQ)'),
            ('IN', 'علایق حرفه‌ای (IN)'),
        ]
        context['importance_choices'] = [
            ('1', '۱ - محوری'),
            ('2', '۲ - تکلیف محور'),
            ('3', '۳ - حداقلی'),
        ]
        context['level_choices'] = [
            ('1', '۱ - آشنایی'),
            ('2', '۲ - توانایی'),
            ('3', '۳ - تسلط'),
        ]
        return context


def clean_str(s):
    if not s:
        return ""
    s = s.replace("ي", "y").replace("ك", "k").replace("ی", "y").replace("ک", "k")
    s = s.replace("\u200c", "").replace("‌", "")
    return "".join(s.split())


def is_functional_competency(title, ctype):
    if ctype not in ['KN', 'SK', 'AB']:
        return False
    
    excluded_titles = {
        "مدیریت مصرف آب",
        "امنیت سایبری",
        "آشنایی با مبانی مدیریت کربن",
        "اقدامات اقلیمی ملی و بین المللی",
        "تاب آوری",
        "اقدامات اقلیمی ملی و بین‌المللی",
        "تاب‌آوری",
        "آشنایی با مبانی مدیریت کربن و اقدامات اقلیمی ملی و بین المللی",
        "آشنایی با مبانی مدیریت کربن و اقدامات اقلیمی ملی و بین‌المللی"
    }
    cleaned_title = clean_str(title)
    excluded_cleaned = {clean_str(t) for t in excluded_titles}
    return cleaned_title not in excluded_cleaned


def get_job_category_from_title(title):
    if not title:
        return ''
    if 'کارشناس مدیریت' in title:
        return 'کارشناس مدیریت'
    if 'کارشناس مسئول' in title:
        return 'کارشناس مسئول'
    if 'کارشناس' in title:
        return 'کارشناس'
    if 'کاردان مسئول' in title:
        return 'کاردان مسئول'
    if 'کاردان' in title:
        return 'کاردان'
    if 'اپراتور' in title or 'تعمیرکار' in title:
        return 'اپراتور - تعمیرکار'
    return ''


def get_ai_recommendation(post_code, post_title, comps, refresh=False):
    """
    Helper to fetch AI recruitment strategies with caching and offline fallback.
    Returns:
        dict: containing opt_advice, scenario, questions, benchmark_mappings, is_live, cached
    """
    comps = [
        c for c in comps
        if is_functional_competency(c.title, c.competency_type)
    ]

    from apps.jobs.models import AIPostRecommendation, AISetting
    import urllib.request
    import json


    # 1. Check cache first if refresh is False
    cached_recommendation = None
    if not refresh:
        cached_recommendation = AIPostRecommendation.objects.filter(post_code=post_code, is_deleted=False).first()

    if cached_recommendation:
        raw_advice = cached_recommendation.opt_advice or []
        opt_advice = []
        for item in raw_advice:
            if isinstance(item, dict):
                text = item.get('text', '')
                weights = item.get('weights', {})
            else:
                text = str(item)
                weights = {}
            opt_advice.append({
                'text': text,
                'weights': weights,
                'weights_json': json.dumps(weights)
            })

        return {
            'opt_advice': opt_advice,
            'scenario': cached_recommendation.scenario or "",
            'questions': cached_recommendation.questions or [],
            'benchmark_mappings': cached_recommendation.benchmark_mappings or [],
            'is_live': True,
            'cached': True
        }

    # 2. Call LLM API
    ai_setting = AISetting.get_active_setting()
    is_live = False
    opt_advice = []
    scenario = ""
    questions = []
    benchmark_mappings = []

    if ai_setting and ai_setting.api_key:
        try:
            comp_list_str = "\n".join([f"- {c.title} ({c.get_competency_type_display()} - اهمیت: {c.get_importance_display()})" for c in comps])

            system_prompt = (
                "شما یک مستشار ارشد جذب و ارزیابی شایستگی‌ها و طراح کانون‌های ارزیابی منابع انسانی هستید.\n"
                "وظیفه شما این است که با تحلیل دقیق عنوان پست سازمانی و لیست شایستگی‌های تعریف‌شده آن، یک راهبرد اختصاصی، سناریوی ارزیابی کاملاً واقعی و کاربردی و نگاشت بنچمارک‌های جهانی تولید کنید.\n"
                "برای پرهیز از خروجی‌های تکراری و کلیشه‌ای، سناریو و توصیه‌های شما باید کاملاً منطبق بر شایستگی‌های ورودی و نیازمندی‌های این شغل خاص طراحی شود. سناریو را به عنوان یک کارشناس خبره جذب و با جزئیات بنویسید.\n\n"
                "قوانین تولید محتوای فیلدها:\n"
                "1. سناریو (scenario) باید یک متن ساختاریافته فارسی و تفصیلی باشد که شامل سرفصل‌های زیر با علامت هشتگ (###) باشد:\n"
                "   - ### عنوان سناریوی کانون ارزیابی\n"
                "   - ### مدت زمان پیشنهادی سنجش\n"
                "   - ### فضای شبیه‌سازی و نقش کاندیدا (مثلاً ایفای نقش مدیر، حل کارتابل، کار گروهی...)\n"
                "   - ### شرح چالش اصلی سناریو (مسئله پیچیده‌ای که داوطلب باید حل کند)\n"
                "   - ### نحوه سنجش شایستگی‌های ورودی در این سناریو (ذکر نحوه ارزیابی شایستگی‌های درخواستی کاربر به صورت مجزا)\n"
                "   - ### راهنمای ناظر/ارزیاب کانون (نشانه‌های رفتاری مثبت و منفی برای رصد و امتیازدهی)\n\n"
                "2. لیست سوالات مصاحبه (questions) باید شامل شیءهایی با فیلدهای زیر باشد:\n"
                "   - competency: نام شایستگی هدف (دقیقاً یکی از شایستگی‌های ورودی)\n"
                "   - question: سوال رفتاری ساختاریافته (CBI) مبتنی بر روش STAR (موقعیت، وظیفه، اقدام، نتیجه) به زبان فارسی و روان\n"
                "   - criteria: راهنمای ارزیابی پاسخ مطلوب و نشانگرهای رفتاری مطلوب برای مصاحبه‌کننده\n\n"
                "3. نگاشت بنچمارک‌ها (benchmark_mappings) باید شامل فیلدهای زیر باشد:\n"
                "   - competency: نام دقیق شایستگی ورودی از لیست کاربر\n"
                "   - framework: نام یکی از چارچوب‌های مرجع جهانی معتبر (مانند SHL UCF یا Lominger یا Korn Ferry یا DDI)\n"
                "   - dimension: بعد معادل انگلیسی و فارسی در آن چارچوب مرجع\n"
                "   - tool: ابزار ارزیابی مناسب (مانند آزمون کتبی، کانون ارزیابی، ایفای نقش، تست شبیه‌ساز، یا کارتابل)\n"
                "   - behavioral_indicators: آرایه‌ای حاوی ۲ الی ۳ نشانگر رفتاری قابل مشاهده و سنجش مربوط به این شایستگی در کار واقعی\n"
                "   - pass_benchmark: نمره قبولی پیشنهادی در مقیاس ۱ تا ۵ به همراه توصیف کوتاه (مثلاً: ۳.۵ از ۵: توانایی کار مستقل)\n"
                "   - rationale: تحلیل کوتاه فنی و کاربردی علت انتخاب ابزار و دلیل نگاشت به بعد جهانی\n\n"
                "پاسخ خود را دقیقاً در قالب ساختار JSON زیر بازگردانید و هیچ توضیح اضافه یا متنی خارج از JSON ارائه ندهید. پاسخ‌ها حتماً به زبان فارسی باشد:\n"
                "{\n"
                "  \"opt_advice\": [\n"
                "    {\n"
                "      \"text\": \"توصیه اختصاصی بهینه‌سازی شایستگی یا ساختار ارزیابی این پست با ذکر درصد وزن‌های پیشنهادی ملموس (مثلاً آزمون مهارتی ۴۰٪، مصاحبه ۳۰٪...)\",\n"
                "      \"weights\": {\"SKILL_TEST\": 40, \"INTERVIEW\": 30, \"EXAM\": 10, \"ASSESSMENT\": 20}\n"
                "    }\n"
                "  ],\n"
                "  \"benchmark_mappings\": [\n"
                "    {\n"
                "      \"competency\": \"نام دقیق شایستگی ورودی\",\n"
                "      \"framework\": \"نام چارچوب مرجع\",\n"
                "      \"dimension\": \"بعد معادل\",\n"
                "      \"tool\": \"ابزار پیشنهادی\",\n"
                "      \"behavioral_indicators\": [\"نشانگر ۱\", \"نشانگر ۲\"],\n"
                "      \"pass_benchmark\": \"بنچمارک قبولی پیشنهادی از ۱ تا ۵\",\n"
                "      \"rationale\": \"تحلیل فنی علت انتخاب ابزار\"\n"
                "    }\n"
                "  ],\n"
                "  \"scenario\": \"متن کامل سناریوی ارزیابی با سرفصل‌های هشتگ‌دار بر اساس الگوی بالا\",\n"
                "  \"questions\": [\n"
                "    {\n"
                "      \"competency\": \"نام شایستگی هدف\",\n"
                "      \"question\": \"سوال مصاحبه رفتاری CBI بر اساس تکنیک STAR\",\n"
                "      \"criteria\": \"راهنمای ارزیابی پاسخ مطلوب\"\n"
                "    }\n"
                "  ]\n"
                "}"
            )

            user_prompt = f"عنوان پست: {post_title}\nکد پست: {post_code}\nشایستگی‌های تعریف‌شده:\n{comp_list_str}"

            payload = {
                "model": ai_setting.model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7,
                "response_format": {"type": "json_object"}
            }

            url = f"{ai_setting.base_url.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {ai_setting.api_key}",
                "Content-Type": "application/json"
            }

            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')

            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    res_body = response.read().decode('utf-8')
                    res_json = json.loads(res_body)
                    content = res_json['choices'][0]['message']['content']
                    parsed_content = json.loads(content)

                    raw_advice = parsed_content.get('opt_advice', [])
                    cache_advice_list = []
                    for item in raw_advice:
                        if isinstance(item, dict):
                            text = item.get('text', '')
                            weights = item.get('weights', {})
                        else:
                            text = str(item)
                            weights = {}

                        opt_advice.append({
                            'text': text,
                            'weights': weights,
                            'weights_json': json.dumps(weights)
                        })
                        cache_advice_list.append({
                            'text': text,
                            'weights': weights
                        })

                    scenario = parsed_content.get('scenario', '')
                    questions = parsed_content.get('questions', [])
                    benchmark_mappings = parsed_content.get('benchmark_mappings', [])

                    if opt_advice and scenario and questions:
                        is_live = True
                        AIPostRecommendation.objects.update_or_create(
                            post_code=post_code,
                            defaults={
                                'opt_advice': cache_advice_list,
                                'scenario': scenario,
                                'questions': questions,
                                'benchmark_mappings': benchmark_mappings,
                                'is_deleted': False
                            }
                        )
        except Exception:
            pass

    # 3. Fallback to local mock data if not live
    if not is_live:
        # Extract comps titles and types
        imp_comps = [c for c in comps if c.importance == 1]
        
        has_kn = any(c.competency_type == 'KN' for c in comps)
        has_sk_ab = any(c.competency_type in ['SK', 'AB'] for c in comps)
        has_ge_st = any(c.competency_type in ['GE', 'ST'] for c in comps)
        
        weights = {}
        if has_kn and has_sk_ab and has_ge_st:
            weights = {"EXAM": 25, "SKILL_TEST": 25, "INTERVIEW": 20, "ASSESSMENT": 30}
        elif has_sk_ab and has_ge_st:
            weights = {"SKILL_TEST": 40, "INTERVIEW": 20, "ASSESSMENT": 40}
        elif has_kn and has_sk_ab:
            weights = {"EXAM": 30, "SKILL_TEST": 40, "INTERVIEW": 30}
        else:
            weights = {"EXAM": 30, "INTERVIEW": 30, "ASSESSMENT": 40}
            
        stage_names_fa = {
            'EXAM': 'آزمون کتبی',
            'SKILL_TEST': 'آزمون مهارتی',
            'INTERVIEW': 'مصاحبه تخصصی',
            'ASSESSMENT': 'کانون ارزیابی'
        }
        
        weights_str = "، ".join([f"{stage_names_fa.get(k, k)} به میزان {v}٪" for k, v in weights.items()])
        
        raw_advice = [
            {
                "text": f"توصیه می‌شود در سناریوی ارزیابی پست «{post_title}»، فرآیندی ترکیبی شامل {weights_str} پیاده‌سازی شود تا شایستگی‌های فنی و عمومی به طور متعادل سنجیده شوند.",
                "weights": weights
            }
        ]
        
        if imp_comps:
            core_titles = " و ".join([f"«{c.title}»" for c in imp_comps[:2]])
            raw_advice.append({
                "text": f"توصیه می‌شود تمرکز اصلی فرآیند ارزیابی و مصاحبه بر شایستگی‌های محوری {core_titles} قرار گیرد و حدنصاب قبولی بالاتری برای آن‌ها در نظر گرفته شود.",
                "weights": {}
            })
            
        raw_advice.append({
            "text": f"پیشنهاد می‌شود برای بهینه‌سازی فرآیند جذب «{post_title}»، ارزیابی‌های مربوط به مهارت‌های ارتباطی و کار تیمی در خلال تمرین‌های گروهی کانون ارزیابی رصد و ثبت گردند.",
            "weights": {}
        })
        
        benchmark_mappings = []
        frameworks = ["SHL UCF", "Lominger", "Korn Ferry", "DDI"]
        for idx, c in enumerate(comps[:4]):
            fw = frameworks[idx % len(frameworks)]
            if c.competency_type == 'KN':
                dim = f"Applying Expertise and Technology ({c.title})"
                tool = "آزمون کتبی تخصصی"
                rat = f"سنجش دانش نظری و تخصصی داوطلب در رابطه با شایستگی «{c.title}»."
                behavioral_indicators = [
                    f"تسلط علمی کامل بر مباحث فنی و الزامات اجرایی مرتبط با {c.title}",
                    f"توانایی تحلیل و حل مسائل تئوریک و کاربردی در حوزه {c.title}"
                ]
                pass_benchmark = "۴ از ۵ (تسلط علمی کامل)"
            elif c.competency_type in ['SK', 'AB']:
                dim = f"Applying Skills and Practical Abilities ({c.title})"
                tool = "آزمون مهارتی عملی یا شبیه‌ساز"
                rat = f"ارزیابی توانمندی داوطلب در پیاده‌سازی عملی مهارت «{c.title}» در کار واقعی."
                behavioral_indicators = [
                    f"انجام سریع و بدون خطای وظایف کاری مرتبط با {c.title}",
                    f"عیب‌یابی سریع و خلاقانه فرآیندها در هنگام بروز چالش در {c.title}"
                ]
                pass_benchmark = "۳.۵ از ۵ (کار مستقل بدون سرپرستی مستقیم)"
            else:
                dim = f"Behavioral Competence and Values ({c.title})"
                tool = "شبیه‌سازی ایفای نقش یا کانون ارزیابی"
                rat = f"بررسی الگوهای رفتاری و انطباق فرهنگی داوطلب با معیارهای «{c.title}»."
                behavioral_indicators = [
                    f"همکاری موثر تیمی و بروز رفتار حرفه‌ای تحت فشار کاری مرتبط با {c.title}",
                    f"انعطاف‌پذیری و سازگاری با تغییر اولویت‌ها بر مبنای ارزش‌های {c.title}"
                ]
                pass_benchmark = "۳ از ۵ (انطباق رفتاری متوسط رو به بالا)"
                
            benchmark_mappings.append({
                "competency": c.title,
                "framework": fw,
                "dimension": dim,
                "tool": tool,
                "behavioral_indicators": behavioral_indicators,
                "pass_benchmark": pass_benchmark,
                "rationale": rat
            })
            
        comp_titles_str = "، ".join([c.title for c in comps[:3]])
        
        scenario = (
            f"### عنوان سناریوی کانون ارزیابی\n"
            f"شبیه‌سازی مدیریت بحران عملیاتی و تعاملات کاری پست {post_title}\n\n"
            f"### مدت زمان پیشنهادی سنجش\n"
            f"۴۵ دقیقه ارزیابی عملی + ۱۵ دقیقه بازخورد و ثبت مشاهدات\n\n"
            f"### فضای شبیه‌سازی و نقش کاندیدا\n"
            f"داوطلب به عنوان سرپرست یا کارشناس ارشد بخش در مواجهه با یک چالش فرضی اما واقعی سازمان قرار می‌گیرد. او باید یک کارتابل شلوغ از ایمیل‌ها و درخواست‌های فوری مربوط به شایستگی‌های {comp_titles_str} را اولویت‌بندی کرده و با یک همکار فرضی (ارزیاب ایفاگر نقش) که معترض است، گفتگو کند.\n\n"
            f"### شرح چالش اصلی سناریو\n"
            f"سیستم اصلی پروژه در آستانه تحویل نهایی با مشکل فنی و ارتباطی مواجه شده است و همزمان اولویت‌ها تغییر کرده‌اند. داوطلب باید ضمن اتخاذ تصمیمات فنی منطقی، خشم همکار خود را مدیریت کند و برنامه کاری جدید را تنظیم نماید.\n\n"
            f"### نحوه سنجش شایستگی‌های ورودی در این سناریو\n"
            f"هر یک از شایستگی‌ها بر اساس سناریو به شرح زیر ارزیابی می‌شود:\n"
        )
        for c in comps[:3]:
            scenario += f"- **{c.title}**: میزان تسلط داوطلب در اتخاذ تصمیمات ملموس و عملی در طول بحران و کیفیت خروجی کارتابل شبیه‌سازی‌شده.\n"
        
        scenario += (
            f"\n### راهنمای ناظر/ارزیاب کانون\n"
            f"- **نشانه‌های رفتاری مثبت**: حفظ آرامش لحن، اولویت‌بندی مجدد بر اساس فوریت و اهمیت، ارائه راه‌حل‌های ساختاریافته فنی.\n"
            f"- **نشانه‌های رفتاری منفی**: سردرگمی در کارتابل، پرخاش یا تسلیم شدن در تعامل با همکار معترض، نداشتن برنامه شفاف عملیاتی."
        )
        
        questions = []
        for c in comps[:3]:
            questions.append({
                "competency": c.title,
                "question": f"یک تجربه واقعی کاری را شرح دهید که در آن نیاز مبرم به استفاده از شایستگی «{c.title}» برای حل یک چالش کاری داشتید. دقیقاً چه کردید و نتیجه چه بود؟",
                "criteria": f"ارزیابی توانمندی داوطلب در استفاده عملی از {c.title}، ارائه مصادیق واقعی بر اساس STAR، و میزان اثرگذاری اقدامات وی بر روی اهداف پروژه."
            })
        questions.append({
            "competency": "برنامه‌ریزی و مدیریت بحران",
            "question": f"به عنوان کاندیدای پست «{post_title}»، اگر در یک موقعیت بحرانی با تداخل منافع ذینفعان و تغییر ناگهانی اولویت‌ها روبرو شوید، چگونه اولویت‌ها را بازنگری و اقدام می‌کنید؟",
            "criteria": "توانایی حفظ خونسردی، تفکیک امور مهم و فوری، تعامل سازنده با ذینفعان ناراضی و ارائه برنامه بازنگری‌شده شفاف."
        })

        for item in raw_advice:
            opt_advice.append({
                'text': item['text'],
                'weights': item['weights'],
                'weights_json': json.dumps(item['weights'])
            })

        # Overwrite database cache with fallback mock data
        from apps.jobs.models import AIPostRecommendation
        cache_advice_list = [
            {'text': item['text'], 'weights': item['weights']} 
            for item in raw_advice
        ]
        AIPostRecommendation.objects.update_or_create(
            post_code=post_code,
            defaults={
                'opt_advice': cache_advice_list,
                'scenario': scenario,
                'questions': questions,
                'benchmark_mappings': benchmark_mappings,
                'is_deleted': False
            }
        )

    return {
        'opt_advice': opt_advice,
        'scenario': scenario,
        'questions': questions,
        'benchmark_mappings': benchmark_mappings,
        'is_live': is_live,
        'cached': cached_recommendation is not None
    }


class RecruitmentPatternDashboardView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    template_name = 'jobs/recruitment_patterns.html'
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
        UserProfile.ROLE_DEPARTMENT_USER,
        UserProfile.ROLE_READ_ONLY_AUDITOR,
    ]

    def get(self, request, *args, **kwargs):
        action = request.GET.get('action', '').strip()
        
        if action == 'simulate':
            post_code = request.GET.get('post_code', '').strip()
            round_weights = request.GET.get('round', 'false').lower() == 'true'
            
            from apps.jobs.models import CentralCompetency
            from django.db.models import Count, Q
            
            comps = CentralCompetency.objects.filter(post_code=post_code, is_deleted=False).exclude(
                Q(title__in=['', None, 'بدون عنوان', 'بدون‌عنوان']) |
                Q(post_title__in=['', None, 'بدون عنوان', 'بدون‌عنوان'])
            )
            if not comps.exists():
                return HttpResponse('<div class="alert alert-warning text-sm text-center">هیچ شایستگی برای این پست یافت نشد.</div>')
            
            post_title = comps.first().post_title or ''
            
            class MockComp:
                def __init__(self, c):
                    self.code = c.code
                    self.title = c.title
                    self.competency_type = c.competency_type
                    self.importance = c.importance
                    self.level = c.level
                    
            mock_comps = [MockComp(c) for c in comps]
            plan = calculate_assessment_plan(mock_comps, round_to_five=round_weights)
            
            # Find similar posts based on shared competency titles and matching job category (same rank)
            current_category = get_job_category_from_title(post_title)
            selected_comp_titles = list(comps.values_list('title', flat=True))
            similar_candidates = (
                CentralCompetency.objects.filter(title__in=selected_comp_titles, is_deleted=False)
                .exclude(post_code=post_code)
                .exclude(Q(post_title__in=['', None, 'بدون عنوان', 'بدون‌عنوان']) | Q(title__in=['', None, 'بدون عنوان', 'بدون‌عنوان']))
                .values('post_code', 'post_title')
                .annotate(match_count=Count('id'))
                .order_by('-match_count')
            )
            similar_posts_list = []
            for item in similar_candidates:
                other_code = item['post_code']
                other_title = item['post_title'] or ''
                other_category = get_job_category_from_title(other_title)
                if current_category == other_category:
                    # Find shared competencies
                    other_comps_qs = CentralCompetency.objects.filter(post_code=other_code, is_deleted=False).exclude(
                        Q(title__in=['', None, 'بدون عنوان', 'بدون‌عنوان'])
                    )
                    other_comps = set(other_comps_qs.values_list('title', flat=True))
                    shared = list(set(selected_comp_titles).intersection(other_comps))
                    
                    similar_posts_list.append({
                        'post_code': other_code,
                        'post_title': other_title,
                        'match_count': item['match_count'],
                        'shared_competencies': shared
                    })
                    if len(similar_posts_list) >= 5:
                        break
            
            # Find matching talents (candidates) from talent bank based on job competency overlap
            # Extract target functional competencies of the current post
            target_comps = [c for c in comps if is_functional_competency(c.title, c.competency_type)]
            target_comp_titles = [c.title for c in target_comps]
            target_comp_set = set(target_comp_titles)

            from apps.jobs.models import JobOpportunity
            from apps.candidates.models import JobApplication, Candidate
            
            jobs_qs = JobOpportunity.objects.filter(is_deleted=False).prefetch_related('selected_competencies')
            similar_job_ids = []
            job_overlap_pcts = {}
            job_shared_comps = {}

            if len(target_comp_set) > 0:
                for job in jobs_qs:
                    if job.code == post_code:
                        continue
                    job_comps = {
                        jc.title for jc in job.selected_competencies.all()
                        if not jc.is_deleted and is_functional_competency(jc.title, jc.competency_type)
                    }
                    intersection = target_comp_set.intersection(job_comps)
                    overlap_pct = (len(intersection) / len(target_comp_set)) * 100
                    if overlap_pct >= 50:
                        similar_job_ids.append(job.id)
                        job_overlap_pcts[job.id] = round(overlap_pct)
                        job_shared_comps[job.id] = list(intersection)

            # Filter out candidates that have STATUS_SELECTED anywhere in the system
            selected_candidate_ids = set(
                JobApplication.objects.filter(
                    status=JobApplication.STATUS_SELECTED,
                    is_deleted=False
                ).values_list('candidate_id', flat=True)
            )

            matching_applications = JobApplication.objects.filter(
                job_id__in=similar_job_ids,
                is_deleted=False
            ).exclude(
                candidate_id__in=selected_candidate_ids
            ).select_related('candidate', 'job')

            candidate_best_matches = {}
            for app in matching_applications:
                cand = app.candidate
                if not cand or cand.is_deleted:
                    continue
                overlap_pct = job_overlap_pcts[app.job_id]
                
                if cand.id not in candidate_best_matches:
                    candidate_best_matches[cand.id] = app
                else:
                    existing_app = candidate_best_matches[cand.id]
                    if app.final_score > existing_app.final_score:
                        candidate_best_matches[cand.id] = app
                    elif app.final_score == existing_app.final_score:
                        if overlap_pct > job_overlap_pcts[existing_app.job_id]:
                            candidate_best_matches[cand.id] = app

            talents = []
            for cand_id, app in candidate_best_matches.items():
                cand = app.candidate
                overlap_pct = job_overlap_pcts[app.job_id]
                shared = job_shared_comps[app.job_id]
                
                talents.append({
                    'id': cand.id,
                    'first_name': cand.first_name,
                    'last_name': cand.last_name,
                    'phone_number': cand.phone_number,
                    'match_percent': overlap_pct,
                    'source_job_title': app.job.title,
                    'source_job_score': round(app.final_score),
                    'shared_competencies': shared
                })

            # Sort talents by final score descending, and match percentage descending
            talents.sort(key=lambda x: (x['source_job_score'], x['match_percent']), reverse=True)
            talents = talents[:5]
            
            from apps.jobs.models import AIPostRecommendation
            has_cached_ai = AIPostRecommendation.objects.filter(post_code=post_code, is_deleted=False).exists()
            ai_data = None
            if has_cached_ai:
                ai_data = get_ai_recommendation(post_code, post_title, comps, refresh=False)
            
            # Calculate overlap with other posts, highlighting those with active JobOpportunities in progress
            from collections import defaultdict
            all_comps_qs = CentralCompetency.objects.filter(is_deleted=False).exclude(
                Q(title__in=['', None, 'بدون عنوان', 'بدون‌عنوان']) |
                Q(post_title__in=['', None, 'بدون عنوان', 'بدون‌عنوان'])
            ).values('post_code', 'post_title', 'title', 'competency_type')
            post_comps = defaultdict(list)
            post_titles = {}
            for c in all_comps_qs:
                p_code = c['post_code']
                if is_functional_competency(c['title'], c['competency_type']):
                    post_comps[p_code].append({
                        'title': c['title'],
                        'type': c['competency_type']
                    })
                if c['post_title']:
                    post_titles[p_code] = c['post_title']
            
            overlap_list = []
            selected_comps_dict = {c.title: c.competency_type for c in comps if is_functional_competency(c.title, c.competency_type)}
            selected_comps_set = set(selected_comps_dict.keys())
            
            for code, comps_list in post_comps.items():
                if code == post_code:
                    continue
                if not comps_list:
                    continue
                
                other_titles = {c['title'] for c in comps_list}
                intersection = selected_comps_set.intersection(other_titles)
                min_len = min(len(selected_comps_set), len(other_titles))
                if min_len > 0:
                    overlap_pct = (len(intersection) / min_len) * 100
                else:
                    overlap_pct = 0
                
                if overlap_pct >= 80 and len(intersection) > 1:
                    # Determine which assessments are shared based on the intersection's competency types
                    shared_stages = []
                    has_written = False
                    has_skill = False
                    has_assessment_center = False
                    
                    for title in intersection:
                        ctype = selected_comps_dict[title]
                        if ctype == 'KN':
                            has_written = True
                        elif ctype in ['SK', 'AB']:
                            has_skill = True
                        elif ctype in ['GE', 'ST']:
                            has_assessment_center = True
                    
                    if has_written:
                        shared_stages.append("آزمون کتبی مشترک")
                    if has_skill:
                        shared_stages.append("ارزیابی مهارتی مشترک")
                    if has_assessment_center:
                        shared_stages.append("کانون ارزیابی مشترک")
                    
                    # Check if there is an active JobOpportunity for this post code
                    from apps.jobs.models import JobOpportunity
                    active_opp = JobOpportunity.objects.filter(
                        code=code, is_deleted=False
                    ).exclude(
                        status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED]
                    ).first()
                    
                    overlap_list.append({
                        'post_code': code,
                        'post_title': post_titles.get(code, code),
                        'overlap_pct': round(overlap_pct),
                        'shared_competencies': list(intersection)[:6],
                        'shared_count': len(intersection),
                        'shared_stages': shared_stages,
                        'is_active_opportunity': active_opp is not None,
                        'active_opp_title': active_opp.title if active_opp else None,
                        'active_opp_id': active_opp.id if active_opp else None,
                        'active_opp_status': active_opp.get_status_display() if active_opp else None
                    })
            
            overlap_list.sort(key=lambda x: (x['is_active_opportunity'], x['overlap_pct']), reverse=True)
            high_overlap_post = overlap_list[0] if overlap_list else None
            
            context = {
                'post_code': post_code,
                'post_title': post_title,
                'competencies': comps,
                'plan': plan['stages'],
                'errors': plan.get('errors', []),
                'similar_posts': similar_posts_list,
                'talents': talents,
                'round_weights': round_weights,
                'has_cached_ai': has_cached_ai,
                'ai_data': ai_data,
                'high_overlap_post': high_overlap_post,
                'overlap_list': overlap_list[:5],
            }
            return render(request, 'jobs/partials/post_pattern_simulation.html', context)
            
        elif action == 'ai_advise':
            post_code = request.GET.get('post_code', '').strip()
            refresh = request.GET.get('refresh', 'false').lower() == 'true'
            
            from apps.jobs.models import CentralCompetency
            comps = CentralCompetency.objects.filter(post_code=post_code, is_deleted=False)
            post_title = comps.first().post_title if comps.exists() else 'پست شبیه‌سازی شده'
            
            ai_data = get_ai_recommendation(post_code, post_title, comps, refresh=refresh)
            
            context = {
                'post_code': post_code,
                'post_title': post_title,
                'opt_advice': ai_data['opt_advice'],
                'scenario': ai_data['scenario'],
                'questions': ai_data['questions'],
                'benchmark_mappings': ai_data.get('benchmark_mappings', []),
                'is_live': ai_data['is_live'],
                'cached': ai_data['cached']
            }
            return render(request, 'jobs/partials/ai_recruitment_strategy.html', context)
        
        elif action == 'ai_match_talent_scores':
            post_code = request.GET.get('post_code', '').strip()
            candidate_id = request.GET.get('candidate_id', '').strip()
            
            from apps.jobs.models import CentralCompetency, AISetting
            from apps.candidates.models import Candidate, JobApplication
            from django.db.models import Q
            import json
            import urllib.request
            
            candidate = get_object_or_404(Candidate, id=candidate_id, is_deleted=False)
            
            # Find candidate's best overlapping job
            comps = CentralCompetency.objects.filter(post_code=post_code, is_deleted=False).exclude(
                Q(title__in=['', None, 'بدون عنوان', 'بدون‌عنوان']) |
                Q(post_title__in=['', None, 'بدون عنوان', 'بدون‌عنوان'])
            )
            post_title = comps.first().post_title if comps.exists() else 'پست شبیه‌سازی شده'
            target_comps = [c for c in comps if is_functional_competency(c.title, c.competency_type)]
            target_comp_titles = [c.title for c in target_comps]
            target_comp_set = set(target_comp_titles)
            
            candidate_apps = JobApplication.objects.filter(candidate=candidate, is_deleted=False).select_related('job')
            best_app = None
            best_overlap_pct = 0
            best_shared_comps = []
            
            for app in candidate_apps:
                if app.job.code == post_code:
                    continue
                job_comps = {
                    jc.title for jc in app.job.selected_competencies.all()
                    if not jc.is_deleted and is_functional_competency(jc.title, jc.competency_type)
                }
                intersection = target_comp_set.intersection(job_comps)
                if len(target_comp_set) > 0:
                    overlap_pct = (len(intersection) / len(target_comp_set)) * 100
                else:
                    overlap_pct = 0
                
                if overlap_pct >= 50:
                    if overlap_pct > best_overlap_pct:
                        best_overlap_pct = overlap_pct
                        best_app = app
                        best_shared_comps = list(intersection)
                    elif overlap_pct == best_overlap_pct and best_app:
                        if app.final_score > best_app.final_score:
                            best_app = app
                            best_shared_comps = list(intersection)
            
            if not best_app:
                return HttpResponse(
                    '<div class="modal-body text-center py-4" style="direction: rtl;">'
                    '<div class="alert alert-warning text-xxs font-bold">هیچ ارزیابی همپوشانی برای این داوطلب یافت نشد.</div>'
                    '</div>'
                )
            
            ai_analysis = ""
            ai_setting = AISetting.get_active_setting()
            
            if ai_setting and ai_setting.api_key:
                try:
                    system_prompt = (
                        "شما یک متخصص ارشد سنجش و جذب منابع انسانی هستید.\n"
                        "وظیفه شما تحلیل قابلیت انتقال (Transferability) نتایج ارزیابی قبلی یک داوطلب به پست جدید است.\n"
                        "با توجه به لیست شایستگی‌های مشترک و نمره نهایی کسب‌شده داوطلب در ارزیابی قبلی، یک تحلیل بسیار کوتاه و خلاصه (حداکثر ۳ الی ۴ جمله) ارائه دهید شامل:\n"
                        "۱. آیا نمره کسب شده صلاحیت او را برای شایستگی‌های مشترک در پست جدید تأیید می‌کند؟\n"
                        "۲. چه بخش‌ها یا شایستگی‌های دیگری در پست جدید نیاز به مصاحبه یا ارزیابی مجدد دارد؟\n"
                        "پاسخ را به زبان فارسی، ساختاریافته و در قالب بندهای کوتاه بنویسید. حجم پاسخ بسیار محدود باشد (کمتر از ۱۵۰ کلمه)."
                    )
                    
                    comps_str = "، ".join(best_shared_comps)
                    user_prompt = (
                        f"نام داوطلب: {candidate.first_name} {candidate.last_name}\n"
                        f"پست جدید (هدف): {post_title}\n"
                        f"ارزیابی قبلی در شغل: {best_app.job.title}\n"
                        f"نمره نهایی کسب‌شده قبلی: {best_app.final_score}٪\n"
                        f"شایستگی‌های مشترک بین دو پست: {comps_str}"
                    )
                    
                    payload = {
                        "model": ai_setting.model_name,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.5
                    }
                    
                    url = f"{ai_setting.base_url.rstrip('/')}/chat/completions"
                    headers = {
                        "Authorization": f"Bearer {ai_setting.api_key}",
                        "Content-Type": "application/json"
                    }
                    
                    data = json.dumps(payload).encode('utf-8')
                    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
                    
                    with urllib.request.urlopen(req, timeout=10) as response:
                        if response.status == 200:
                            res_body = response.read().decode('utf-8')
                            res_json = json.loads(res_body)
                            ai_analysis = res_json['choices'][0]['message']['content'].strip()
                except Exception:
                    pass
            
            if not ai_analysis:
                # Fallback to local simulated assessment if offline or failed
                comps_str = "، ".join(best_shared_comps)
                ai_analysis = (
                    f"با توجه به کسب نمره {best_app.final_score}٪ در ارزیابی قبلی برای پست «{best_app.job.title}» و همپوشانی {round(best_overlap_pct)}٪ در شایستگی‌های مشترک ({comps_str})، "
                    f"صلاحیت عمومی کاندیدا در این بخش‌ها مطلوب و قابل قبول ارزیابی می‌شود. "
                    f"با این وجود، توصیه می‌شود بخش‌های اختصاصی و مهارتی پست هدف («{post_title}») که در ارزیابی قبلی غایب بوده‌اند، در فرآیند مصاحبه مجدداً سنجیده شوند."
                )
            
            context = {
                'candidate': candidate,
                'candidate_name': f"{candidate.first_name} {candidate.last_name}",
                'overlap_pct': round(best_overlap_pct),
                'source_job_title': best_app.job.title,
                'source_job_score': round(best_app.final_score),
                'shared_competencies': best_shared_comps,
                'ai_analysis': ai_analysis,
            }
            return render(request, 'jobs/partials/ai_talent_suitability_match.html', context)
        
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Total counts
        total_comps = CentralCompetency.objects.filter(is_deleted=False).count()
        context['total_count'] = total_comps
        
        # Distribution by Type
        type_dist = (
            CentralCompetency.objects.filter(is_deleted=False)
            .values('competency_type')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        context['type_distribution'] = type_dist
        
        # Unique Posts Count
        unique_posts_count = (
            CentralCompetency.objects.filter(is_deleted=False)
            .values('post_code')
            .distinct()
            .count()
        )
        context['unique_posts_count'] = unique_posts_count
        
        # Fetch some sample post patterns
        # Group by post code, select top posts by competency count
        top_posts = (
            CentralCompetency.objects.filter(is_deleted=False)
            .values('post_code', 'post_title')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        )
        
        post_patterns = []
        for post in top_posts:
            post_code = post['post_code']
            post_title = post['post_title']
            
            # Fetch competencies for this post
            comps = CentralCompetency.objects.filter(post_code=post_code, is_deleted=False)
            
            # Use calculate_assessment_plan helper
            # Need to mock the JobOpportunityCompetency models for calculate_assessment_plan
            class MockComp:
                def __init__(self, c):
                    self.code = c.code
                    self.title = c.title
                    self.competency_type = c.competency_type
                    self.importance = c.importance
                    self.level = c.level
                    
            mock_comps = [MockComp(c) for c in comps]
            plan = calculate_assessment_plan(mock_comps, round_to_five=True)
            
            post_patterns.append({
                'post_code': post_code,
                'post_title': post_title,
                'competencies_count': post['count'],
                'plan': plan['stages']
            })
            
        context['post_patterns'] = post_patterns
        
        # Calculate overlap suggestions for active JobOpportunities in progress
        from apps.jobs.models import JobOpportunity
        active_jobs = JobOpportunity.objects.filter(is_deleted=False).exclude(
            status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED]
        )
        
        job_comps = {}
        for job in active_jobs:
            comps_qs = job.selected_competencies.filter(is_deleted=False).values('title', 'competency_type')
            if comps_qs:
                filtered_dict = {
                    c['title']: c['competency_type'] 
                    for c in comps_qs 
                    if is_functional_competency(c['title'], c['competency_type'])
                }
                if filtered_dict:
                    job_comps[job.id] = {
                        'title': job.title,
                        'code': job.code,
                        'comps': filtered_dict
                    }
        
        overlap_suggestions = []
        job_ids = list(job_comps.keys())
        n = len(job_ids)
        for i in range(n):
            for j in range(i + 1, n):
                id1 = job_ids[i]
                id2 = job_ids[j]
                dict1 = job_comps[id1]['comps']
                dict2 = job_comps[id2]['comps']
                set1 = set(dict1.keys())
                set2 = set(dict2.keys())
                
                intersection = set1.intersection(set2)
                min_len = min(len(set1), len(set2))
                if min_len > 0:
                    overlap_pct = (len(intersection) / min_len) * 100
                else:
                    overlap_pct = 0
                
                if overlap_pct >= 80 and len(intersection) > 1:
                    # Determine which assessments are shared based on the intersection's competency types
                    shared_stages = []
                    has_written = False
                    has_skill = False
                    has_assessment_center = False
                    
                    for title in intersection:
                        ctype = dict1[title]
                        if ctype == 'KN':
                            has_written = True
                        elif ctype in ['SK', 'AB']:
                            has_skill = True
                        elif ctype in ['GE', 'ST']:
                            has_assessment_center = True
                    
                    if has_written:
                        shared_stages.append("آزمون کتبی مشترک")
                    if has_skill:
                        shared_stages.append("ارزیابی مهارتی مشترک")
                    if has_assessment_center:
                        shared_stages.append("کانون ارزیابی مشترک")
                        
                    overlap_suggestions.append({
                        'post1_title': job_comps[id1]['title'],
                        'post1_code': job_comps[id1]['code'],
                        'post2_title': job_comps[id2]['title'],
                        'post2_code': job_comps[id2]['code'],
                        'overlap_pct': round(overlap_pct),
                        'shared_count': len(intersection),
                        'shared_competencies': list(intersection)[:4],
                        'shared_stages': shared_stages
                    })
        
        overlap_suggestions.sort(key=lambda x: x['overlap_pct'], reverse=True)
        context['overlap_suggestions'] = overlap_suggestions[:6]
        
        return context


class JobCompetencyConfigView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]
    template_name = 'jobs/job_competency_config.html'

    def get_job(self, job_id):
        return get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)

    def get(self, request, job_id):
        job = self.get_job(job_id)
        
        # 1. Handle remote search request for posts
        action = request.GET.get('action', '').strip()
        if action == 'search_posts':
            q = request.GET.get('q', '').strip()
            
            # Fetch matching unique posts
            from django.db.models import Q, Count
            posts_query = CentralCompetency.objects.filter(is_deleted=False).exclude(
                Q(post_title__in=['', None, 'بدون عنوان', 'بدون‌عنوان']) |
                Q(title__in=['', None, 'بدون عنوان', 'بدون‌عنوان'])
            )
            if q:
                posts_query = posts_query.filter(
                    Q(post_code__icontains=q) | Q(post_title__icontains=q)
                )
            
            # Group by post_code and count the number of competencies
            unique_posts = (
                posts_query.values('post_code', 'post_title')
                .annotate(count=Count('id'))
                .order_by('post_code')[:50]
            )
            
            items = []
            for p in unique_posts:
                title = p['post_title'] or 'بدون عنوان'
                items.append({
                    'post_code': p['post_code'],
                    'display_name': f"{p['post_code']} - {title} ({p['count']} شایستگی)"
                })
                
            import json
            return HttpResponse(json.dumps({'items': items}), content_type='application/json')

        # 2. Render configuration page
        selected_comps = job.selected_competencies.filter(is_deleted=False)
        central_selected = selected_comps.filter(is_custom=False)
        custom_selected = selected_comps.filter(is_custom=True)
        custom_comps_list = []
        for c in custom_selected:
            custom_comps_list.append({
                'title': c.title,
                'competency_type': c.competency_type,
                'importance': c.importance,
                'level': c.level
            })
        selected_codes = set(c.code for c in central_selected)
        
        # Try to find a default post from the database by matching the job code or search in competencies
        suggested_post = None
        suggested_post_title = None
        suggested_post_count = 0
        
        if job.code:
            # Check if there are competencies in the bank for this post code
            post_exists = CentralCompetency.objects.filter(post_code=job.code, is_deleted=False).exists()
            if post_exists:
                suggested_post = job.code
                
        # If not, find the first post code of already selected competencies
        if not suggested_post and selected_comps.exists():
            first_comp = selected_comps.first()
            if first_comp.central_competency:
                suggested_post = first_comp.central_competency.post_code
                
        if suggested_post:
            comps_for_suggested = CentralCompetency.objects.filter(post_code=suggested_post, is_deleted=False)
            if comps_for_suggested.exists():
                suggested_post_title = comps_for_suggested.first().post_title
                suggested_post_count = comps_for_suggested.count()

        # Fetch existing saved weights and passing scores if they exist
        db_stages = job.stages.filter(is_deleted=False)
        custom_weights = None
        custom_passing_scores = None
        deactivated_stages = []
        if db_stages.exists():
            custom_weights = {}
            custom_passing_scores = {}
            active_stages_in_db = set()
            for stage in db_stages:
                if stage.stage_type in ['EXAM', 'SKILL_TEST', 'INTERVIEW', 'ASSESSMENT']:
                    custom_weights[stage.stage_type] = stage.weight
                    custom_passing_scores[stage.stage_type] = int(stage.passing_score)
                    active_stages_in_db.add(stage.stage_type)
            
            # Find recommended stages
            plan_temp = calculate_assessment_plan(selected_comps, bypass_limits=job.bypass_limits)
            for k, s in plan_temp['stages'].items():
                if k != 'SCREENING' and s.get('is_active', False) and k not in active_stages_in_db:
                    deactivated_stages.append(k)

        deactivated_stages_str = ','.join(deactivated_stages)
        round_to_five = request.GET.get('round_to_five', 'on') == 'on'

        # Get suggested workflows based on current selection
        plan_res = calculate_assessment_plan(
            selected_comps,
            custom_weights=custom_weights,
            custom_passing_scores=custom_passing_scores,
            round_to_five=round_to_five,
            deactivated_stages=deactivated_stages,
            bypass_limits=job.bypass_limits
        )
        active_stage_keys = [k for k, s in plan_res['stages'].items() if s.get('is_active', False)]
        from .utils import suggest_workflow_templates
        suggested_workflows = suggest_workflow_templates(active_stage_keys)
        selected_workflow_id = job.workflow.id if job.workflow else None

        competency_models = CompetencyModel.objects.filter(is_deleted=False)

        context = {
            'job': job,
            'selected_competencies': central_selected,
            'selected_codes': selected_codes,
            'custom_competencies_list': custom_comps_list,
            'suggested_post': suggested_post,
            'suggested_post_title': suggested_post_title,
            'suggested_post_count': suggested_post_count,
            'calculated_plan': plan_res['stages'],
            'suggested_workflows': suggested_workflows,
            'selected_workflow_id': selected_workflow_id,
            'round_to_five': round_to_five,
            'bypass_limits': job.bypass_limits,
            'competency_models': competency_models,
            'deactivated_stages_str': deactivated_stages_str
        }
        return render(request, self.template_name, context)

    def post(self, request, job_id):
        job = self.get_job(job_id)
        action = request.POST.get('action', '').strip()

        def get_clean_ids(key):
            vals = request.POST.getlist(key)
            if len(vals) == 1 and ',' in vals[0]:
                vals = vals[0].split(',')
            elif len(vals) == 1 and vals[0].startswith('[') and vals[0].endswith(']'):
                import json
                try:
                    vals = json.loads(vals[0])
                except Exception:
                    pass
            return [int(v) for v in vals if str(v).strip().isdigit() or isinstance(v, int)]

        # HTMX partial renders (Live Preview)
        if action == 'preview':
            comp_ids = get_clean_ids('selected_competencies')
            # Fetch details from CentralCompetency
            comps = CentralCompetency.objects.filter(id__in=comp_ids, is_deleted=False)
            
            # Fetch custom weights
            recalculate_weights = request.POST.get('recalculate_weights') == 'true'
            custom_weights = {}
            if not recalculate_weights:
                for key in ['EXAM', 'SKILL_TEST', 'INTERVIEW', 'ASSESSMENT']:
                    val = request.POST.get(f'stage_weight_{key}')
                    if val is not None and val.strip() != '':
                        custom_weights[key] = val

            # Fetch custom passing scores
            custom_passing_scores = {}
            for key in ['EXAM', 'SKILL_TEST', 'INTERVIEW', 'ASSESSMENT']:
                val = request.POST.get(f'stage_passing_score_{key}')
                if val is not None and val.strip() != '':
                    custom_passing_scores[key] = val
            
            selected_workflow_id = request.POST.get('workflow_template_id')
            
            # Parse manual/custom competencies
            custom_comps_raw = request.POST.getlist('custom_competencies')
            custom_comps_parsed = []
            for cc_json in custom_comps_raw:
                try:
                    import json
                    cc_data = json.loads(cc_json)
                    custom_comps_parsed.append(cc_data)
                except Exception:
                    pass

            # Temporary list for calculation
            class TempComp:
                def __init__(self, title, competency_type, importance, level, code="CUSTOM"):
                    self.code = code
                    self.title = title
                    self.competency_type = competency_type
                    self.importance = int(importance)
                    self.level = int(level)
            
            temp_comps = [
                TempComp(c.title, c.competency_type, c.importance, c.level, c.code)
                for c in comps
            ]
            for cc in custom_comps_parsed:
                temp_comps.append(
                    TempComp(cc['title'], cc['competency_type'], cc['importance'], cc['level'])
                )

            round_to_five = request.POST.get('round_to_five') == 'on'
            bypass_limits = request.POST.get('bypass_limits') == 'on'
            deactivated_stages_raw = request.POST.get('deactivated_stages', '').strip()
            deactivated_stages = [s.strip() for s in deactivated_stages_raw.split(',') if s.strip()]

            plan_res = calculate_assessment_plan(
                temp_comps,
                custom_weights=custom_weights,
                custom_passing_scores=custom_passing_scores,
                round_to_five=round_to_five,
                deactivated_stages=deactivated_stages,
                bypass_limits=bypass_limits
            )
            
            active_stage_keys = [k for k, s in plan_res['stages'].items() if s.get('is_active', False)]
            from .utils import suggest_workflow_templates
            suggested_workflows = suggest_workflow_templates(active_stage_keys)
            
            context = {
                'job': job,
                'calculated_plan': plan_res['stages'],
                'errors': plan_res.get('errors', []),
                'suggested_workflows': suggested_workflows,
                'selected_workflow_id': selected_workflow_id,
                'deactivated_stages_str': deactivated_stages_raw,
                'bypass_limits': bypass_limits
            }
            # Renders only the preview table part
            return render(request, 'jobs/partials/competency_preview_table.html', context)

        elif action == 'load_post_comps':
            # HTMX call to load competencies of a selected post
            post_code = request.POST.get('post_code', '').strip()
            comps = CentralCompetency.objects.filter(post_code=post_code, is_deleted=False)
            selected_comps = job.selected_competencies.filter(is_deleted=False)
            selected_codes = set(c.code for c in selected_comps)
            
            context = {
                'post_competencies': comps,
                'selected_codes': selected_codes
            }
            return render(request, 'jobs/partials/post_competencies_list.html', context)

        elif action == 'save':
            from django.contrib import messages
            comp_ids = get_clean_ids('selected_competencies')
            
            # Fetch custom weights
            custom_weights = {}
            for key in ['EXAM', 'SKILL_TEST', 'INTERVIEW', 'ASSESSMENT']:
                val = request.POST.get(f'stage_weight_{key}')
                if val is not None and val.strip() != '':
                    custom_weights[key] = val

            # Fetch custom passing scores
            custom_passing_scores = {}
            for key in ['EXAM', 'SKILL_TEST', 'INTERVIEW', 'ASSESSMENT']:
                val = request.POST.get(f'stage_passing_score_{key}')
                if val is not None and val.strip() != '':
                    custom_passing_scores[key] = val
                    
            # 1. First validate selection using calculate_assessment_plan (before writing to DB)
            central_comps = CentralCompetency.objects.filter(id__in=comp_ids, is_deleted=False)
            
            # Parse manual/custom competencies
            custom_comps_raw = request.POST.getlist('custom_competencies')
            custom_comps_parsed = []
            for cc_json in custom_comps_raw:
                try:
                    import json
                    cc_data = json.loads(cc_json)
                    custom_comps_parsed.append(cc_data)
                except Exception:
                    pass

            class TempComp:
                def __init__(self, title, competency_type, importance, level, code="CUSTOM"):
                    self.code = code
                    self.title = title
                    self.competency_type = competency_type
                    self.importance = int(importance)
                    self.level = int(level)
            
            temp_comps = [
                TempComp(c.title, c.competency_type, c.importance, c.level, c.code)
                for c in central_comps
            ]
            for cc in custom_comps_parsed:
                temp_comps.append(
                    TempComp(cc['title'], cc['competency_type'], cc['importance'], cc['level'])
                )

            round_to_five = request.POST.get('round_to_five') == 'on'
            bypass_limits = request.POST.get('bypass_limits') == 'on'
            deactivated_stages_raw = request.POST.get('deactivated_stages', '').strip()
            deactivated_stages = [s.strip() for s in deactivated_stages_raw.split(',') if s.strip()]

            plan_res = calculate_assessment_plan(
                temp_comps,
                custom_weights=custom_weights,
                custom_passing_scores=custom_passing_scores,
                round_to_five=round_to_five,
                deactivated_stages=deactivated_stages,
                bypass_limits=bypass_limits
            )
            stages_data = plan_res['stages']
            
            # Check for validation errors
            if plan_res.get('errors') or not stages_data:
                errors = plan_res.get('errors', [])
                if not stages_data and not errors:
                    errors.append("هیچ شایستگی مناسبی برای سنجش انتخاب نشده است. لطفاً حداقل یک شایستگی با نوع KN، SK، AB، GE یا ST انتخاب کنید.")
                
                # Retrieve matching suggested workflows for the error screen
                from .utils import suggest_workflow_templates
                active_stage_keys = [k for k, s in stages_data.items() if s.get('is_active', False)]
                suggested_workflows = suggest_workflow_templates(active_stage_keys)
                
                # Prepare suggested post context
                suggested_post = request.POST.get('post_code', '').strip()
                suggested_post_title = None
                suggested_post_count = 0
                if suggested_post:
                    comps_for_suggested = CentralCompetency.objects.filter(post_code=suggested_post, is_deleted=False)
                    if comps_for_suggested.exists():
                        suggested_post_title = comps_for_suggested.first().post_title
                        suggested_post_count = comps_for_suggested.count()
                
                context = {
                    'job': job,
                    'selected_competencies': central_comps,
                    'selected_codes': set(cc.code for cc in central_comps),
                    'custom_competencies_list': custom_comps_parsed,
                    'suggested_post': suggested_post,
                    'suggested_post_title': suggested_post_title,
                    'suggested_post_count': suggested_post_count,
                    'calculated_plan': stages_data,
                    'errors': errors,
                    'suggested_workflows': suggested_workflows,
                    'selected_workflow_id': request.POST.get('workflow_template_id'),
                    'round_to_five': round_to_five,
                    'bypass_limits': bypass_limits,
                    'deactivated_stages_str': deactivated_stages_raw
                }
                return render(request, self.template_name, context)

            # 2. Validation passed! Now save to DB inside transaction
            with transaction.atomic():
                # Link selected workflow template to the job first (will trigger default stage copying if changed)
                workflow_id = request.POST.get('workflow_template_id')
                if workflow_id:
                    from apps.jobs.models import WorkflowTemplate
                    try:
                        workflow = WorkflowTemplate.objects.get(id=workflow_id, is_deleted=False)
                        job.workflow = workflow
                    except WorkflowTemplate.DoesNotExist:
                        pass
                
                # Change job status to PLANNING if it was RECEIVED
                if job.status == JobOpportunity.STATUS_RECEIVED:
                    job.status = JobOpportunity.STATUS_PLANNING
                
                job.bypass_limits = bypass_limits
                job.save()

                # Soft delete current job competencies
                job.selected_competencies.filter(is_deleted=False).update(
                    is_deleted=True,
                    deleted_at=timezone.now()
                )
                
                # Add newly selected competencies
                new_selected_comps = []
                for cc in central_comps:
                    # Look for existing soft-deleted first
                    jc = JobOpportunityCompetency.all_objects.filter(
                        job=job,
                        code=cc.code,
                        central_competency=cc
                    ).first()
                    
                    if jc:
                        jc.is_deleted = False
                        jc.deleted_at = None
                        jc.title = cc.title
                        jc.competency_type = cc.competency_type
                        jc.importance = cc.importance
                        jc.level = cc.level
                        jc.is_custom = False
                        jc.save()
                    else:
                        jc = JobOpportunityCompetency.objects.create(
                            job=job,
                            central_competency=cc,
                            code=cc.code,
                            title=cc.title,
                            competency_type=cc.competency_type,
                            importance=cc.importance,
                            level=cc.level,
                            is_custom=False
                        )
                    new_selected_comps.append(jc)

                # Add manually created competencies
                import uuid
                for cc in custom_comps_parsed:
                    custom_code = f"MANUAL-{uuid.uuid4().hex[:8]}"
                    jc = JobOpportunityCompetency.objects.create(
                        job=job,
                        central_competency=None,
                        code=custom_code,
                        title=cc['title'],
                        competency_type=cc['competency_type'],
                        importance=cc['importance'],
                        level=cc['level'],
                        is_custom=True
                    )
                    new_selected_comps.append(jc)

                # Now, soft delete current job stages (including any copied default stages from job.save())
                job.stages.filter(is_deleted=False).update(
                    is_deleted=True,
                    deleted_at=timezone.now()
                )

                # Create new customized stages and assessment competencies
                seq = 1
                for key, s_info in stages_data.items():
                    if not s_info.get('is_active', False):
                        continue
                    # Create the JobOpportunityStage
                    stage = JobOpportunityStage.objects.create(
                        job=job,
                        name=s_info['name'],
                        weight=s_info['weight'],
                        sequence=seq,
                        passing_score=s_info['passing_score'],
                        stage_type=key
                    )
                    
                    # Create AssessmentCompetency records under this stage
                    for c_info in s_info['competencies']:
                        AssessmentCompetency.objects.create(
                            stage=stage,
                            name=c_info['title'],
                            weight=c_info['weight']
                        )
                    seq += 1
                job.sync_application_stages()

            messages.success(request, "شایستگی‌های فرصت شغلی و سند Assessment Plan با موفقیت ثبت و الگوی فرآیند مربوطه اعمال گردید.")
            return redirect('job_list')

        messages.error(request, "عملیات نامعتبر است.")
        return redirect('job_list')


class JobAssessmentPlanPrintView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = JobOpportunity
    template_name = 'jobs/assessment_plan_print.html'
    context_object_name = 'job'
    pk_url_kwarg = 'job_id'
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
        UserProfile.ROLE_DEPARTMENT_USER,
        UserProfile.ROLE_READ_ONLY_AUDITOR,
    ]

    def get_queryset(self):
        return JobOpportunity.objects.filter(is_deleted=False).prefetch_related('stages', 'stages__competencies')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Fetch the selected competencies snapshot to display
        context['selected_competencies'] = self.object.selected_competencies.filter(is_deleted=False)
        return context


class JobExamSpecificationPrintView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = JobOpportunity
    template_name = 'jobs/exam_specification_print.html'
    context_object_name = 'job'
    pk_url_kwarg = 'job_id'
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
        UserProfile.ROLE_DEPARTMENT_USER,
        UserProfile.ROLE_READ_ONLY_AUDITOR,
    ]

    def get_queryset(self):
        return JobOpportunity.objects.filter(is_deleted=False).prefetch_related('stages', 'stages__competencies')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Fetch the written exam stage(s)
        exam_stages = self.object.stages.filter(stage_type='EXAM', is_deleted=False).order_by('sequence')
        context['exam_stages'] = exam_stages
        
        # If there are exam stages, collect competencies and map their levels/importance
        exam_competencies = []
        for stage in exam_stages:
            for comp in stage.competencies.filter(is_deleted=False):
                # Find matching JobOpportunityCompetency snapshot to get the required level and importance
                jc = self.object.selected_competencies.filter(title=comp.name, is_deleted=False).first()
                exam_competencies.append({
                    'code': jc.code if jc else 'N/A',
                    'name': comp.name,
                    'stage_name': stage.name,
                    'weight': comp.weight,
                    'level': jc.get_level_display() if jc else 'نامشخص',
                    'importance': jc.get_importance_display() if jc else 'نامشخص',
                    'type': jc.get_competency_type_display() if jc else 'نامشخص'
                })
        
        context['exam_competencies'] = exam_competencies
        return context


class SearchPostsApiView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def get(self, request):
        q = request.GET.get('q', '').strip()
        from django.db.models import Q, Count
        posts_query = CentralCompetency.objects.filter(is_deleted=False).exclude(
            Q(post_title__in=['', None, 'بدون عنوان', 'بدون‌عنوان']) |
            Q(title__in=['', None, 'بدون عنوان', 'بدون‌عنوان'])
        )
        if q:
            posts_query = posts_query.filter(
                Q(post_code__icontains=q) | Q(post_title__icontains=q)
            )
        
        unique_posts = (
            posts_query.values('post_code', 'post_title')
            .annotate(count=Count('id'))
            .order_by('post_code')[:50]
        )
        
        items = []
        for p in unique_posts:
            title = p['post_title'] or 'بدون عنوان'
            items.append({
                'post_code': p['post_code'],
                'display_name': f"{p['post_code']} - {title} ({p['count']} شایستگی)"
            })
            
        import json
        return HttpResponse(json.dumps({'items': items}), content_type='application/json')


class SearchPostsDetailApiView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def get(self, request):
        post_code = request.GET.get('post_code', '').strip()
        from apps.jobs.models import CentralCompetency
        comp = CentralCompetency.objects.filter(post_code=post_code, is_deleted=False).first()
        if not comp:
            import json
            return HttpResponse(json.dumps({'error': 'Not found'}), status=404, content_type='application/json')
        
        # Map job category from post_title
        title = comp.post_title or ''
        job_category = ''
        if 'کارشناس مدیریت' in title:
            job_category = 'کارشناس مدیریت'
        elif 'کارشناس مسئول' in title:
            job_category = 'کارشناس مسئول'
        elif 'کارشناس' in title:
            job_category = 'کارشناس'
        elif 'کاردان مسئول' in title:
            job_category = 'کاردان مسئول'
        elif 'کاردان' in title:
            job_category = 'کاردان'
        elif 'اپراتور' in title or 'تعمیرکار' in title:
            job_category = 'اپراتور - تعمیرکار'
            
        data = {
            'title': comp.post_title or '',
            'department': comp.management_name or '',
            'unit': comp.section_name or '',
            'job_category': job_category
        }
        import json
        return HttpResponse(json.dumps(data), content_type='application/json')


class SearchCompetenciesApiView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def get(self, request):
        q = request.GET.get('q', '').strip()
        from django.db.models import Q
        comps_query = CentralCompetency.objects.filter(is_deleted=False)
        if q:
            comps_query = comps_query.filter(
                Q(title__icontains=q) | Q(code__icontains=q)
            )
        
        items = []
        seen_titles = set()
        for c in comps_query.order_by('title')[:300]:
            title_clean = c.title.strip()
            if title_clean not in seen_titles:
                seen_titles.add(title_clean)
                items.append({
                    'title': title_clean,
                    'competency_type': c.competency_type,
                    'importance': c.importance,
                    'level': c.level,
                    'display_name': f"{title_clean} ({c.get_competency_type_display()} - {c.get_importance_display()} - {c.get_level_display()})"
                })
                if len(items) >= 50:
                    break
                    
        import json
        return HttpResponse(json.dumps({'items': items}), content_type='application/json')


import csv
class CustomCompetenciesReportView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]
    template_name = 'jobs/custom_competencies_report.html'
    context_object_name = 'custom_competencies'

    def get_queryset(self):
        qs = JobOpportunityCompetency.objects.filter(
            is_custom=True, 
            is_deleted=False
        ).select_related('job', 'job__assigned_recruiter').order_by('-created_at')
        
        q = self.request.GET.get('q', '').strip()
        if q:
            from django.db.models import Q
            qs = qs.filter(
                Q(title__icontains=q) | 
                Q(job__title__icontains=q) | 
                Q(job__code__icontains=q)
            )
            
        comp_type = self.request.GET.get('competency_type', '').strip()
        if comp_type:
            qs = qs.filter(competency_type=comp_type)
            
        importance = self.request.GET.get('importance', '').strip()
        if importance:
            qs = qs.filter(importance=importance)
            
        level = self.request.GET.get('level', '').strip()
        if level:
            qs = qs.filter(level=level)
            
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.request.GET.get('q', '').strip()
        context['competency_type'] = self.request.GET.get('competency_type', '').strip()
        context['importance'] = self.request.GET.get('importance', '').strip()
        context['level'] = self.request.GET.get('level', '').strip()
        return context

    def get(self, request, *args, **kwargs):
        # Handle CSV export action
        if request.GET.get('export') == 'csv':
            response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
            response['Content-Disposition'] = 'attachment; filename="custom_competencies_report.csv"'
            
            writer = csv.writer(response)
            writer.writerow([
                'ردیف', 'عنوان شایستگی', 'نوع شایستگی', 'سطح مورد نیاز',
                'اهمیت', 'کد پست فرصت شغلی', 'فرصت شغلی مربوطه', 'کارشناس جذب', 'تاریخ ایجاد'
            ])
            
            queryset = self.get_queryset()
            
            type_map = {
                'KN': 'دانش',
                'SK': 'مهارت',
                'AB': 'توانایی',
                'GE': 'رفتاری',
                'ST': 'ارزش‌ها و سبک‌ها',
                'PR': 'گردشکار و فرآیندها',
                'CQ': 'گواهینامه‌ها و صلاحیت‌ها',
                'IN': 'علایق حرفه‌ای'
            }
            imp_map = {1: 'محوری', 2: 'تکلیف محور', 3: 'حداقلی'}
            lvl_map = {1: 'آشنایی', 2: 'توانایی', 3: 'تسلط'}
            
            for idx, c in enumerate(queryset, 1):
                recruiter = c.job.assigned_recruiter
                recruiter_name = recruiter.get_full_name() if recruiter else '-'
                created_date = c.created_at.strftime('%Y-%m-%d')
                writer.writerow([
                    idx,
                    c.title,
                    type_map.get(c.competency_type, c.competency_type),
                    lvl_map.get(c.level, c.level),
                    imp_map.get(c.importance, c.importance),
                    c.job.code,
                    c.job.title,
                    recruiter_name,
                    created_date
                ])
            return response
            
        return super().get(request, *args, **kwargs)


class AISettingView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN]
    template_name = 'jobs/ai_setting.html'

    def get(self, request):
        from apps.jobs.models import AISetting
        from apps.jobs.forms import AISettingForm
        
        setting = AISetting.objects.first()
        if not setting:
            setting = AISetting(base_url="https://api.avalai.ir/v1", model_name="gpt-4o", is_active=True)
            
        form = AISettingForm(instance=setting)
        return render(request, self.template_name, {'form': form, 'setting': setting})

    def post(self, request):
        from apps.jobs.models import AISetting
        from apps.jobs.forms import AISettingForm
        
        action = request.POST.get('action', 'save').strip()
        
        if action == 'test_connection':
            api_key = request.POST.get('api_key', '').strip()
            base_url = request.POST.get('base_url', '').strip()
            model_name = request.POST.get('model_name', '').strip()
            
            if not api_key:
                return HttpResponse(
                    '<div class="alert alert-warning d-flex align-items-center gap-2 m-0 animate__animated animate__fadeIn">'
                    '<span>⚠ لطفاً کلید API را وارد کنید.</span>'
                    '</div>'
                )
            
            try:
                import urllib.request
                import json
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": model_name,
                    "messages": [{"role": "user", "content": "Respond with only one word: Connected."}],
                    "max_tokens": 5
                }
                url = f"{base_url.rstrip('/')}/chat/completions"
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(url, data=data, headers=headers, method='POST')
                
                with urllib.request.urlopen(req, timeout=6) as response:
                    if response.status == 200:
                        res_body = response.read().decode('utf-8')
                        res_json = json.loads(res_body)
                        ans = res_json['choices'][0]['message']['content'].strip()
                        html = (
                            f'<div class="alert alert-success d-flex align-items-center gap-2 m-0 animate__animated animate__fadeIn">'
                            f'<span>✓ اتصال زنده با موفقیت برقرار شد! پاسخ سرور: {ans}</span>'
                            f'</div>'
                        )
                    else:
                        html = (
                            f'<div class="alert alert-danger d-flex align-items-center gap-2 m-0 animate__animated animate__fadeIn">'
                            f'<span>✗ خطا در برقراری اتصال (کد وضعیت {response.status}): {response.reason}</span>'
                            f'</div>'
                        )
            except urllib.error.HTTPError as he:
                try:
                    error_text = he.read().decode('utf-8')[:120]
                except Exception:
                    error_text = str(he)
                html = (
                    f'<div class="alert alert-danger d-flex align-items-center gap-2 m-0 animate__animated animate__fadeIn">'
                    f'<span>✗ خطا در برقراری اتصال (کد وضعیت {he.code}): {error_text}</span>'
                    f'</div>'
                )
            except Exception as e:
                html = (
                    f'<div class="alert alert-danger d-flex align-items-center gap-2 m-0 animate__animated animate__fadeIn">'
                    f'<span>✗ خطا در برقراری ارتباط: {str(e)}</span>'
                    f'</div>'
                )
            return HttpResponse(html)
            
        else:
            setting = AISetting.objects.first()
            if setting:
                form = AISettingForm(request.POST, instance=setting)
            else:
                form = AISettingForm(request.POST)
                
            if form.is_valid():
                form.save()
                from django.contrib import messages
                messages.success(request, "تنظیمات هوش مصنوعی با موفقیت ذخیره شد.")
                return redirect('ai_setting')
            
            return render(request, self.template_name, {'form': form, 'setting': setting})


class JobAIStrategyPrintView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def get(self, request):
        post_code = request.GET.get('post_code', '').strip()
        from apps.jobs.models import CentralCompetency
        
        comps = CentralCompetency.objects.filter(post_code=post_code, is_deleted=False)
        if not comps.exists():
            return HttpResponse('پست سازمانی یافت نشد.', status=404)
            
        post_title = comps.first().post_title or 'پست سازمانی'
        
        # Get AI recommendation (check cache/fallback)
        ai_data = get_ai_recommendation(post_code, post_title, comps, refresh=False)
        
        context = {
            'post_code': post_code,
            'post_title': post_title,
            'opt_advice': ai_data['opt_advice'],
            'scenario': ai_data['scenario'],
            'questions': ai_data['questions'],
            'benchmark_mappings': ai_data.get('benchmark_mappings', []),
            'is_live': ai_data['is_live'],
            'cached': ai_data['cached']
        }
        
        return render(request, 'jobs/print_ai_strategy.html', context)


class OrganizationSettingView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN]
    template_name = 'jobs/organization_setting.html'

    def get(self, request):
        from apps.jobs.models import OrganizationSetting, JobOpportunity
        from apps.jobs.forms import OrganizationSettingForm
        from apps.accounts.models import SMSTemplate
        from apps.candidates.models import JobApplication, ApplicationStageState
        
        setting = OrganizationSetting.get_active_setting()
        form = OrganizationSettingForm(instance=setting)
        
        # اطلاعات مورد نیاز برای تب مدیریت پیامک‌های دستی
        templates = SMSTemplate.objects.filter(is_deleted=False)
        jobs = JobOpportunity.objects.filter(is_deleted=False)
        app_statuses = JobApplication.STATUS_CHOICES
        stage_statuses = ApplicationStageState.STATUS_CHOICES
        
        from apps.core.license import get_license_usage_stats
        license_stats = get_license_usage_stats(request)
        
        context = {
            'form': form,
            'setting': setting,
            'templates': templates,
            'jobs': jobs,
            'app_statuses': app_statuses,
            'stage_statuses': stage_statuses,
            'license_stats': license_stats,
        }
        
        edit_id = request.GET.get('edit_template')
        if edit_id:
            try:
                context['edit_template'] = SMSTemplate.objects.get(id=edit_id, is_deleted=False)
            except SMSTemplate.DoesNotExist:
                pass
                
        return render(request, self.template_name, context)

    def post(self, request):
        from apps.jobs.models import OrganizationSetting
        from apps.jobs.forms import OrganizationSettingForm
        from django.contrib import messages
        
        setting = OrganizationSetting.get_active_setting()
        form = OrganizationSettingForm(request.POST, request.FILES, instance=setting)
        if form.is_valid():
            instance = form.save(commit=False)
            # Force update organization name if a valid license key is present
            if instance.license_key:
                from apps.core.license import verify_license_key
                license_stats = verify_license_key(instance.license_key, current_host=request.get_host())
                if license_stats['is_valid']:
                    instance.name = license_stats['licensee']
            instance.save()
            messages.success(request, "تنظیمات سازمان با موفقیت ذخیره شد.")
            return redirect('organization_setting')
        
        # اگر خطا وجود داشت کل کانتکست گت را لود می‌کنیم تا تب‌ها خراب نشوند
        from apps.jobs.models import JobOpportunity
        from apps.accounts.models import SMSTemplate
        from apps.candidates.models import JobApplication, ApplicationStageState
        from apps.core.license import get_license_usage_stats
        
        templates = SMSTemplate.objects.filter(is_deleted=False)
        jobs = JobOpportunity.objects.filter(is_deleted=False)
        app_statuses = JobApplication.STATUS_CHOICES
        stage_statuses = ApplicationStageState.STATUS_CHOICES
        license_stats = get_license_usage_stats(request)
        
        context = {
            'form': form,
            'setting': setting,
            'templates': templates,
            'jobs': jobs,
            'app_statuses': app_statuses,
            'stage_statuses': stage_statuses,
            'license_stats': license_stats,
        }
        return render(request, self.template_name, context)


# --- Competency Model Management Views ---
from django.http import JsonResponse
from django.urls import reverse
from apps.jobs.models import CompetencyModel, CompetencyModelItem

TYPE_CHOICES = [
    ('KN', 'دانش (Knowledge)'),
    ('SK', 'مهارت (Skill)'),
    ('AB', 'توانایی (Ability)'),
    ('GE', 'رفتاری (General/Behavioral)'),
    ('ST', 'ارزش‌ها و سبک‌ها (Styles & Values)'),
]
IMPORTANCE_CHOICES = [
    (1, '۱ - محوری'),
    (2, '۲ - تکلیف محور'),
    (3, '۳ - حداقلی'),
]
LEVEL_CHOICES = [
    (1, '۱ - آشنایی'),
    (2, '۲ - توانایی'),
    (3, '۳ - تسلط'),
]

class CompetencyModelListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = CompetencyModel
    template_name = 'jobs/competency_model_list.html'
    context_object_name = 'models'
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def get_queryset(self):
        return CompetencyModel.objects.filter(is_deleted=False).order_by('name')

    def get(self, request, *args, **kwargs):
        action = request.GET.get('action', '').strip()
        model_id = request.GET.get('model_id', '').strip()
        
        if action == 'create_form':
            context = {'action': 'create'}
            return render(request, 'jobs/partials/competency_model_form.html', context)
            
        elif action == 'edit_form':
            model_obj = get_object_or_404(CompetencyModel, id=model_id, is_deleted=False)
            context = {'action': 'edit', 'model': model_obj}
            return render(request, 'jobs/partials/competency_model_form.html', context)
            
        elif model_id and request.headers.get('HX-Request') == 'true':
            model_obj = get_object_or_404(CompetencyModel, id=model_id, is_deleted=False)
            items = model_obj.items.filter(is_deleted=False)
            context = {
                'model': model_obj,
                'items': items,
                'type_choices': TYPE_CHOICES,
                'importance_choices': IMPORTANCE_CHOICES,
                'level_choices': LEVEL_CHOICES,
            }
            return render(request, 'jobs/partials/competency_model_detail.html', context)
            
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        model_id = self.request.GET.get('model_id', '').strip()
        if model_id:
            try:
                model_obj = CompetencyModel.objects.get(id=model_id, is_deleted=False)
                context['selected_model'] = model_obj
                context['items'] = model_obj.items.filter(is_deleted=False)
            except CompetencyModel.DoesNotExist:
                pass
        context['type_choices'] = TYPE_CHOICES
        context['importance_choices'] = IMPORTANCE_CHOICES
        context['level_choices'] = LEVEL_CHOICES
        return context


class CompetencyModelManageView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action', '').strip()
        model_id = request.POST.get('model_id', '').strip()
        
        if action == 'delete':
            model_obj = get_object_or_404(CompetencyModel, id=model_id, is_deleted=False)
            model_obj.items.filter(is_deleted=False).update(
                is_deleted=True,
                deleted_at=timezone.now()
            )
            model_obj.is_deleted = True
            model_obj.deleted_at = timezone.now()
            model_obj.save()
            from django.contrib import messages
            messages.success(request, "مدل شایستگی با موفقیت حذف شد.")
            return redirect('competency_model_list')
            
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        
        if model_id:
            model_obj = get_object_or_404(CompetencyModel, id=model_id, is_deleted=False)
            model_obj.name = name
            model_obj.description = description
            model_obj.save()
            from django.contrib import messages
            messages.success(request, "اطلاعات مدل شایستگی با موفقیت بروزرسانی شد.")
            return redirect(reverse('competency_model_list') + f'?model_id={model_obj.id}')
        else:
            model_obj = CompetencyModel.objects.create(
                name=name,
                description=description
            )
            from django.contrib import messages
            messages.success(request, "مدل شایستگی جدید با موفقیت ایجاد شد.")
            return redirect(reverse('competency_model_list') + f'?model_id={model_obj.id}')


class CompetencyModelItemManageView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def post(self, request, model_id, *args, **kwargs):
        model_obj = get_object_or_404(CompetencyModel, id=model_id, is_deleted=False)
        action = request.POST.get('action', '').strip()
        
        if action == 'delete':
            item_id = request.POST.get('item_id', '').strip()
            item = get_object_or_404(CompetencyModelItem, id=item_id, competency_model=model_obj, is_deleted=False)
            item.is_deleted = True
            item.deleted_at = timezone.now()
            item.save()
        else:
            title = request.POST.get('title', '').strip()
            competency_type = request.POST.get('competency_type', 'GE').strip()
            importance = int(request.POST.get('importance', 1))
            level = int(request.POST.get('level', 2))
            
            import uuid
            code = f"MODEL-{uuid.uuid4().hex[:8]}"
            
            CompetencyModelItem.objects.create(
                competency_model=model_obj,
                title=title,
                competency_type=competency_type,
                importance=importance,
                level=level,
                code=code
            )
            
        if request.headers.get('HX-Request') != 'true':
            return redirect(reverse('competency_model_list') + f'?model_id={model_obj.id}')

        items = model_obj.items.filter(is_deleted=False)
        context = {
            'model': model_obj,
            'items': items,
            'type_choices': TYPE_CHOICES,
            'importance_choices': IMPORTANCE_CHOICES,
            'level_choices': LEVEL_CHOICES,
        }
        return render(request, 'jobs/partials/competency_model_detail.html', context)


class CompetencyModelDetailApiView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def get(self, request, model_id, *args, **kwargs):
        model_obj = get_object_or_404(CompetencyModel, id=model_id, is_deleted=False)
        items = model_obj.items.filter(is_deleted=False)
        
        items_data = []
        for item in items:
            items_data.append({
                'title': item.title,
                'competency_type': item.competency_type,
                'importance': item.importance,
                'level': item.level,
                'code': item.code,
                'model_name': model_obj.name,
            })
            
        data = {
            'id': model_obj.id,
            'name': model_obj.name,
            'description': model_obj.description,
            'items': items_data,
        }
        return JsonResponse(data)

