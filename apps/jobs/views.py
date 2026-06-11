from django.shortcuts import render, get_object_or_404
from django.views.generic import ListView, CreateView, UpdateView
from django.views import View
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse

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

    def get_queryset(self):
        from django.db.models import Count, Q
        queryset = JobOpportunity.objects.filter(is_deleted=False)
        queryset = apply_job_filters(queryset, self.request.GET)
        return queryset.annotate(
            candidate_count=Count('applications', filter=Q(applications__is_deleted=False))
        ).prefetch_related('stages').order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
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
        return reverse('job_planning', kwargs={'job_id': self.object.pk}) + '?next=print_doc'

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
        return reverse('job_print_doc', kwargs={'pk': self.object.pk})

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
        context = self.get_context_data()
        stages = context['stages']
        if stages.is_valid():
            self.object = form.save()
            stages.instance = self.object
            stages.save()
            return super().form_valid(form)
        else:
            return self.form_invalid(form)


class JobOpportunityDeleteView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_JOB_CLASSIFICATION_USER,
    ]

    def delete(self, request, pk):
        job = get_object_or_404(JobOpportunity, pk=pk)
        job.delete()  # Soft delete
        return HttpResponse("")


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
