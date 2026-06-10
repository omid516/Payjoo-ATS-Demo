from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView
from django.views import View
from django.urls import reverse_lazy, reverse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, HttpResponseRedirect
from django.db import transaction, models
from django.core.exceptions import PermissionDenied

from apps.accounts.permissions import RoleRequiredMixin
from apps.accounts.models import UserProfile
from .models import (
    Candidate, CandidateEducation, CandidateExperience, JobApplication,
    CandidateLanguage, CandidateSkill, CandidateCertificate
)
from .forms import (
    CandidateForm, CandidateEducationFormSet, CandidateExperienceFormSet, JobApplicationForm,
    CandidateLanguageFormSet, CandidateSkillFormSet, CandidateCertificateFormSet
)

class CandidateListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = Candidate
    template_name = 'candidates/candidate_list.html'
    context_object_name = 'candidates'
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]
    paginate_by = 10

    def extract_keywords(self, text):
        if not text:
            return []
        import re
        # Remove non-word characters
        cleaned = re.sub(r'[^\w\s]', ' ', text)
        words = cleaned.split()
        stop_words = {
            'در', 'و', 'به', 'از', 'با', 'بر', 'تا', 'یا', 'برای', 'کارشناس', 'مدیر', 
            'مسئول', 'دبارتمان', 'بخش', 'سازمان', 'شرکت', 'توسعه', 'توسعه‌دهنده', 
            'ارشد', 'جذب', 'استخدام', 'نفر', 'ها', 'های', 'and', 'the', 'for', 'of', 'in'
        }
        keywords = [w.lower() for w in words if len(w) >= 3 and w.lower() not in stop_words]
        return list(set(keywords))

    def compute_job_match(self, candidate, job_keywords):
        score = 0
        matched_skills = []
        matched_exps = []
        matched_edus = []

        # 1. Skill Match (up to 45 points)
        skill_points = 0
        for skill in candidate.skills.filter(is_deleted=False):
            skill_name_lower = skill.name.lower()
            if any(kw in skill_name_lower for kw in job_keywords):
                matched_skills.append(skill.name)
                skill_points += 15
        score += min(skill_points, 45)

        # 2. Experience Match (up to 40 points)
        exp_points = 0
        for exp in candidate.experience.filter(is_deleted=False):
            exp_title_lower = exp.job_title.lower()
            if any(kw in exp_title_lower for kw in job_keywords):
                matched_exps.append(exp.job_title)
                exp_points += 20
        score += min(exp_points, 40)

        # 3. Education Match (up to 15 points)
        edu_points = 0
        for edu in candidate.education.filter(is_deleted=False):
            edu_major_lower = edu.major.lower()
            if any(kw in edu_major_lower for kw in job_keywords):
                matched_edus.append(edu.major)
                edu_points += 15
        score += min(edu_points, 15)

        reasons = []
        if matched_skills:
            reasons.append(f"مهارت‌ها: {', '.join(matched_skills[:3])}")
        if matched_exps:
            reasons.append(f"سوابق: {', '.join(matched_exps[:2])}")
        if matched_edus:
            reasons.append(f"رشته: {', '.join(matched_edus[:1])}")

        return score, ' | '.join(reasons)

    def get_queryset(self):
        queryset = Candidate.objects.filter(is_deleted=False).prefetch_related(
            'applications__stage_states__stage',
            'skills',
            'experience',
            'education'
        )
        
        # 1. Text Search
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                models.Q(first_name__icontains=search_query) |
                models.Q(last_name__icontains=search_query) |
                models.Q(national_id__icontains=search_query) |
                models.Q(email__icontains=search_query)
            )

        # 2. Education Degree Filter
        degree = self.request.GET.get('degree')
        if degree:
            queryset = queryset.filter(education__degree=degree, education__is_deleted=False).distinct()

        # 3. Major Filter
        major = self.request.GET.get('major')
        if major:
            queryset = queryset.filter(education__major__icontains=major, education__is_deleted=False).distinct()

        # 4. Skill Filter
        skill = self.request.GET.get('skill')
        if skill:
            queryset = queryset.filter(skills__name__icontains=skill, skills__is_deleted=False).distinct()

        # 5. Work Experience Years Filter (Python-side filtering for cross-DB safety)
        min_exp = self.request.GET.get('min_experience')
        if min_exp:
            try:
                min_exp_years = float(min_exp)
                valid_candidate_ids = []
                from datetime import date
                for candidate in queryset.prefetch_related('experience'):
                    total_days = 0
                    for exp in candidate.experience.filter(is_deleted=False):
                        start = exp.start_date
                        end = exp.end_date or date.today()
                        if start:
                            total_days += (end - start).days
                    if (total_days / 365.25) >= min_exp_years:
                        valid_candidate_ids.append(candidate.id)
                queryset = queryset.filter(id__in=valid_candidate_ids)
            except ValueError:
                pass

        # 6. Score Filters
        min_exam = self.request.GET.get('min_exam_score')
        if min_exam:
            try:
                val = float(min_exam)
                exam_kws = ["آزمون", "امتحان", "کتبی", "exam", "test"]
                q_obj = models.Q()
                for kw in exam_kws:
                    q_obj |= models.Q(
                        applications__stage_states__stage__name__icontains=kw,
                        applications__stage_states__score__gte=val,
                        applications__stage_states__is_deleted=False,
                        applications__is_deleted=False
                    )
                queryset = queryset.filter(q_obj).distinct()
            except ValueError:
                pass

        min_interview = self.request.GET.get('min_interview_score')
        if min_interview:
            try:
                val = float(min_interview)
                intv_kws = ["مصاحبه", "interview"]
                q_obj = models.Q()
                for kw in intv_kws:
                    q_obj |= models.Q(
                        applications__stage_states__stage__name__icontains=kw,
                        applications__stage_states__score__gte=val,
                        applications__stage_states__is_deleted=False,
                        applications__is_deleted=False
                    )
                queryset = queryset.filter(q_obj).distinct()
            except ValueError:
                pass

        min_assessment = self.request.GET.get('min_assessment_score')
        if min_assessment:
            try:
                val = float(min_assessment)
                asmt_kws = ["کانون", "ارزیابی", "assessment", "سنتر", "competency"]
                q_obj = models.Q()
                for kw in asmt_kws:
                    q_obj |= models.Q(
                        applications__stage_states__stage__name__icontains=kw,
                        applications__stage_states__score__gte=val,
                        applications__stage_states__is_deleted=False,
                        applications__is_deleted=False
                    )
                queryset = queryset.filter(q_obj).distinct()
            except ValueError:
                pass

        # 7. Applied Job Opportunity Filter
        applied_job_id = self.request.GET.get('applied_job')
        if applied_job_id:
            queryset = queryset.filter(
                applications__job_id=applied_job_id,
                applications__is_deleted=False
            ).distinct()

        # 8. Similarity Match / Suitability Recommendation for a target Job
        similar_to_job_id = self.request.GET.get('similar_to_job')
        if similar_to_job_id:
            similar_job = JobOpportunity.objects.filter(id=similar_to_job_id, is_deleted=False).first()
            if similar_job:
                # Calculate match scores and filter
                job_keywords = self.extract_keywords(similar_job.title) + self.extract_keywords(similar_job.department)
                candidates_list = list(queryset)
                filtered_candidates = []
                for candidate in candidates_list:
                    match_score, matched_reasons = self.compute_job_match(candidate, job_keywords)
                    if match_score > 0:
                        candidate.match_score = match_score
                        candidate.match_reasons = matched_reasons
                        filtered_candidates.append(candidate)
                # Sort by match score descending
                filtered_candidates.sort(key=lambda c: c.match_score, reverse=True)
                return filtered_candidates

        return queryset

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        from datetime import date
        
        # Calculate dashboard analytics
        all_candidates = Candidate.objects.filter(is_deleted=False)
        total_candidates = all_candidates.count()
        data['total_candidates'] = total_candidates
        
        # Higher Education % (Master / PhD)
        higher_edu_count = all_candidates.filter(
            education__degree__in=['MASTER', 'PHD'],
            education__is_deleted=False
        ).distinct().count()
        data['higher_edu_percentage'] = round((higher_edu_count / total_candidates) * 100, 1) if total_candidates > 0 else 0.0
        
        # Average Experience Years
        total_exp_days = 0
        candidates_with_exp = all_candidates.prefetch_related('experience')
        for candidate in candidates_with_exp:
            for exp in candidate.experience.filter(is_deleted=False):
                start = exp.start_date
                end = exp.end_date or date.today()
                if start:
                    total_exp_days += (end - start).days
        data['average_experience_years'] = round((total_exp_days / 365.25) / total_candidates, 1) if total_candidates > 0 else 0.0

        # Pass active job opportunities for assignment dropdown (fixed query)
        data['active_jobs'] = JobOpportunity.objects.filter(is_deleted=False).exclude(status__in=['CLOSED', 'CANCELLED']).order_by('-created_at')
        
        # Pass all jobs for search/filters
        data['all_jobs'] = JobOpportunity.objects.filter(is_deleted=False).order_by('-created_at')

        # Preserve active filters in context
        data['selected_degree'] = self.request.GET.get('degree', '')
        data['selected_major'] = self.request.GET.get('major', '')
        data['selected_skill'] = self.request.GET.get('skill', '')
        data['selected_min_experience'] = self.request.GET.get('min_experience', '')
        data['selected_min_exam_score'] = self.request.GET.get('min_exam_score', '')
        data['selected_min_interview_score'] = self.request.GET.get('min_interview_score', '')
        data['selected_min_assessment_score'] = self.request.GET.get('min_assessment_score', '')
        data['selected_applied_job'] = self.request.GET.get('applied_job', '')
        data['selected_similar_to_job'] = self.request.GET.get('similar_to_job', '')
        
        return data


class AssignCandidateToJobView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def post(self, request, candidate_id):
        candidate = get_object_or_404(Candidate, pk=candidate_id, is_deleted=False)
        job_id = request.POST.get('job_id')
        if not job_id:
            return HttpResponse("شناسه فرصت شغلی الزامی است.", status=400)
            
        job = get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)
        
        # Check if already exists
        exists = JobApplication.objects.filter(job=job, candidate=candidate, is_deleted=False).exists()
        if exists:
            return HttpResponse("این متقاضی قبلاً برای این فرصت شغلی ثبت‌نام شده است.", status=400)
            
        with transaction.atomic():
            JobApplication.objects.create(job=job, candidate=candidate)
            
        view_param = request.GET.get('view')
        redirect_url = reverse('candidate_list')
        if view_param:
            redirect_url += f'?view={view_param}'

        if request.headers.get('HX-Request'):
            response = HttpResponse("موفقیت‌آمیز")
            response['HX-Redirect'] = redirect_url
            return response
            
        return redirect(redirect_url)


class CandidateDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = Candidate
    template_name = 'candidates/candidate_detail.html'
    context_object_name = 'candidate'
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        # دریافت سوابق تحصیلی و کاری فعال
        data['education_list'] = self.object.education.filter(is_deleted=False)
        data['experience_list'] = self.object.experience.filter(is_deleted=False)
        data['language_list'] = self.object.languages.filter(is_deleted=False)
        data['skill_list'] = self.object.skills.filter(is_deleted=False)
        data['certificate_list'] = self.object.certificates.filter(is_deleted=False)
        # دریافت لیست درخواست‌ها به همراه مراحلشان
        data['applications'] = self.object.applications.filter(is_deleted=False).select_related('job', 'current_stage')
        return data


class CandidateCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = Candidate
    form_class = CandidateForm
    template_name = 'candidates/candidate_form.html'
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get_success_url(self):
        view_param = self.request.GET.get('view')
        if view_param:
            return reverse('candidate_list') + f'?view={view_param}'
        return reverse('candidate_list')

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        if self.request.POST:
            data['education_formset'] = CandidateEducationFormSet(self.request.POST)
            data['experience_formset'] = CandidateExperienceFormSet(self.request.POST)
        else:
            data['education_formset'] = CandidateEducationFormSet()
            data['experience_formset'] = CandidateExperienceFormSet()
        return data

    def form_valid(self, form):
        context = self.get_context_data()
        education_formset = context['education_formset']
        experience_formset = context['experience_formset']
        
        if education_formset.is_valid() and experience_formset.is_valid():
            with transaction.atomic():
                self.object = form.save()
                
                education_formset.instance = self.object
                education_formset.save()
                
                experience_formset.instance = self.object
                experience_formset.save()
                
            return redirect(self.get_success_url())
        else:
            return self.render_to_response(self.get_context_data(form=form))


class CandidateUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = Candidate
    form_class = CandidateForm
    template_name = 'candidates/candidate_form.html'
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        if self.request.POST:
            data['education_formset'] = CandidateEducationFormSet(self.request.POST, instance=self.object)
            data['experience_formset'] = CandidateExperienceFormSet(self.request.POST, instance=self.object)
        else:
            data['education_formset'] = CandidateEducationFormSet(
                instance=self.object,
                queryset=CandidateEducation.objects.filter(is_deleted=False).order_by('-graduation_year')
            )
            data['experience_formset'] = CandidateExperienceFormSet(
                instance=self.object,
                queryset=CandidateExperience.objects.filter(is_deleted=False).order_by('-start_date')
            )
        return data

    def form_valid(self, form):
        context = self.get_context_data()
        education_formset = context['education_formset']
        experience_formset = context['experience_formset']
        
        if education_formset.is_valid() and experience_formset.is_valid():
            with transaction.atomic():
                self.object = form.save()
                
                education_formset.instance = self.object
                education_formset.save()
                
                experience_formset.instance = self.object
                experience_formset.save()
                
            return redirect(self.get_success_url())
        else:
            return self.render_to_response(self.get_context_data(form=form))

    def get_success_url(self):
        return reverse('candidate_detail', kwargs={'pk': self.object.pk})


class CandidateDeleteView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def delete(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk)
        
        with transaction.atomic():
            # حذف نرم متقاضی
            candidate.delete()
            # حذف نرم درخواست‌ها و سوابق وی
            candidate.education.all().delete()
            candidate.experience.all().delete()
            candidate.applications.all().delete()
            candidate.languages.all().delete()
            candidate.skills.all().delete()
            candidate.certificates.all().delete()
            
        return HttpResponse("")


class JobApplicationCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = JobApplication
    form_class = JobApplicationForm
    template_name = 'candidates/application_form.html'
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data['candidate'] = get_object_or_404(Candidate, pk=self.kwargs.get('candidate_id'))
        return data

    def form_valid(self, form):
        candidate = get_object_or_404(Candidate, pk=self.kwargs.get('candidate_id'))
        form.instance.candidate = candidate
        
        # جلوگیری از درخواست تکراری برای یک شغل
        if JobApplication.objects.filter(job=form.instance.job, candidate=candidate, is_deleted=False).exists():
            form.add_error('job', 'این متقاضی قبلاً برای این فرصت شغلی ثبت‌نام شده است.')
            return self.form_invalid(form)
            
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('candidate_detail', kwargs={'pk': self.kwargs.get('candidate_id')})


from apps.jobs.models import JobOpportunity, JobOpportunityStage
from .models import ApplicationStageState

class JobOpportunityPipelineView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = JobOpportunity
    template_name = 'jobs/job_pipeline.html'
    context_object_name = 'job'
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data['stages'] = self.object.stages.filter(is_deleted=False).prefetch_related('interviewers__user').order_by('sequence')
        data['applications'] = self.object.applications.filter(is_deleted=False).select_related('candidate').prefetch_related('stage_states__stage')
        data['status_choices'] = JobApplication.STATUS_CHOICES
        return data


class EditApplicationStageStateView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request, pk):
        state = get_object_or_404(ApplicationStageState, pk=pk)
        if not state.is_accessible:
            return HttpResponse("این مرحله هنوز برای متقاضی فعال نشده است و مراحل قبلی باید تکمیل شوند.", status=400)
        return render(request, 'candidates/partials/stage_state_edit.html', {'state': state})


class UpdateApplicationStageStateView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def post(self, request, pk):
        state = get_object_or_404(ApplicationStageState, pk=pk)
        if not state.is_accessible:
            return HttpResponse("این مرحله هنوز برای متقاضی فعال نشده است و مراحل قبلی باید تکمیل شوند.", status=400)
        
        score_val = request.POST.get('score', '0')
        status_val = request.POST.get('status', ApplicationStageState.STATUS_PENDING)
        notes_val = request.POST.get('notes', '')
        is_conditional_pass_val = request.POST.get('is_conditional_pass') == 'true' or request.POST.get('is_conditional_pass') == 'on'

        try:
            state.score = float(score_val)
        except ValueError:
            state.score = 0.0

        state.status = status_val
        state.notes = notes_val
        state.is_conditional_pass = is_conditional_pass_val
        state.evaluator = request.user
        state.save()

        source = request.POST.get('source')
        if source == 'score_entry':
            # Get the new active stage state for the application if it advanced
            app = state.application
            new_active_state = ApplicationStageState.objects.filter(
                application=app,
                stage=app.current_stage,
                is_deleted=False
            ).first()
            return render(request, 'candidates/partials/score_entry_row.html', {
                'state': new_active_state or state,
                'just_saved': True,
                'saved_stage_name': state.stage.name,
                'saved_status': state.get_status_display(),
                'saved_score': state.score,
            })

        # Render read-only view cell along with out-of-band update for final score
        return render(request, 'candidates/partials/stage_state_view.html', {
            'state': state,
            'application': state.application,
            'oob_update': True
        })


class ViewApplicationStageStateView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request, pk):
        state = get_object_or_404(ApplicationStageState, pk=pk)
        return render(request, 'candidates/partials/stage_state_view.html', {'state': state})


class UpdateApplicationStatusView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def post(self, request, pk):
        application = get_object_or_404(JobApplication, pk=pk)
        status_val = request.POST.get('status')
        if status_val in dict(JobApplication.STATUS_CHOICES):
            application.status = status_val
            application.save(update_fields=['status'])
            application.job.update_status()
            
        badge_class = 'bg-warning text-warning'
        border_class = 'border-warning'
        if application.status == JobApplication.STATUS_SELECTED:
            badge_class = 'bg-success text-success'
            border_class = 'border-success'
        elif application.status == JobApplication.STATUS_RESERVE:
            badge_class = 'bg-info text-info'
            border_class = 'border-info'
        elif application.status == JobApplication.STATUS_REJECTED:
            badge_class = 'bg-danger text-danger'
            border_class = 'border-danger'

        html = f'<span class="badge {badge_class} bg-opacity-10 border {border_class} border-opacity-25 px-2 py-1.5 rounded text-xs">{application.get_status_display()}</span>'
        return HttpResponse(html)


class CareersListView(ListView):
    model = JobOpportunity
    template_name = 'candidates/public_job_list.html'
    context_object_name = 'jobs'

    def get_queryset(self):
        from datetime import date
        from django.db.models import Q
        return JobOpportunity.objects.filter(
            status=JobOpportunity.STATUS_PUBLISHED,
            is_deleted=False
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=date.today())
        ).prefetch_related('stages')

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        # Group by department
        jobs = self.get_queryset()
        grouped_jobs = {}
        for job in jobs:
            dept = job.department or 'سایر دپارتمان‌ها'
            if dept not in grouped_jobs:
                grouped_jobs[dept] = []
            grouped_jobs[dept].append(job)
        data['grouped_jobs'] = grouped_jobs
        return data


class CareersDetailAndApplyView(View):
    def get(self, request, pk):
        from datetime import date
        job = get_object_or_404(JobOpportunity, pk=pk, status=JobOpportunity.STATUS_PUBLISHED, is_deleted=False)
        if job.end_date and job.end_date < date.today():
            return render(request, 'candidates/public_job_detail.html', {
                'job': job,
                'registration_closed': True,
            })
        form = CandidateForm()
        has_applied = False
        candidate = None
        if request.user.is_authenticated and hasattr(request.user, 'profile') and request.user.profile.role == UserProfile.ROLE_CANDIDATE:
            candidate = getattr(request.user, 'candidate_profile', None)
            if candidate:
                has_applied = JobApplication.objects.filter(job=job, candidate=candidate, is_deleted=False).exists()
        return render(request, 'candidates/public_job_detail.html', {
            'job': job,
            'form': form,
            'has_applied': has_applied,
            'candidate': candidate,
        })

    def post(self, request, pk):
        from datetime import date
        job = get_object_or_404(JobOpportunity, pk=pk, status=JobOpportunity.STATUS_PUBLISHED, is_deleted=False)
        if job.end_date and job.end_date < date.today():
            return render(request, 'candidates/public_job_detail.html', {
                'job': job,
                'registration_closed': True,
            })
        
        national_id = request.POST.get('national_id', '').strip()

        candidate = None
        if national_id:
            candidate = Candidate.objects.filter(national_id=national_id, is_deleted=False).first()

        if candidate:
            form = CandidateForm(request.POST, request.FILES, instance=candidate)
        else:
            form = CandidateForm(request.POST, request.FILES)

        if form.is_valid():
            with transaction.atomic():
                candidate = form.save()

                # Check if this candidate already applied for this job
                existing_app = JobApplication.all_objects.filter(job=job, candidate=candidate).first()
                if existing_app:
                    if not existing_app.is_deleted:
                        form.add_error(None, 'شما قبلاً برای این فرصت شغلی ثبت‌نام کرده‌اید.')
                        return render(request, 'candidates/public_job_detail.html', {
                            'job': job,
                            'form': form
                        })
                    else:
                        # Restore soft-deleted application
                        existing_app.is_deleted = False
                        existing_app.deleted_at = None
                        existing_app.status = JobApplication.STATUS_IN_PROGRESS
                        existing_app.save()
                else:
                    # Create JobApplication
                    JobApplication.objects.create(
                        job=job,
                        candidate=candidate,
                        status=JobApplication.STATUS_IN_PROGRESS
                    )
            
            return redirect('careers_success')
        else:
            return render(request, 'candidates/public_job_detail.html', {
                'job': job,
                'form': form
            })


class CareersTrackView(View):
    def get(self, request):
        return render(request, 'candidates/public_track.html')

    def post(self, request):
        national_id = request.POST.get('national_id', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()

        candidate = Candidate.objects.filter(
            national_id=national_id,
            phone_number=phone_number,
            is_deleted=False
        ).prefetch_related('applications__job', 'applications__current_stage').first()

        if not candidate:
            return render(request, 'candidates/public_track.html', {
                'error': 'متقاضی با مشخصات فوق در سیستم یافت نشد. لطفاً اطلاعات وارد شده را مجدداً بررسی نمایید.',
                'national_id': national_id,
                'phone_number': phone_number
            })

        applications = candidate.applications.filter(is_deleted=False)
        return render(request, 'candidates/public_track.html', {
            'candidate': candidate,
            'applications': applications,
            'national_id': national_id,
            'phone_number': phone_number
        })


class CareersSuccessView(TemplateView):
    template_name = 'candidates/public_success.html'


from django.contrib.auth import login
from django.contrib.auth.models import User
from .forms import CandidateSignUpForm

class CandidateSignUpView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('candidate_dashboard')
        form = CandidateSignUpForm()
        education_formset = CandidateEducationFormSet(prefix='edu')
        experience_formset = CandidateExperienceFormSet(prefix='exp')
        language_formset = CandidateLanguageFormSet(prefix='lang')
        skill_formset = CandidateSkillFormSet(prefix='skill')
        certificate_formset = CandidateCertificateFormSet(prefix='cert')
        
        return render(request, 'candidates/signup.html', {
            'form': form,
            'education_formset': education_formset,
            'experience_formset': experience_formset,
            'language_formset': language_formset,
            'skill_formset': skill_formset,
            'certificate_formset': certificate_formset,
        })

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('candidate_dashboard')
        form = CandidateSignUpForm(request.POST, request.FILES)
        education_formset = CandidateEducationFormSet(request.POST, prefix='edu')
        experience_formset = CandidateExperienceFormSet(request.POST, prefix='exp')
        language_formset = CandidateLanguageFormSet(request.POST, prefix='lang')
        skill_formset = CandidateSkillFormSet(request.POST, prefix='skill')
        certificate_formset = CandidateCertificateFormSet(request.POST, prefix='cert')

        if (form.is_valid() and education_formset.is_valid() and 
            experience_formset.is_valid() and language_formset.is_valid() and 
            skill_formset.is_valid() and certificate_formset.is_valid()):
            
            with transaction.atomic():
                first_name = form.cleaned_data['first_name']
                last_name = form.cleaned_data['last_name']
                email = form.cleaned_data['email']
                phone_number = form.cleaned_data['phone_number']
                national_id = form.cleaned_data['national_id']
                personnel_number = form.cleaned_data['personnel_number']
                password = form.cleaned_data['password']

                # Create Django User
                user = User.objects.create_user(
                    username=national_id,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name
                )
                
                # Update UserProfile role to CANDIDATE
                profile = user.profile
                profile.role = UserProfile.ROLE_CANDIDATE
                profile.phone_number = phone_number
                profile.save()

                # Link or create Candidate record
                candidate = Candidate.all_objects.filter(national_id=national_id).first()
                if candidate:
                    candidate.is_deleted = False
                    candidate.deleted_at = None
                    candidate.user = user
                    candidate.first_name = first_name
                    candidate.last_name = last_name
                    candidate.email = email
                    candidate.phone_number = phone_number
                    candidate.personnel_number = personnel_number or None
                    if 'resume' in request.FILES:
                        candidate.resume = request.FILES['resume']
                    candidate.save()
                else:
                    candidate = Candidate.objects.create(
                        user=user,
                        first_name=first_name,
                        last_name=last_name,
                        email=email,
                        phone_number=phone_number,
                        national_id=national_id,
                        personnel_number=personnel_number or None,
                        resume=request.FILES.get('resume')
                    )

                # Save formsets linked to candidate
                education_formset.instance = candidate
                education_formset.save()
                
                experience_formset.instance = candidate
                experience_formset.save()
                
                language_formset.instance = candidate
                language_formset.save()
                
                skill_formset.instance = candidate
                skill_formset.save()
                
                certificate_formset.instance = candidate
                certificate_formset.save()
            
            # Log the user in
            login(request, user)
            return redirect('candidate_dashboard')
        
        return render(request, 'candidates/signup.html', {
            'form': form,
            'education_formset': education_formset,
            'experience_formset': experience_formset,
            'language_formset': language_formset,
            'skill_formset': skill_formset,
            'certificate_formset': certificate_formset,
        })


class CandidateDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'candidates/dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not hasattr(request.user, 'profile') or request.user.profile.role != UserProfile.ROLE_CANDIDATE:
            return redirect('dashboard')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        # Find or create linked Candidate profile
        candidate, created = Candidate.objects.get_or_create(
            user=self.request.user,
            defaults={
                'first_name': self.request.user.first_name,
                'last_name': self.request.user.last_name,
                'email': self.request.user.email,
                'phone_number': self.request.user.profile.phone_number,
                'national_id': self.request.user.username,
            }
        )
        data['candidate'] = candidate
        
        # Load published jobs grouped by department
        jobs = JobOpportunity.objects.filter(
            status=JobOpportunity.STATUS_PUBLISHED,
            is_deleted=False
        ).prefetch_related('stages')
        
        grouped_jobs = {}
        for job in jobs:
            dept = job.department or 'سایر دپارتمان‌ها'
            if dept not in grouped_jobs:
                grouped_jobs[dept] = []
            grouped_jobs[dept].append(job)
        data['grouped_jobs'] = grouped_jobs
        
        # Candidate's applications
        data['applications'] = candidate.applications.filter(is_deleted=False).select_related('job', 'current_stage').prefetch_related('stage_states__stage')
        
        # Already applied job ids
        data['applied_job_ids'] = list(candidate.applications.filter(is_deleted=False).values_list('job_id', flat=True))
        
        # Profile & CV forms
        data['profile_form'] = CandidateForm(instance=candidate)
        data['education_formset'] = CandidateEducationFormSet(instance=candidate, prefix='edu')
        data['experience_formset'] = CandidateExperienceFormSet(instance=candidate, prefix='exp')
        data['language_formset'] = CandidateLanguageFormSet(instance=candidate, prefix='lang')
        data['skill_formset'] = CandidateSkillFormSet(instance=candidate, prefix='skill')
        data['certificate_formset'] = CandidateCertificateFormSet(instance=candidate, prefix='cert')
        
        return data


class CandidateProfileUpdateView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not hasattr(request.user, 'profile') or request.user.profile.role != UserProfile.ROLE_CANDIDATE:
            return HttpResponse(status=403)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        candidate = get_object_or_404(Candidate, user=request.user, is_deleted=False)
        form = CandidateForm(request.POST, request.FILES, instance=candidate)
        if form.is_valid():
            form.save()
            return redirect('candidate_dashboard')
        
        dashboard_view = CandidateDashboardView()
        dashboard_view.request = request
        context = dashboard_view.get_context_data()
        context['profile_form'] = form
        context['active_tab'] = 'profile'
        return render(request, 'candidates/dashboard.html', context)


class CandidateEducationUpdateView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not hasattr(request.user, 'profile') or request.user.profile.role != UserProfile.ROLE_CANDIDATE:
            return HttpResponse(status=403)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        candidate = get_object_or_404(Candidate, user=request.user, is_deleted=False)
        formset = CandidateEducationFormSet(request.POST, instance=candidate, prefix='edu')
        if formset.is_valid():
            formset.save()
            return redirect('candidate_dashboard')
        
        dashboard_view = CandidateDashboardView()
        dashboard_view.request = request
        context = dashboard_view.get_context_data()
        context['education_formset'] = formset
        context['active_tab'] = 'profile'
        return render(request, 'candidates/dashboard.html', context)


class CandidateExperienceUpdateView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not hasattr(request.user, 'profile') or request.user.profile.role != UserProfile.ROLE_CANDIDATE:
            return HttpResponse(status=403)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        candidate = get_object_or_404(Candidate, user=request.user, is_deleted=False)
        formset = CandidateExperienceFormSet(request.POST, instance=candidate, prefix='exp')
        if formset.is_valid():
            formset.save()
            return redirect('candidate_dashboard')
        
        dashboard_view = CandidateDashboardView()
        dashboard_view.request = request
        context = dashboard_view.get_context_data()
        context['experience_formset'] = formset
        context['active_tab'] = 'profile'
        return render(request, 'candidates/dashboard.html', context)


class CandidateApplyDirectView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not hasattr(request.user, 'profile') or request.user.profile.role != UserProfile.ROLE_CANDIDATE:
            return HttpResponse(status=403)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, pk):
        from datetime import date
        job = get_object_or_404(JobOpportunity, pk=pk, status=JobOpportunity.STATUS_PUBLISHED, is_deleted=False)
        if job.end_date and job.end_date < date.today():
            return HttpResponse("مهلت ثبت‌نام در این فرصت شغلی به پایان رسیده است.", status=400)
            
        candidate = get_object_or_404(Candidate, user=request.user, is_deleted=False)
        
        # Check if already applied
        existing_app = JobApplication.all_objects.filter(job=job, candidate=candidate).first()
        if existing_app:
            if existing_app.is_deleted:
                existing_app.is_deleted = False
                existing_app.deleted_at = None
                existing_app.status = JobApplication.STATUS_IN_PROGRESS
                existing_app.save()
        else:
            JobApplication.objects.create(
                job=job,
                candidate=candidate,
                status=JobApplication.STATUS_IN_PROGRESS
            )
            
        return redirect('candidate_dashboard')


class CandidateLanguageUpdateView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not hasattr(request.user, 'profile') or request.user.profile.role != UserProfile.ROLE_CANDIDATE:
            return HttpResponse(status=403)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        candidate = get_object_or_404(Candidate, user=request.user, is_deleted=False)
        formset = CandidateLanguageFormSet(request.POST, instance=candidate, prefix='lang')
        if formset.is_valid():
            formset.save()
            return redirect('candidate_dashboard')
        
        dashboard_view = CandidateDashboardView()
        dashboard_view.request = request
        context = dashboard_view.get_context_data()
        context['language_formset'] = formset
        context['active_tab'] = 'profile'
        return render(request, 'candidates/dashboard.html', context)


class CandidateSkillUpdateView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not hasattr(request.user, 'profile') or request.user.profile.role != UserProfile.ROLE_CANDIDATE:
            return HttpResponse(status=403)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        candidate = get_object_or_404(Candidate, user=request.user, is_deleted=False)
        formset = CandidateSkillFormSet(request.POST, instance=candidate, prefix='skill')
        if formset.is_valid():
            formset.save()
            return redirect('candidate_dashboard')
        
        dashboard_view = CandidateDashboardView()
        dashboard_view.request = request
        context = dashboard_view.get_context_data()
        context['skill_formset'] = formset
        context['active_tab'] = 'profile'
        return render(request, 'candidates/dashboard.html', context)


class CandidateCertificateUpdateView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not hasattr(request.user, 'profile') or request.user.profile.role != UserProfile.ROLE_CANDIDATE:
            return HttpResponse(status=403)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request):
        candidate = get_object_or_404(Candidate, user=request.user, is_deleted=False)
        formset = CandidateCertificateFormSet(request.POST, instance=candidate, prefix='cert')
        if formset.is_valid():
            formset.save()
            return redirect('candidate_dashboard')
        
        dashboard_view = CandidateDashboardView()
        dashboard_view.request = request
        context = dashboard_view.get_context_data()
        context['certificate_formset'] = formset
        context['active_tab'] = 'profile'
        return render(request, 'candidates/dashboard.html', context)
def parse_jalali_date(val):
    if not val:
        return None
    try:
        import jdatetime
        parts = [int(p) for p in val.strip().split('/')]
        if len(parts) == 3:
            return jdatetime.date(parts[0], parts[1], parts[2]).togregorian()
    except Exception:
        pass
    return None


class ScoreEntryListView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_SPECIALIST, UserProfile.ROLE_RECRUITMENT_DIRECTOR]

    def get(self, request):
        from django.core.paginator import Paginator
        from django.db.models import Q as DQ
        job_q = request.GET.get('job_q', '').strip()
        jobs_qs = JobOpportunity.objects.filter(is_deleted=False).exclude(status=JobOpportunity.STATUS_CLOSED)
        if job_q:
            jobs_qs = jobs_qs.filter(
                DQ(title__icontains=job_q) |
                DQ(code__icontains=job_q) |
                DQ(request_number__icontains=job_q)
            )
        jobs = jobs_qs.order_by('code')
        job_id = request.GET.get('job_id')
        stage_id = request.GET.get('stage_id')
        q = request.GET.get('q')
        eval_status = request.GET.get('eval_status', 'PENDING')
        show_failed_prior_val = request.GET.get('show_failed_prior')
        show_failed_prior = show_failed_prior_val in ['true', 'on', '1']

        
        selected_job = None
        selected_stage = None
        stages = []
        pending_states = []
        page_obj = None
        paginator = None
        is_paginated = False

        if job_id:
            selected_job = get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)
            stages = selected_job.stages.filter(is_deleted=False).order_by('sequence')
            
            if request.headers.get('HX-Request') and 'job_id' in request.GET and 'stage_id' not in request.GET:
                return render(request, 'candidates/partials/score_entry_stages_select.html', {
                    'stages': stages,
                })

            if stage_id:
                from django.db.models import Exists, OuterRef
                selected_stage = get_object_or_404(JobOpportunityStage, pk=stage_id, is_deleted=False)
                pending_states_qs = ApplicationStageState.objects.filter(
                    application__job=selected_job,
                    application__status=JobApplication.STATUS_IN_PROGRESS,
                    application__is_deleted=False,
                    stage=selected_stage,
                    is_deleted=False
                ).select_related('application__candidate', 'application__job', 'stage', 'evaluator')
                
                # Annotate if there is a failed prior stage state
                prior_failed_subquery = ApplicationStageState.objects.filter(
                    application=OuterRef('application'),
                    stage__sequence__lt=OuterRef('stage__sequence'),
                    status=ApplicationStageState.STATUS_FAILED,
                    is_conditional_pass=False,
                    is_deleted=False
                )
                pending_states_qs = pending_states_qs.annotate(
                    has_failed_prior=Exists(prior_failed_subquery)
                )
                
                # Filter out prior failed stages unless specifically requested
                if not show_failed_prior:
                    pending_states_qs = pending_states_qs.filter(has_failed_prior=False)
                
                # Apply eval_status filter
                if eval_status == 'PENDING':
                    pending_states_qs = pending_states_qs.filter(status=ApplicationStageState.STATUS_PENDING)
                elif eval_status == 'COMPLETED_FAILED':
                    pending_states_qs = pending_states_qs.filter(status__in=[ApplicationStageState.STATUS_COMPLETED, ApplicationStageState.STATUS_FAILED])
                
                # Apply name/id search
                if q:
                    pending_states_qs = pending_states_qs.filter(
                        models.Q(application__candidate__first_name__icontains=q) |
                        models.Q(application__candidate__last_name__icontains=q) |
                        models.Q(application__candidate__national_id__icontains=q)
                    )
                    
                ordered_states = pending_states_qs.order_by('application__candidate__last_name')
                paginator = Paginator(ordered_states, 10)
                page_number = request.GET.get('page')
                page_obj = paginator.get_page(page_number)
                pending_states = page_obj
                is_paginated = page_obj.has_other_pages()

        if request.headers.get('HX-Request'):
            return render(request, 'candidates/partials/score_entry_list.html', {
                'selected_job': selected_job,
                'selected_stage': selected_stage,
                'stages': stages,
                'pending_states': pending_states,
                'selected_q': q,
                'selected_eval_status': eval_status,
                'show_failed_prior': show_failed_prior,
                'page_obj': page_obj,
                'is_paginated': is_paginated,
                'paginator': paginator,
            })

        return render(request, 'candidates/score_entry.html', {
            'jobs': jobs,
            'job_q': job_q,
            'selected_job': selected_job,
            'selected_stage': selected_stage,
            'stages': stages,
            'pending_states': pending_states,
            'selected_q': q,
            'selected_eval_status': eval_status,
            'show_failed_prior': show_failed_prior,
            'page_obj': page_obj,
            'is_paginated': is_paginated,
            'paginator': paginator,
        })

    def post(self, request):
        from django.core.paginator import Paginator
        jobs = JobOpportunity.objects.filter(is_deleted=False).exclude(status=JobOpportunity.STATUS_CLOSED).order_by('-created_at')
        job_id = request.POST.get('job_id')
        stage_id = request.POST.get('stage_id')
        q = request.POST.get('q')
        eval_status = request.POST.get('eval_status', 'PENDING')
        show_failed_prior_val = request.POST.get('show_failed_prior') or request.GET.get('show_failed_prior')
        show_failed_prior = show_failed_prior_val in ['true', 'on', '1']
        
        selected_job = None
        selected_stage = None
        stages = []
        pending_states = []
        page_obj = None
        paginator = None
        is_paginated = False

        if job_id:
            selected_job = get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)
            stages = selected_job.stages.filter(is_deleted=False).order_by('sequence')
            if stage_id:
                selected_stage = get_object_or_404(JobOpportunityStage, pk=stage_id, is_deleted=False)

            state_ids = []
            for key in request.POST.keys():
                if key.startswith('score_'):
                    try:
                        state_ids.append(int(key.split('_')[1]))
                    except ValueError:
                        pass

            with transaction.atomic():
                for sid in state_ids:
                    state = ApplicationStageState.objects.filter(pk=sid, is_deleted=False).first()
                    if state and state.is_accessible:
                        score_val = request.POST.get(f'score_{sid}', '0')
                        status_val = request.POST.get(f'status_{sid}', ApplicationStageState.STATUS_PENDING)
                        notes_val = request.POST.get(f'notes_{sid}', '')
                        date_val = request.POST.get(f'date_{sid}', '').strip()
                        is_conditional_pass_val = request.POST.get(f'is_conditional_pass_{sid}') in ['true', 'on']
                        
                        try:
                            state.score = float(score_val)
                        except ValueError:
                            state.score = 0.0
                            
                        state.status = status_val
                        state.notes = notes_val
                        state.is_conditional_pass = is_conditional_pass_val
                        state.evaluator = request.user
                        
                        if date_val:
                            state.evaluation_date = parse_jalali_date(date_val)
                        else:
                            state.evaluation_date = None
                            
                        state.save()

            if selected_stage:
                from django.db.models import Exists, OuterRef
                pending_states_qs = ApplicationStageState.objects.filter(
                    application__job=selected_job,
                    application__status=JobApplication.STATUS_IN_PROGRESS,
                    application__is_deleted=False,
                    stage=selected_stage,
                    is_deleted=False
                ).select_related('application__candidate', 'application__job', 'stage', 'evaluator')

                # Annotate if there is a failed prior stage state
                prior_failed_subquery = ApplicationStageState.objects.filter(
                    application=OuterRef('application'),
                    stage__sequence__lt=OuterRef('stage__sequence'),
                    status=ApplicationStageState.STATUS_FAILED,
                    is_conditional_pass=False,
                    is_deleted=False
                )
                pending_states_qs = pending_states_qs.annotate(
                    has_failed_prior=Exists(prior_failed_subquery)
                )

                # Filter out prior failed stages unless specifically requested
                if not show_failed_prior:
                    pending_states_qs = pending_states_qs.filter(has_failed_prior=False)

                # Apply eval_status filter
                if eval_status == 'PENDING':
                    pending_states_qs = pending_states_qs.filter(status=ApplicationStageState.STATUS_PENDING)
                elif eval_status == 'COMPLETED_FAILED':
                    pending_states_qs = pending_states_qs.filter(status__in=[ApplicationStageState.STATUS_COMPLETED, ApplicationStageState.STATUS_FAILED])
                
                # Apply name/id search
                if q:
                    pending_states_qs = pending_states_qs.filter(
                        models.Q(application__candidate__first_name__icontains=q) |
                        models.Q(application__candidate__last_name__icontains=q) |
                        models.Q(application__candidate__national_id__icontains=q)
                    )

                ordered_states = pending_states_qs.order_by('application__candidate__last_name')
                paginator = Paginator(ordered_states, 10)
                page_number = request.GET.get('page') or request.POST.get('page')
                page_obj = paginator.get_page(page_number)
                pending_states = page_obj
                is_paginated = page_obj.has_other_pages()

        if request.headers.get('HX-Request'):
            return render(request, 'candidates/partials/score_entry_list.html', {
                'selected_job': selected_job,
                'selected_stage': selected_stage,
                'stages': stages,
                'pending_states': pending_states,
                'bulk_success': True,
                'selected_q': q,
                'selected_eval_status': eval_status,
                'show_failed_prior': show_failed_prior,
                'page_obj': page_obj,
                'is_paginated': is_paginated,
                'paginator': paginator,
            })

        return render(request, 'candidates/score_entry.html', {
            'jobs': jobs,
            'selected_job': selected_job,
            'selected_stage': selected_stage,
            'stages': stages,
            'pending_states': pending_states,
            'bulk_success': True,
            'selected_q': q,
            'selected_eval_status': eval_status,
            'show_failed_prior': show_failed_prior,
            'page_obj': page_obj,
            'is_paginated': is_paginated,
            'paginator': paginator,
        })


class ImportScoreEntryExcelView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_SPECIALIST, UserProfile.ROLE_RECRUITMENT_DIRECTOR]

    def post(self, request):
        import openpyxl
        from django.contrib import messages
        from django.shortcuts import get_object_or_404, redirect
        from django.db import transaction
        from apps.jobs.models import JobOpportunity, JobOpportunityStage
        from apps.candidates.models import ApplicationStageState

        job_id = request.POST.get('job_id')
        stage_id = request.POST.get('stage_id')
        excel_file = request.FILES.get('excel_file')

        if not job_id or not stage_id or not excel_file:
            messages.error(request, "اطلاعات فرصت شغلی، مرحله یا فایل ارسالی نامعتبر است.")
            return redirect('candidate_score_entry')

        job = get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)
        stage = get_object_or_404(JobOpportunityStage, pk=stage_id, is_deleted=False)

        try:
            wb = openpyxl.load_workbook(excel_file)
            ws = wb.active
        except Exception as e:
            messages.error(request, f"خطا در خواندن فایل اکسل: {str(e)}")
            return redirect(f"{reverse('candidate_score_entry')}?job_id={job.id}&stage_id={stage.id}")

        rows = list(ws.iter_rows(values_only=True))
        if not rows or len(rows) < 2:
            messages.error(request, "فایل اکسل خالی است یا فاقد داده‌های معتبر می‌باشد.")
            return redirect(f"{reverse('candidate_score_entry')}?job_id={job.id}&stage_id={stage.id}")

        headers = rows[0]
        data_rows = rows[1:]

        # Map headers
        header_map = {name: index for index, name in enumerate(headers)}
        
        state_id_idx = header_map.get("شناسه وضعیت")
        score_idx = header_map.get("نمره نهایی مرحله")
        status_idx = header_map.get("وضعیت ارزیابی")
        notes_idx = header_map.get("توضیحات و یادداشت ارزیاب")
        if notes_idx is None:
            notes_idx = header_map.get("توضیحات")

        if state_id_idx is None or score_idx is None or status_idx is None:
            messages.error(request, "ستون‌های حیاتی 'شناسه وضعیت'، 'نمره نهایی مرحله' یا 'وضعیت ارزیابی' یافت نشدند.")
            return redirect(f"{reverse('candidate_score_entry')}?job_id={job.id}&stage_id={stage.id}")

        success_count = 0
        error_count = 0
        errors = []

        # Map Persian status string to DB status choices
        status_mapping = {
            "در انتظار ارزیابی": 'PENDING',
            "در انتظار": 'PENDING',
            "pending": 'PENDING',
            "قبول شده در این مرحله": 'COMPLETED',
            "قبول": 'COMPLETED',
            "completed": 'COMPLETED',
            "مردود شده در این مرحله": 'FAILED',
            "مردود": 'FAILED',
            "failed": 'FAILED',
        }

        try:
            with transaction.atomic():
                for idx, row in enumerate(data_rows, start=2):
                    # Skip completely empty rows
                    if not any(row):
                        continue

                    state_id = row[state_id_idx]
                    score_val = row[score_idx]
                    status_str = row[status_idx]
                    notes_val = row[notes_idx] if notes_idx is not None else ""

                    if not state_id:
                        errors.append(f"ردیف {idx}: شناسه وضعیت خالی است.")
                        error_count += 1
                        continue

                    # Fetch and verify stage state
                    state = ApplicationStageState.objects.filter(
                        id=state_id,
                        application__job=job,
                        stage=stage,
                        is_deleted=False
                    ).first()

                    if not state:
                        errors.append(f"ردیف {idx}: شناسه وضعیت {state_id} برای این شغل و مرحله معتبر نیست.")
                        error_count += 1
                        continue

                    if not state.is_accessible:
                        errors.append(f"ردیف {idx} ({state.application.candidate}): این مرحله قفل یا در دسترس نیست.")
                        error_count += 1
                        continue

                    # Parse score
                    try:
                        score = float(score_val) if score_val is not None else 0.0
                    except (ValueError, TypeError):
                        score = 0.0

                    # Parse status
                    db_status = 'PENDING'
                    if status_str:
                        clean_status = str(status_str).strip().lower()
                        db_status = status_mapping.get(clean_status, 'PENDING')

                    state.score = score
                    state.status = db_status
                    if notes_val:
                        state.notes = str(notes_val).strip()
                    state.evaluator = request.user
                    state.save()
                    success_count += 1
        except Exception as ex:
            messages.error(request, f"خطا در حین تراکنش بروزرسانی نمرات: {str(ex)}")
            return redirect(f"{reverse('candidate_score_entry')}?job_id={job.id}&stage_id={stage.id}")

        if success_count > 0:
            messages.success(request, f"نمرات تعداد {success_count} متقاضی با موفقیت از فایل اکسل بروزرسانی شد.")
        if error_count > 0:
            messages.error(request, f"بروزرسانی تعداد {error_count} ردیف با خطا مواجه شد:<br>" + "<br>".join(errors[:10]))

        return redirect(f"{reverse('candidate_score_entry')}?job_id={job.id}&stage_id={stage.id}")


class ManageStageInterviewersView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_SPECIALIST, UserProfile.ROLE_RECRUITMENT_DIRECTOR]

    def get(self, request, stage_id):
        from apps.jobs.models import JobOpportunityStage, JobStageInterviewer
        stage = get_object_or_404(JobOpportunityStage, pk=stage_id, is_deleted=False)
        interviewers = stage.interviewers.filter(is_deleted=False).select_related('user')
        competencies = stage.competencies.filter(is_deleted=False)
        
        from django.contrib.auth.models import User
        available_users = User.objects.filter(
            profile__role__in=[
                UserProfile.ROLE_ADMIN,
                UserProfile.ROLE_RECRUITMENT_SPECIALIST,
                UserProfile.ROLE_RECRUITMENT_DIRECTOR,
                UserProfile.ROLE_INTERVIEWER,
                UserProfile.ROLE_EXTERNAL_ASSESSOR
            ],
            is_active=True
        ).order_by('first_name', 'username')

        return render(request, 'candidates/partials/stage_interviewers_manage.html', {
            'stage': stage,
            'interviewers': interviewers,
            'available_users': available_users,
            'competencies': competencies,
        })

    def post(self, request, stage_id):
        from apps.jobs.models import JobOpportunityStage, JobStageInterviewer, AssessmentCompetency
        stage = get_object_or_404(JobOpportunityStage, pk=stage_id, is_deleted=False)
        
        passing_score_val = request.POST.get('passing_score')
        if passing_score_val:
            try:
                stage.passing_score = float(passing_score_val)
                stage.save()
                for state in stage.candidate_states.filter(is_deleted=False):
                    state.save()
            except ValueError:
                pass
                
        action = request.POST.get('action')

        if action == 'delete':
            assignment_id = request.POST.get('assignment_id')
            assignment = get_object_or_404(JobStageInterviewer, pk=assignment_id, stage=stage)
            assignment.delete()
        elif action == 'add':
            user_id = request.POST.get('user_id')
            weight_val = request.POST.get('weight', '100')
            group_name = request.POST.get('group_name', '')
            
            try:
                weight = int(weight_val)
            except ValueError:
                weight = 100

            from django.contrib.auth.models import User
            user = get_object_or_404(User, pk=user_id)
            
            assignment = JobStageInterviewer.all_objects.filter(stage=stage, user=user).first()
            if assignment:
                assignment.is_deleted = False
                assignment.deleted_at = None
                assignment.weight = weight
                assignment.group_name = group_name
                assignment.save()
            else:
                JobStageInterviewer.objects.create(
                    job=stage.job,
                    stage=stage,
                    user=user,
                    weight=weight,
                    group_name=group_name
                )
        elif action == 'add_competency':
            comp_name = request.POST.get('competency_name')
            comp_weight_val = request.POST.get('competency_weight', '100')
            try:
                comp_weight = int(comp_weight_val)
            except ValueError:
                comp_weight = 100
            
            if comp_name:
                comp = AssessmentCompetency.all_objects.filter(stage=stage, name=comp_name).first()
                if comp:
                    comp.is_deleted = False
                    comp.deleted_at = None
                    comp.weight = comp_weight
                    comp.save()
                else:
                    AssessmentCompetency.objects.create(
                        stage=stage,
                        name=comp_name,
                        weight=comp_weight
                    )
        elif action == 'delete_competency':
            comp_id = request.POST.get('competency_id')
            AssessmentCompetency.objects.filter(pk=comp_id, stage=stage).delete()

        interviewers = stage.interviewers.filter(is_deleted=False).select_related('user')
        competencies = stage.competencies.filter(is_deleted=False)
        from django.contrib.auth.models import User
        available_users = User.objects.filter(
            profile__role__in=[
                UserProfile.ROLE_ADMIN,
                UserProfile.ROLE_RECRUITMENT_SPECIALIST,
                UserProfile.ROLE_RECRUITMENT_DIRECTOR,
                UserProfile.ROLE_INTERVIEWER,
                UserProfile.ROLE_EXTERNAL_ASSESSOR
            ],
            is_active=True
        ).order_by('first_name', 'username')

        return render(request, 'candidates/partials/stage_interviewers_manage.html', {
            'stage': stage,
            'interviewers': interviewers,
            'available_users': available_users,
            'competencies': competencies,
        })


class InterviewsPanelView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_INTERVIEWER,
        UserProfile.ROLE_EXTERNAL_ASSESSOR
    ]

    def get(self, request):
        from apps.jobs.models import JobStageInterviewer
        from django.db.models import F
        from apps.accounts.permissions import check_stage_access

        user_profile = request.user.profile

        # 1. Staff / Admin can view all active stage states
        if user_profile.is_recruitment_staff or user_profile.role == UserProfile.ROLE_ADMIN:
            active_stage_states = ApplicationStageState.objects.filter(
                application__status=JobApplication.STATUS_IN_PROGRESS,
                application__is_deleted=False,
                stage=F('application__current_stage'),
                is_deleted=False
            ).select_related('application__candidate', 'application__job', 'stage').order_by('application__candidate__last_name')
        else:
            # 2. Non-staff (Interviewers / Assessors) can only see stage states where they are explicitly assigned
            assigned_stage_ids = JobStageInterviewer.objects.filter(
                user=request.user, is_deleted=False
            ).values_list('stage_id', flat=True)

            active_stage_states = ApplicationStageState.objects.filter(
                application__status=JobApplication.STATUS_IN_PROGRESS,
                application__is_deleted=False,
                stage_id__in=assigned_stage_ids,
                stage=F('application__current_stage'),
                is_deleted=False
            ).select_related('application__candidate', 'application__job', 'stage').order_by('application__candidate__last_name')

            # 3. Apply role-based stage type check
            filtered_states = []
            for state in active_stage_states:
                if check_stage_access(request.user, state.stage):
                    filtered_states.append(state)
            active_stage_states = filtered_states

        for state in active_stage_states:
            my_score = state.interviewer_scores.filter(interviewer=request.user, is_deleted=False).first()
            state.my_score_obj = my_score

        return render(request, 'candidates/interviews.html', {
            'stage_states': active_stage_states,
        })


class SubmitInterviewerScoreView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_INTERVIEWER,
        UserProfile.ROLE_EXTERNAL_ASSESSOR
    ]

    def post(self, request, pk):
        from .models import InterviewerScore
        from apps.accounts.permissions import check_stage_access
        
        state = get_object_or_404(ApplicationStageState, pk=pk, is_deleted=False)
        
        # Enforce role-based stage type check
        if not check_stage_access(request.user, state.stage):
            raise PermissionDenied("شما دسترسی لازم برای ثبت نمره در این مرحله را ندارید.")
            
        # Enforce explicit interviewer assignment check for non-staff/admins
        if not (request.user.profile.is_recruitment_staff or request.user.profile.role == UserProfile.ROLE_ADMIN):
            from apps.jobs.models import JobStageInterviewer
            is_assigned = JobStageInterviewer.objects.filter(
                stage=state.stage,
                user=request.user,
                is_deleted=False
            ).exists()
            if not is_assigned:
                raise PermissionDenied("شما به عنوان مصاحبه‌گر به این مرحله تخصیص داده نشده‌اید.")
        
        score_val = request.POST.get('score', '0')
        status_val = 'COMPLETED'
        notes_val = request.POST.get('notes', '')

        try:
            score_float = float(score_val)
        except ValueError:
            score_float = 0.0

        with transaction.atomic():
            iscore, created = InterviewerScore.objects.get_or_create(
                stage_state=state,
                interviewer=request.user,
                defaults={'score': score_float, 'status': status_val, 'notes': notes_val}
            )
            if not created:
                iscore.score = score_float
                iscore.status = status_val
                iscore.notes = notes_val
                iscore.save()

        return render(request, 'candidates/partials/interviewer_score_row_saved.html', {
            'state': state,
            'iscore': iscore,
        })


class JobOpportunityDescriptionView(LoginRequiredMixin, View):
    def get(self, request, pk):
        from apps.jobs.models import JobOpportunity
        job = get_object_or_404(JobOpportunity, pk=pk, is_deleted=False)
        return render(request, 'candidates/partials/job_description_modal.html', {'job': job})


class AssessmentCenterSheetView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_INTERVIEWER,
        UserProfile.ROLE_EXTERNAL_ASSESSOR
    ]

    def get(self, request, pk):
        from .models import InterviewerScore, AssessorCompetencyScore
        from apps.accounts.permissions import check_stage_access
        
        state = get_object_or_404(ApplicationStageState, pk=pk, is_deleted=False)
        
        # Enforce role-based stage type check
        if not check_stage_access(request.user, state.stage):
            raise PermissionDenied("شما دسترسی لازم برای مشاهده این برگ ارزیابی را ندارید.")
            
        # Enforce explicit interviewer assignment check for non-staff/admins
        if not (request.user.profile.is_recruitment_staff or request.user.profile.role == UserProfile.ROLE_ADMIN):
            from apps.jobs.models import JobStageInterviewer
            is_assigned = JobStageInterviewer.objects.filter(
                stage=state.stage,
                user=request.user,
                is_deleted=False
            ).exists()
            if not is_assigned:
                raise PermissionDenied("شما به عنوان ارزیاب به این مرحله تخصیص داده نشده‌اید.")

        competencies = state.stage.competencies.filter(is_deleted=False)
        
        iscore = state.interviewer_scores.filter(interviewer=request.user, is_deleted=False).first()
        comp_scores = {}
        if iscore:
            for cs in iscore.competency_scores.filter(is_deleted=False):
                comp_scores[cs.competency_id] = cs
                
        comp_data = []
        for c in competencies:
            comp_data.append({
                'competency': c,
                'score_obj': comp_scores.get(c.id)
            })

        return render(request, 'candidates/partials/assessment_center_sheet.html', {
            'state': state,
            'comp_data': comp_data,
            'iscore': iscore,
            'source': request.GET.get('source'),
        })

    def post(self, request, pk):
        from .models import InterviewerScore, AssessorCompetencyScore
        from apps.accounts.permissions import check_stage_access
        
        state = get_object_or_404(ApplicationStageState, pk=pk, is_deleted=False)
        
        # Enforce role-based stage type check
        if not check_stage_access(request.user, state.stage):
            raise PermissionDenied("شما دسترسی لازم برای ثبت نمره در این مرحله را ندارید.")
            
        # Enforce explicit interviewer assignment check for non-staff/admins
        if not (request.user.profile.is_recruitment_staff or request.user.profile.role == UserProfile.ROLE_ADMIN):
            from apps.jobs.models import JobStageInterviewer
            is_assigned = JobStageInterviewer.objects.filter(
                stage=state.stage,
                user=request.user,
                is_deleted=False
            ).exists()
            if not is_assigned:
                raise PermissionDenied("شما به عنوان ارزیاب به این مرحله تخصیص داده نشده‌اید.")

        competencies = state.stage.competencies.filter(is_deleted=False)

        notes_val = request.POST.get('notes', '')
        source = request.POST.get('source')

        with transaction.atomic():
            iscore, created = InterviewerScore.objects.get_or_create(
                stage_state=state,
                interviewer=request.user,
                defaults={'score': 0.0, 'status': 'COMPLETED', 'notes': notes_val}
            )
            iscore.status = 'COMPLETED'
            iscore.notes = notes_val
            iscore.save()

            for c in competencies:
                score_val = request.POST.get(f'comp_score_{c.id}', '0')
                comp_notes = request.POST.get(f'comp_notes_{c.id}', '')
                try:
                    score_float = float(score_val)
                except ValueError:
                    score_float = 0.0

                cs_obj, cs_created = AssessorCompetencyScore.objects.get_or_create(
                    interviewer_score=iscore,
                    competency=c,
                    defaults={'score': score_float, 'notes': comp_notes}
                )
                if not cs_created:
                    cs_obj.score = score_float
                    cs_obj.notes = comp_notes
                    cs_obj.save()

            iscore.save()

        if source == 'score_entry':
            return render(request, 'candidates/partials/score_entry_row.html', {
                'state': state,
            })

        return render(request, 'candidates/partials/interviewer_score_row_saved.html', {
            'state': state,
            'iscore': iscore,
        })


class AssessmentCenterReportView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_SPECIALIST, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_EXTERNAL_ASSESSOR]

    def get(self, request):
        states = ApplicationStageState.objects.filter(
            stage__competencies__isnull=False,
            is_deleted=False
        ).exclude(status=ApplicationStageState.STATUS_PENDING).select_related(
            'application__candidate', 'application__job', 'stage', 'evaluator'
        ).prefetch_related('interviewer_scores__competency_scores__competency').distinct().order_by('-updated_at')

        return render(request, 'candidates/assessment_report_list.html', {
            'states': states
        })


class AssessmentCenterDetailReportView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_SPECIALIST, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_EXTERNAL_ASSESSOR]

    def get(self, request, pk):
        state = get_object_or_404(ApplicationStageState, pk=pk, is_deleted=False)
        competencies = state.stage.competencies.filter(is_deleted=False)
        
        iscores = state.interviewer_scores.filter(is_deleted=False).exclude(status='PENDING').prefetch_related(
            'competency_scores__competency', 'interviewer'
        )

        comp_rows = []
        for comp in competencies:
            scores_detail = []
            for iscore in iscores:
                cs = iscore.competency_scores.filter(competency=comp, is_deleted=False).first()
                scores_detail.append({
                    'assessor': iscore.interviewer.get_full_name() or iscore.interviewer.username,
                    'score': cs.score if cs else None,
                    'notes': cs.notes if cs else ''
                })
            comp_rows.append({
                'competency': comp,
                'scores': scores_detail
            })

        return render(request, 'candidates/assessment_detail_report.html', {
            'state': state,
            'iscores': iscores,
            'comp_rows': comp_rows,
            'competencies': competencies,
        })


class JobOpportunityFinalRankingView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = JobOpportunity
    template_name = 'jobs/job_final_ranking.html'
    context_object_name = 'job'
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_SPECIALIST, UserProfile.ROLE_RECRUITMENT_DIRECTOR]

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        apps = self.object.applications.filter(is_deleted=False).select_related('candidate')
        data['applications'] = apps.order_by('-final_score')
        data['stages'] = self.object.stages.filter(is_deleted=False).order_by('sequence')
        data['selected_count'] = apps.filter(status=JobApplication.STATUS_SELECTED).count()
        data['reserve_count'] = apps.filter(status=JobApplication.STATUS_RESERVE).count()
        data['rejected_count'] = apps.filter(status=JobApplication.STATUS_REJECTED).count()
        return data


class BulkUpdateApplicationStatusView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_SPECIALIST, UserProfile.ROLE_RECRUITMENT_DIRECTOR]

    def post(self, request, job_id):
        job = get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)
        application_ids = request.POST.getlist('application_ids')
        status_action = request.POST.get('status_action')

        if status_action in dict(JobApplication.STATUS_CHOICES):
            with transaction.atomic():
                JobApplication.objects.filter(pk__in=application_ids, job=job, is_deleted=False).update(status=status_action)
                job.update_status()

        return redirect('job_final_ranking', pk=job_id)


class BulkAdvanceStageView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_SPECIALIST, UserProfile.ROLE_RECRUITMENT_DIRECTOR]

    def post(self, request, job_id):
        job = get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)
        application_ids = request.POST.getlist('application_ids')

        with transaction.atomic():
            for app_id in application_ids:
                app = JobApplication.objects.filter(pk=app_id, job=job, status=JobApplication.STATUS_IN_PROGRESS, is_deleted=False).first()
                if app and app.current_stage:
                    current_state = app.stage_states.filter(stage=app.current_stage, is_deleted=False).first()
                    if current_state and (current_state.status == ApplicationStageState.STATUS_COMPLETED or current_state.is_conditional_pass):
                        next_stage = job.stages.filter(
                            is_deleted=False, 
                            sequence__gt=app.current_stage.sequence
                        ).order_by('sequence').first()
                        
                        if next_stage:
                            app.current_stage = next_stage
                            app.save(update_fields=['current_stage'])
            job.update_status()

        return redirect('job_pipeline', pk=job_id)


class ExportCandidatesExcelView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request):
        from apps.candidates.views import CandidateListView
        view = CandidateListView()
        view.request = request
        view.args = ()
        view.kwargs = {}
        queryset = view.get_queryset()
        
        headers = [
            "شناسه", "نام", "نام خانوادگی", "کد ملی", "ایمیل", "تلفن", 
            "آخرین مدرک تحصیلی", "رشته تحصیلی", "دانشگاه", "سوابق شغلی", "مهارت‌ها", "فرصت‌های شغلی متقاضی"
        ]
        
        rows = []
        for candidate in queryset:
            edu = candidate.education.filter(is_deleted=False).order_by('-graduation_year').first()
            degree_display = edu.get_degree_display() if edu else ""
            major_display = edu.major if edu else ""
            univ_display = edu.university if edu else ""
            
            exps = [f"{exp.job_title} ({exp.company})" for exp in candidate.experience.filter(is_deleted=False)]
            exps_str = " | ".join(exps)
            
            skills = [s.name for s in candidate.skills.filter(is_deleted=False)]
            skills_str = ", ".join(skills)
            
            jobs = [app.job.title for app in candidate.applications.filter(is_deleted=False)]
            jobs_str = ", ".join(jobs)
            
            rows.append([
                candidate.id,
                candidate.first_name,
                candidate.last_name,
                candidate.national_id,
                candidate.email,
                candidate.phone_number,
                degree_display,
                major_display,
                univ_display,
                exps_str,
                skills_str,
                jobs_str
            ])
            
        from apps.core.utils import export_to_excel_response
        return export_to_excel_response("candidates_report.xlsx", headers, rows)


class ExportScoreEntryExcelView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_SPECIALIST, UserProfile.ROLE_RECRUITMENT_DIRECTOR]

    def get(self, request):
        from apps.jobs.models import JobOpportunity, JobOpportunityStage
        from apps.candidates.models import ApplicationStageState, JobApplication
        
        job_id = request.GET.get('job_id')
        stage_id = request.GET.get('stage_id')
        q = request.GET.get('q')
        eval_status = request.GET.get('eval_status', 'PENDING')
        show_failed_prior_val = request.GET.get('show_failed_prior')
        show_failed_prior = show_failed_prior_val in ['true', 'on', '1']
        
        if not job_id or not stage_id:
            return HttpResponse("شناسه فرصت شغلی و مرحله الزامی است.", status=400)
            
        job = get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)
        stage = get_object_or_404(JobOpportunityStage, pk=stage_id, is_deleted=False)
        
        pending_states_qs = ApplicationStageState.objects.filter(
            application__job=job,
            application__status=JobApplication.STATUS_IN_PROGRESS,
            application__is_deleted=False,
            stage=stage,
            is_deleted=False
        ).select_related('application__candidate', 'application__job', 'stage')
        
        from django.db.models import Exists, OuterRef
        # Annotate if there is a failed prior stage state
        prior_failed_subquery = ApplicationStageState.objects.filter(
            application=OuterRef('application'),
            stage__sequence__lt=OuterRef('stage__sequence'),
            status=ApplicationStageState.STATUS_FAILED,
            is_conditional_pass=False,
            is_deleted=False
        )
        pending_states_qs = pending_states_qs.annotate(
            has_failed_prior=Exists(prior_failed_subquery)
        )
        
        # Filter out prior failed stages unless specifically requested
        if not show_failed_prior:
            pending_states_qs = pending_states_qs.filter(has_failed_prior=False)

        if eval_status == 'PENDING':
            pending_states_qs = pending_states_qs.filter(status=ApplicationStageState.STATUS_PENDING)
        elif eval_status == 'COMPLETED_FAILED':
            pending_states_qs = pending_states_qs.filter(status__in=[ApplicationStageState.STATUS_COMPLETED, ApplicationStageState.STATUS_FAILED])
            
        if q:
            pending_states_qs = pending_states_qs.filter(
                models.Q(application__candidate__first_name__icontains=q) |
                models.Q(application__candidate__last_name__icontains=q) |
                models.Q(application__candidate__national_id__icontains=q)
            )
            
        states = pending_states_qs.order_by('application__candidate__last_name')
        
        headers = [
            "شناسه وضعیت", "نام متقاضی", "نام خانوادگی", "کد ملی", "عنوان شغل", "مرحله", 
            "نمره نهایی مرحله", "وضعیت ارزیابی", "تاریخ ارزیابی", "ارزیاب", "آخرین تغییر"
        ]
        
        from apps.core.templatetags.jalali_tags import to_jalali
        rows = []
        for state in states:
            evaluator_name = state.evaluator.get_full_name() if state.evaluator else str(state.evaluator or '')
            rows.append([
                state.id,
                state.application.candidate.first_name,
                state.application.candidate.last_name,
                state.application.candidate.national_id,
                job.title,
                stage.name,
                state.score if state.score is not None else "",
                state.get_status_display(),
                to_jalali(state.evaluation_date),
                evaluator_name,
                state.updated_at.strftime('%Y-%m-%d %H:%M') if state.updated_at else ""
            ])
            
        from apps.core.utils import export_to_excel_response
        filename = f"score_entry_{job.id}_{stage.id}.xlsx"
        return export_to_excel_response(filename, headers, rows)


class ExportInterviewsExcelView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [
        UserProfile.ROLE_ADMIN,
        UserProfile.ROLE_RECRUITMENT_SPECIALIST,
        UserProfile.ROLE_RECRUITMENT_DIRECTOR,
        UserProfile.ROLE_INTERVIEWER,
        UserProfile.ROLE_EXTERNAL_ASSESSOR
    ]

    def get(self, request):
        from apps.jobs.models import JobStageInterviewer
        from django.db.models import F
        from apps.accounts.permissions import check_stage_access
        
        user_profile = request.user.profile
        
        if user_profile.is_recruitment_staff or user_profile.role == UserProfile.ROLE_ADMIN:
            active_stage_states = ApplicationStageState.objects.filter(
                application__status=JobApplication.STATUS_IN_PROGRESS,
                application__is_deleted=False,
                stage=F('application__current_stage'),
                is_deleted=False
            ).select_related('application__candidate', 'application__job', 'stage').order_by('application__candidate__last_name')
        else:
            assigned_stage_ids = JobStageInterviewer.objects.filter(
                user=request.user, is_deleted=False
            ).values_list('stage_id', flat=True)

            active_stage_states = ApplicationStageState.objects.filter(
                application__status=JobApplication.STATUS_IN_PROGRESS,
                application__is_deleted=False,
                stage_id__in=assigned_stage_ids,
                stage=F('application__current_stage'),
                is_deleted=False
            ).select_related('application__candidate', 'application__job', 'stage').order_by('application__candidate__last_name')

            filtered_states = []
            for state in active_stage_states:
                if check_stage_access(request.user, state.stage):
                    filtered_states.append(state)
            active_stage_states = filtered_states

        headers = [
            "شناسه", "نام متقاضی", "نام خانوادگی", "عنوان شغل", "مرحله جاری", "نمره شما", "آخرین تغییر"
        ]
        
        rows = []
        for state in active_stage_states:
            my_score_obj = state.interviewer_scores.filter(interviewer=request.user, is_deleted=False).first()
            my_score = my_score_obj.score if my_score_obj else ""
            
            rows.append([
                state.id,
                state.application.candidate.first_name,
                state.application.candidate.last_name,
                state.application.job.title,
                state.stage.name,
                my_score,
                state.updated_at.strftime('%Y-%m-%d %H:%M') if state.updated_at else ""
            ])
            
        from apps.core.utils import export_to_excel_response
        return export_to_excel_response("my_interviews.xlsx", headers, rows)


class ExportAssessmentCenterExcelView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_SPECIALIST, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_EXTERNAL_ASSESSOR]

    def get(self, request):
        states = ApplicationStageState.objects.filter(
            stage__competencies__isnull=False,
            is_deleted=False
        ).exclude(status=ApplicationStageState.STATUS_PENDING).select_related(
            'application__candidate', 'application__job', 'stage'
        ).distinct().order_by('-updated_at')
        
        headers = [
            "شناسه وضعیت", "نام متقاضی", "نام خانوادگی", "کد ملی", "فرصت شغلی", "مرحله کانون", 
            "میانگین وزنی کانون", "حد نصاب قبولی", "وضعیت نتیجه", "آخرین به‌روزرسانی"
        ]
        
        rows = []
        for state in states:
            passing_score = state.stage.passing_score or 60.0
            score_val = state.score if state.score is not None else 0.0
            status_display = "قبول" if score_val >= passing_score else "مردود"
            
            rows.append([
                state.id,
                state.application.candidate.first_name,
                state.application.candidate.last_name,
                state.application.candidate.national_id,
                state.application.job.title,
                state.stage.name,
                state.score if state.score is not None else "",
                passing_score,
                status_display,
                state.updated_at.strftime('%Y-%m-%d %H:%M') if state.updated_at else ""
            ])
            
        from apps.core.utils import export_to_excel_response
        return export_to_excel_response("assessment_center_report.xlsx", headers, rows)


class ExportJobFinalRankingExcelView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_SPECIALIST, UserProfile.ROLE_RECRUITMENT_DIRECTOR]

    def get(self, request, pk):
        from apps.jobs.models import JobOpportunity
        from apps.candidates.models import JobApplication, ApplicationStageState
        job = get_object_or_404(JobOpportunity, pk=pk, is_deleted=False)
        apps = job.applications.filter(is_deleted=False).select_related('candidate').order_by('-final_score')
        stages = job.stages.filter(is_deleted=False).order_by('sequence')

        headers = ["رتبه", "نام", "نام خانوادگی", "کد ملی", "شماره پرسنلی", "امتیاز نهایی وزنی"]
        for stage in stages:
            headers.append(stage.name)
        headers.append("وضعیت درخواست")

        rows = []
        for idx, app in enumerate(apps, start=1):
            candidate = app.candidate
            row = [
                idx,
                candidate.first_name,
                candidate.last_name,
                candidate.national_id,
                candidate.personnel_number or "",
                app.final_score,
            ]
            for stage in stages:
                state = app.stage_states.filter(stage=stage, is_deleted=False).first()
                if state:
                    if state.status == 'COMPLETED':
                        row.append(state.score)
                    else:
                        row.append("در حال ارزیابی")
                else:
                    row.append("-")
            
            status_map = {
                'IN_PROGRESS': 'در حال بررسی / ارزیابی',
                'SELECTED': 'پذیرفته شده نهایی',
                'RESERVE': 'ذخیره',
                'REJECTED': 'رد شده',
            }
            row.append(status_map.get(app.status, app.status))
            rows.append(row)

        from apps.core.utils import export_to_excel_response
        filename = f"job_ranking_{job.id}.xlsx"
        return export_to_excel_response(filename, headers, rows)


class DownloadCandidateTemplateView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request):
        headers = [
            "نام", "نام خانوادگی", "کد ملی", "ایمیل", "شماره تماس", 
            "شماره پرسنلی (اختیاری)", "مدرک تحصیلی (کاردانی/کارشناسی/ارشد/دکتری)", "رشته تحصیلی", "مهارت‌ها (جدا شده با کاما)"
        ]
        sample_row = [
            "علی", "احمدی", "0012345678", "ali@example.com", "09121112222", 
            "98001", "کارشناسی ارشد", "هوش مصنوعی", "Python, Machine Learning, Git"
        ]
        
        from apps.core.utils import export_to_excel_response
        return export_to_excel_response("candidate_import_template.xlsx", headers, [sample_row])


class ImportCandidatesView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def post(self, request):
        from django.contrib import messages
        import openpyxl
        import re
        from django.contrib.auth.models import User
        from apps.accounts.models import UserProfile
        from apps.candidates.models import Candidate, JobApplication, CandidateEducation, CandidateSkill
        from apps.jobs.models import JobOpportunity

        view_param = request.GET.get('view')
        redirect_url = reverse('candidate_list')
        if view_param:
            redirect_url += f'?view={view_param}'

        excel_file = request.FILES.get('excel_file')
        job_id = request.POST.get('job_id')

        if not excel_file:
            messages.error(request, "لطفاً یک فایل اکسل انتخاب کنید.")
            return redirect(redirect_url)

        # Read Excel using openpyxl
        try:
            wb = openpyxl.load_workbook(excel_file)
            ws = wb.active
        except Exception as e:
            messages.error(request, f"خطا در خواندن فایل اکسل: {str(e)}")
            return redirect(redirect_url)

        rows = list(ws.iter_rows(values_only=True))
        if not rows or len(rows) < 2:
            messages.error(request, "فایل اکسل خالی است یا فاقد داده‌های معتبر می‌باشد.")
            return redirect(redirect_url)

        # First row is headers
        headers = rows[0]
        data_rows = rows[1:]

        # Check headers compatibility (basic check)
        expected_headers = ["نام", "نام خانوادگی", "کد ملی", "ایمیل", "شماره تماس"]
        for header in expected_headers:
            if header not in headers:
                messages.error(request, f"ستون حیاتی '{header}' در سربرگ‌های فایل اکسل یافت نشد. لطفاً از فایل نمونه استفاده کنید.")
                return redirect(redirect_url)

        # Map headers to indices
        header_map = {name: index for index, name in enumerate(headers)}
        
        success_count = 0
        errors = []

        # Target job (if any)
        target_job = None
        if job_id:
            target_job = JobOpportunity.objects.filter(id=job_id, is_deleted=False).first()

        for idx, row in enumerate(data_rows, start=2):
            # Skip completely empty rows
            if not any(row):
                continue

            first_name = row[header_map.get("نام")]
            last_name = row[header_map.get("نام خانوادگی")]
            national_id = row[header_map.get("کد ملی")]
            email = row[header_map.get("ایمیل")]
            phone_number = row[header_map.get("شماره تماس")]
            
            p_num_idx = header_map.get("شماره پرسنلی (اختیاری)")
            personnel_number = str(row[p_num_idx]).strip() if p_num_idx is not None and row[p_num_idx] is not None else None
            if not personnel_number:
                p_num_idx_alt = header_map.get("شماره پرسنلی")
                personnel_number = str(row[p_num_idx_alt]).strip() if p_num_idx_alt is not None and row[p_num_idx_alt] is not None else None

            # Optional new fields: degree, major, skills
            degree_idx = header_map.get("مدرک تحصیلی (کاردانی/کارشناسی/ارشد/دکتری)")
            if degree_idx is None:
                degree_idx = header_map.get("مدرک تحصیلی")
            if degree_idx is None:
                degree_idx = header_map.get("مقطع تحصیلی")
            degree_str = str(row[degree_idx]).strip() if degree_idx is not None and row[degree_idx] is not None else None

            major_idx = header_map.get("رشته تحصیلی")
            if major_idx is None:
                major_idx = header_map.get("رشته")
            major_str = str(row[major_idx]).strip() if major_idx is not None and row[major_idx] is not None else None

            skills_idx = header_map.get("مهارت‌ها (جدا شده با کاما)")
            if skills_idx is None:
                skills_idx = header_map.get("مهارت‌ها")
            if skills_idx is None:
                skills_idx = header_map.get("مهارت")
            skills_str = str(row[skills_idx]).strip() if skills_idx is not None and row[skills_idx] is not None else None

            # Basic Validation
            if not first_name or not last_name or not national_id or not email or not phone_number:
                errors.append(f"ردیف {idx}: تمامی فیلدهای نام، نام خانوادگی، کد ملی، ایمیل و شماره تماس اجباری هستند.")
                continue

            first_name = str(first_name).strip()
            last_name = str(last_name).strip()
            national_id = str(national_id).strip()
            email = str(email).strip()
            
            # Clean and normalize phone number (e.g. 9123456789 -> 09123456789)
            phone_str = str(phone_number).strip()
            if phone_str.endswith('.0'):
                phone_str = phone_str[:-2]
            phone_str = phone_str.replace(" ", "")
            if phone_str and not phone_str.startswith('0') and len(phone_str) == 10:
                phone_str = '0' + phone_str
            phone_number = phone_str

            # Validate National ID (10 digits)
            if not re.match(r'^\d{10}$', national_id):
                errors.append(f"ردیف {idx} ({first_name} {last_name}): کد ملی باید دقیقاً ۱۰ رقم عددی باشد.")
                continue

            # Validate Email format
            if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
                errors.append(f"ردیف {idx} ({first_name} {last_name}): فرمت ایمیل نامعتبر است.")
                continue

            # Check duplicate national_id in DB
            if Candidate.objects.filter(national_id=national_id, is_deleted=False).exists():
                errors.append(f"ردیف {idx} ({first_name} {last_name}): متقاضی با کد ملی {national_id} از قبل در سیستم وجود دارد.")
                continue

            # Check duplicate user in DB
            if User.objects.filter(username=national_id).exists():
                errors.append(f"ردیف {idx} ({first_name} {last_name}): کاربر سیستم با کد ملی {national_id} از قبل در سیستم وجود دارد.")
                continue

            # Check duplicate personnel number (if provided)
            if personnel_number and Candidate.objects.filter(personnel_number=personnel_number, is_deleted=False).exists():
                errors.append(f"ردیف {idx} ({first_name} {last_name}): متقاضی با شماره پرسنلی {personnel_number} از قبل وجود دارد.")
                continue

            # Map Persian degree string to DB choices keys
            degree_choice = None
            if degree_str:
                val = degree_str.lower()
                if "ارشد" in val or "master" in val or "فوق لیسانس" in val:
                    degree_choice = 'MASTER'
                elif "دکتری" in val or "phd" in val or "دکترا" in val:
                    degree_choice = 'PHD'
                elif "کاردانی" in val or "associate" in val or "فوق دیپلم" in val:
                    degree_choice = 'ASSOCIATE'
                elif "کارشناسی" in val or "bachelor" in val or "لیسانس" in val:
                    degree_choice = 'BACHELOR'

            # Create candidate
            try:
                with transaction.atomic():
                    # Create Django User
                    user = User.objects.create_user(
                        username=national_id,
                        email=email,
                        password=phone_number,
                        first_name=first_name,
                        last_name=last_name
                    )
                    
                    # Update UserProfile role to CANDIDATE
                    profile = user.profile
                    profile.role = UserProfile.ROLE_CANDIDATE
                    profile.phone_number = phone_number
                    profile.save()

                    # Create Candidate
                    candidate = Candidate.objects.create(
                        user=user,
                        first_name=first_name,
                        last_name=last_name,
                        national_id=national_id,
                        email=email,
                        phone_number=phone_number,
                        personnel_number=personnel_number if personnel_number else None
                    )
                    
                    # Create education record if degree and major are specified
                    if degree_choice and major_str:
                        CandidateEducation.objects.create(
                            candidate=candidate,
                            degree=degree_choice,
                            major=major_str,
                            university="ثبت نشده",
                            gpa=0.0,
                            graduation_year=1400
                        )

                    # Create skill records if specified
                    if skills_str:
                        skills_list = [s.strip() for s in re.split(r'[,،]', skills_str) if s.strip()]
                        for s_name in skills_list:
                            CandidateSkill.objects.create(
                                candidate=candidate,
                                name=s_name,
                                level='INTERMEDIATE'
                            )

                    # If target job is specified, create JobApplication
                    if target_job:
                        JobApplication.objects.create(
                            job=target_job,
                            candidate=candidate
                        )
                success_count += 1
            except Exception as ex:
                errors.append(f"ردیف {idx} ({first_name} {last_name}): خطا در ثبت داده‌ها: {str(ex)}")

        # Build final feedback message
        if success_count > 0:
            msg = f"تعداد {success_count} متقاضی جدید با موفقیت از فایل اکسل وارد شدند."
            if target_job:
                msg += f" و به فرصت شغلی '{target_job.title}' انتساب یافتند."
            messages.success(request, msg)

        if errors:
            err_msg = "برخی ردیف‌ها با خطا مواجه شدند:<br>" + "<br>".join(errors)
            messages.error(request, err_msg)

        return redirect(redirect_url)


from django.contrib.auth.views import PasswordChangeView
from django.contrib.auth.forms import PasswordChangeForm

class CandidatePasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    form_class = PasswordChangeForm
    template_name = 'candidates/password_change.html'

    def get_success_url(self):
        user = self.request.user
        if hasattr(user, 'profile') and user.profile.role == UserProfile.ROLE_CANDIDATE:
            return reverse('candidate_dashboard')
        return reverse('dashboard')

    def form_valid(self, form):
        from django.contrib import messages
        messages.success(self.request, "رمز عبور شما با موفقیت تغییر یافت.")
        return super().form_valid(form)


class CandidateResumePrintView(LoginRequiredMixin, RoleRequiredMixin, View):
    """نمایش رزومه چاپ‌آماده بر اساس اطلاعات موجود در سامانه"""
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request, pk):
        candidate = get_object_or_404(Candidate, pk=pk, is_deleted=False)
        context = {
            'candidate': candidate,
            'education_list': candidate.education.filter(is_deleted=False).order_by('-graduation_year'),
            'experience_list': candidate.experience.filter(is_deleted=False).order_by('-start_date'),
            'language_list': candidate.languages.filter(is_deleted=False),
            'skill_list': candidate.skills.filter(is_deleted=False),
            'certificate_list': candidate.certificates.filter(is_deleted=False).order_by('-issue_date'),
            'applications': candidate.applications.filter(is_deleted=False).select_related('job', 'current_stage'),
        }
        return render(request, 'candidates/candidate_resume_print.html', context)


class CandidateTranscriptPrintView(LoginRequiredMixin, RoleRequiredMixin, View):
    """کارنامه آزمون / ارزیابی یک درخواست شغلی خاص"""
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request, pk):
        application = get_object_or_404(
            JobApplication,
            pk=pk,
            is_deleted=False
        )
        stage_states = application.stage_states.filter(
            is_deleted=False
        ).select_related('stage', 'evaluator').order_by('stage__sequence')
        context = {
            'application': application,
            'candidate': application.candidate,
            'job': application.job,
            'stage_states': stage_states,
        }
        return render(request, 'candidates/candidate_transcript_print.html', context)

