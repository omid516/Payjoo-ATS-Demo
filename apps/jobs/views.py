from django.shortcuts import render, get_object_or_404
from django.views.generic import ListView, CreateView, UpdateView
from django.views import View
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.db import transaction
from django.utils import timezone

from apps.accounts.permissions import RoleRequiredMixin
from apps.accounts.models import UserProfile
from .models import JobOpportunity, JobOpportunityStage, WorkflowTemplate, WorkflowStageTemplate
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
            plan = calculate_assessment_plan(mock_comps)
            
            post_patterns.append({
                'post_code': post_code,
                'post_title': post_title,
                'competencies_count': post['count'],
                'plan': plan['stages']
            })
            
        context['post_patterns'] = post_patterns
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
            posts_query = CentralCompetency.objects.filter(is_deleted=False)
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
        if db_stages.exists():
            custom_weights = {}
            custom_passing_scores = {}
            for stage in db_stages:
                if stage.stage_type in ['EXAM', 'SKILL_TEST', 'INTERVIEW', 'ASSESSMENT']:
                    custom_weights[stage.stage_type] = stage.weight
                    custom_passing_scores[stage.stage_type] = int(stage.passing_score)

        # Get suggested workflows based on current selection
        plan_res = calculate_assessment_plan(
            selected_comps,
            custom_weights=custom_weights,
            custom_passing_scores=custom_passing_scores
        )
        active_stage_keys = list(plan_res['stages'].keys())
        from .utils import suggest_workflow_templates
        suggested_workflows = suggest_workflow_templates(active_stage_keys)
        selected_workflow_id = job.workflow.id if job.workflow else None

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
            'selected_workflow_id': selected_workflow_id
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

            plan_res = calculate_assessment_plan(
                temp_comps,
                custom_weights=custom_weights,
                custom_passing_scores=custom_passing_scores
            )
            
            active_stage_keys = list(plan_res['stages'].keys())
            from .utils import suggest_workflow_templates
            suggested_workflows = suggest_workflow_templates(active_stage_keys)
            
            context = {
                'job': job,
                'calculated_plan': plan_res['stages'],
                'errors': plan_res.get('errors', []),
                'suggested_workflows': suggested_workflows,
                'selected_workflow_id': selected_workflow_id
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

            plan_res = calculate_assessment_plan(
                temp_comps,
                custom_weights=custom_weights,
                custom_passing_scores=custom_passing_scores
            )
            stages_data = plan_res['stages']
            
            # Check for validation errors
            if plan_res.get('errors') or not stages_data:
                errors = plan_res.get('errors', [])
                if not stages_data and not errors:
                    errors.append("هیچ شایستگی مناسبی برای سنجش انتخاب نشده است. لطفاً حداقل یک شایستگی با نوع KN، SK، AB، GE یا ST انتخاب کنید.")
                
                # Retrieve matching suggested workflows for the error screen
                from .utils import suggest_workflow_templates
                active_stage_keys = list(stages_data.keys())
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
                    'selected_workflow_id': request.POST.get('workflow_template_id')
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
        posts_query = CentralCompetency.objects.filter(is_deleted=False)
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
