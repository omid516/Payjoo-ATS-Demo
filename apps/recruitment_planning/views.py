import datetime
import jdatetime
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.db import transaction
from django.urls import reverse

from apps.accounts.models import UserProfile
from apps.accounts.permissions import RoleRequiredMixin
from apps.jobs.models import JobOpportunity, JobOpportunityStage
from .models import StageTypeConfiguration, Holiday, JobRecruitmentPlan, JobStagePlan
from .utils import (
    to_jalali_string, parse_jalali_to_gregorian, 
    calculate_recruitment_schedule, get_jalali_month_range
)
from apps.candidates.models import ApplicationStageState

class PlanningDashboardView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request):
        today = datetime.date.today()
        j_today = jdatetime.date.fromgregorian(date=today)
        
        # Read year and month from query parameters, fallback to current Jalali date
        try:
            year = int(request.GET.get('year', j_today.year))
            month = int(request.GET.get('month', j_today.month))
        except (ValueError, TypeError):
            year = j_today.year
            month = j_today.month
            
        JALALI_MONTH_NAMES = [
            "", "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
            "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
        ]
        
        # Format month name in Farsi
        current_month_name = f"{JALALI_MONTH_NAMES[month]} {year}"
        
        # Calculate prev and next months
        prev_month = month - 1
        prev_year = year
        if prev_month < 1:
            prev_month = 12
            prev_year -= 1
            
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year += 1
            
        # Get start/end dates of requested Jalali month
        g_start, g_end = get_jalali_month_range(year, month)

        # Get query parameters
        search_query = request.GET.get('q', '').strip()
        selected_dept = request.GET.get('department', '').strip()
        sort_by = request.GET.get('sort_by', '-created_at').strip()

        # Active plans
        active_plans = JobRecruitmentPlan.objects.filter(
            status=JobRecruitmentPlan.STATUS_ACTIVE, 
            is_deleted=False,
            job__is_deleted=False
        ).exclude(job__status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED, JobOpportunity.STATUS_SUSPENDED])
        
        draft_plans = JobRecruitmentPlan.objects.filter(
            status=JobRecruitmentPlan.STATUS_DRAFT, 
            is_deleted=False,
            job__is_deleted=False
        ).exclude(job__status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED, JobOpportunity.STATUS_SUSPENDED])

        # Get list of unique departments for the dropdown
        departments = JobOpportunity.objects.filter(
            is_deleted=False
        ).exclude(
            department=''
        ).values_list('department', flat=True).distinct().order_by('department')

        # Apply filtering to active plans & drafts
        from django.db.models import Q
        if search_query:
            active_plans = active_plans.filter(
                Q(job__title__icontains=search_query) | 
                Q(job__code__icontains=search_query) |
                Q(job__request_number__icontains=search_query)
            )
            draft_plans = draft_plans.filter(
                Q(job__title__icontains=search_query) | 
                Q(job__code__icontains=search_query) |
                Q(job__request_number__icontains=search_query)
            )

        if selected_dept:
            active_plans = active_plans.filter(job__department=selected_dept)
            draft_plans = draft_plans.filter(job__department=selected_dept)

        # Apply sorting to active plans
        valid_sorts = {
            'start_date': 'start_date',
            '-start_date': '-start_date',
            'predicted_end_date': 'predicted_end_date',
            '-predicted_end_date': '-predicted_end_date',
            'title': 'job__title',
            '-title': '-job__title',
            'headcount': '-job__headcount',
            'created_at': 'created_at',
            '-created_at': '-created_at'
        }
        order_by_field = valid_sorts.get(sort_by, '-created_at')
        active_plans = active_plans.order_by(order_by_field)
        
        # Find delayed plans (outside SLA)
        delayed_plans = []
        for plan in active_plans:
            is_delayed = False
            for stage_plan in plan.stage_plans.filter(is_deleted=False):
                # Check if this stage is completed in candidates evaluations
                # It is considered incomplete if any candidate application stage state is in PENDING
                pending_evals = ApplicationStageState.objects.filter(
                    stage=stage_plan.stage,
                    status=ApplicationStageState.STATUS_PENDING,
                    is_deleted=False
                )
                if pending_evals.exists() and stage_plan.planned_end_date < today:
                    is_delayed = True
                    break
            if is_delayed:
                delayed_plans.append(plan)

        # Capacity gauges for current month
        stage_types = ['SCREENING', 'EXAM', 'SKILL_TEST', 'IQ_TEST', 'INTERVIEW', 'ASSESSMENT']
        capacity_stats = []
        configs = {c.stage_type: c for c in StageTypeConfiguration.objects.filter(is_deleted=False)}
        
        for stype in stage_types:
            config = configs.get(stype)
            capacity_limit = config.monthly_capacity if config else 100
            
            from .utils import get_consumed_capacity
            consumed = get_consumed_capacity(stype, g_start, g_end, year, month)
            
            remaining = max(0, capacity_limit - consumed)
            percentage = round((consumed / capacity_limit) * 100, 1) if capacity_limit > 0 else 0
            
            # Map type to Farsi label
            labels = {
                'SCREENING': 'غربالگری اولیه',
                'EXAM': 'آزمون کتبی',
                'SKILL_TEST': 'آزمون مهارتی',
                'IQ_TEST': 'تست هوش',
                'INTERVIEW': 'مصاحبه حضوری',
                'ASSESSMENT': 'کانون ارزیابی'
            }
            
            capacity_stats.append({
                'type': stype,
                'label': labels.get(stype, stype),
                'limit': capacity_limit,
                'consumed': consumed,
                'remaining': remaining,
                'percentage': percentage
            })

        # List of active jobs that are NOT planned yet
        unplanned_jobs = JobOpportunity.objects.filter(
            is_deleted=False
        ).exclude(
            status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED, JobOpportunity.STATUS_SUSPENDED]
        ).exclude(
            recruitment_plan__isnull=False,
            recruitment_plan__is_deleted=False
        )

        if search_query:
            unplanned_jobs = unplanned_jobs.filter(
                Q(title__icontains=search_query) | 
                Q(code__icontains=search_query)
            )
        if selected_dept:
            unplanned_jobs = unplanned_jobs.filter(department=selected_dept)
            
        unplanned_jobs = unplanned_jobs.order_by('title')


        # Agenda for the next 7 days
        agenda_events = []
        for i in range(7):
            target_date = today + datetime.timedelta(days=i)
            j_date = jdatetime.date.fromgregorian(date=target_date)
            date_label = f"{JALALI_MONTH_NAMES[j_date.month]} {j_date.day}"
            if i == 0:
                day_name = "امروز"
            elif i == 1:
                day_name = "فردا"
            else:
                # Get day of week in Farsi (weekday() Monday=0 to Sunday=6)
                weekdays = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یک‌شنبه"]
                day_name = weekdays[target_date.weekday()]

            starts = JobStagePlan.objects.filter(
                planned_start_date=target_date,
                plan__status=JobRecruitmentPlan.STATUS_ACTIVE,
                plan__is_deleted=False,
                plan__job__is_deleted=False,
                is_deleted=False
            ).exclude(
                plan__job__status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED, JobOpportunity.STATUS_SUSPENDED]
            ).select_related('plan__job', 'stage')

            ends = JobStagePlan.objects.filter(
                planned_end_date=target_date,
                plan__status=JobRecruitmentPlan.STATUS_ACTIVE,
                plan__is_deleted=False,
                plan__job__is_deleted=False,
                is_deleted=False
            ).exclude(
                plan__job__status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED, JobOpportunity.STATUS_SUSPENDED]
            ).select_related('plan__job', 'stage')

            events = []
            for sp in starts:
                events.append({
                    'type': 'START',
                    'job_title': sp.plan.job.title,
                    'stage_name': sp.stage.name,
                    'badge_color': 'success',
                })
            for sp in ends:
                events.append({
                    'type': 'END',
                    'job_title': sp.plan.job.title,
                    'stage_name': sp.stage.name,
                    'badge_color': 'danger',
                })

            if events:
                agenda_events.append({
                    'date': target_date,
                    'jalali_str': f"{day_name} ({date_label})",
                    'events': events
                })

        context = {
            'active_plans': active_plans,
            'draft_plans': draft_plans,
            'delayed_plans': delayed_plans,
            'delayed_count': len(delayed_plans),
            'capacity_stats': capacity_stats,
            'unplanned_jobs': unplanned_jobs,
            'current_month_name': current_month_name,
            'today_jalali': to_jalali_string(today),
            'prev_year': prev_year,
            'prev_month': prev_month,
            'next_year': next_year,
            'next_month': next_month,
            'selected_year': year,
            'selected_month': month,
            'agenda_events': agenda_events,
            'search_query': search_query,
            'selected_dept': selected_dept,
            'sort_by': sort_by,
            'departments': departments,
        }
        return render(request, 'recruitment_planning/dashboard.html', context)


class JobPlanningView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request, job_id):
        job = get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)
        plan = getattr(job, 'recruitment_plan', None)
        if plan and plan.is_deleted:
            plan = None
        
        stages = job.stages.filter(is_deleted=False).order_by('sequence')
        
        context = {
            'job': job,
            'plan': plan,
            'stages': stages,
            'current_stage': job.current_stage,
            'today_jalali': to_jalali_string(datetime.date.today())
        }
        if request.GET.get('modal') == '1':
            context['next_url'] = request.GET.get('next', '')
            return render(request, 'recruitment_planning/partials/planning_modal_content.html', context)
            
        return render(request, 'recruitment_planning/job_planning.html', context)

    def post(self, request, job_id):
        job = get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)
        start_date_str = request.POST.get('start_date', '')
        start_date = parse_jalali_to_gregorian(start_date_str)
        
        if not start_date:
            return HttpResponse('<div class="alert alert-danger text-xs font-bold text-right mb-0">لطفا تاریخ شروع معتبری وارد کنید.</div>', status=400)

        # Parse overrides if any exist in the post data
        stages = job.stages.filter(is_deleted=False)
        has_interactive_schedule = any(k.startswith('start_date_') for k in request.POST.keys())
        overrides = {}
        if has_interactive_schedule:
            for stage in stages:
                stage_id = stage.id
                overrides[stage_id] = {
                    'is_exact': f'is_exact_{stage_id}' in request.POST
                }
                st_val = request.POST.get(f'start_date_{stage_id}')
                en_val = request.POST.get(f'end_date_{stage_id}')
                if st_val:
                    overrides[stage_id]['planned_start_date'] = parse_jalali_to_gregorian(st_val)
                if en_val:
                    overrides[stage_id]['planned_end_date'] = parse_jalali_to_gregorian(en_val)

        # Generate schedule preview
        schedule = calculate_recruitment_schedule(job, start_date, overrides=overrides)
        
        # Check if it is a preview request
        action = request.POST.get('action', 'preview')
        if action == 'preview':
            context = {
                'schedule': schedule,
                'job': job,
                'start_date_str': start_date_str
            }
            return render(request, 'recruitment_planning/partials/schedule_preview.html', context)

        # Save Plan Action
        if not schedule:
            return HttpResponse('<div class="alert alert-danger text-xs font-bold text-right mb-0">خطا: این فرصت شغلی هیچ مرحله ارزیابی تعریف‌شده‌ای ندارد.</div>', status=400)

        with transaction.atomic():
            # Look up including soft-deleted plans to avoid UNIQUE constraint violations
            plan = JobRecruitmentPlan.all_objects.filter(job=job).first()
            if plan:
                plan.start_date = start_date
                plan.predicted_end_date = schedule[-1]['planned_end_date']
                plan.status = JobRecruitmentPlan.STATUS_ACTIVE
                plan.is_deleted = False
                plan.save()
            else:
                plan = JobRecruitmentPlan.objects.create(
                    job=job,
                    start_date=start_date,
                    predicted_end_date=schedule[-1]['planned_end_date'],
                    status=JobRecruitmentPlan.STATUS_ACTIVE
                )

            # Clean and rebuild stage plans
            plan.stage_plans.all().delete()
            for s in schedule:
                JobStagePlan.objects.create(
                    plan=plan,
                    stage=s['stage'],
                    stage_type=s['stage_type'],
                    planned_start_date=s['planned_start_date'],
                    planned_end_date=s['planned_end_date'],
                    sla_days=s['sla_days'],
                    capacity_shifted=s['capacity_shifted'],
                    is_exact=s['is_exact']
                )

        next_param = request.GET.get('next') or request.POST.get('next')
        if next_param == 'print_doc':
            redirect_url = reverse('job_print_doc', kwargs={'pk': job.pk})
        else:
            redirect_url = next_param if next_param else reverse("planning_dashboard")

        if request.headers.get('HX-Request'):
            response = HttpResponse()
            response['HX-Redirect'] = redirect_url
            return response
        return redirect(redirect_url)


class PlanningConfigView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR]

    def get(self, request):
        configs = StageTypeConfiguration.objects.filter(is_deleted=False)
        holidays = Holiday.objects.filter(is_deleted=False).order_by('date')
        
        defaults = [
            ('SCREENING', 'غربالگری اولیه', 5, 200),
            ('EXAM', 'آزمون کتبی', 15, 300),
            ('SKILL_TEST', 'آزمون مهارتی', 15, 150),
            ('INTERVIEW', 'مصاحبه حضوری', 10, 80),
            ('ASSESSMENT', 'کانون ارزیابی', 15, 20),
            ('OTHER', 'سایر مراحل', 5, 100)
        ]
        
        with transaction.atomic():
            for code, name, sla, cap in defaults:
                StageTypeConfiguration.objects.get_or_create(
                    stage_type=code,
                    defaults={'default_sla_days': sla, 'monthly_capacity': cap}
                )
        
        context = {
            'configs': configs,
            'holidays': holidays,
            'today_jalali': to_jalali_string(datetime.date.today())
        }
        return render(request, 'recruitment_planning/config.html', context)

    def post(self, request):
        action = request.POST.get('action')
        
        # 1. Update SLA/Capacity Configs
        if action == 'save_configs':
            configs = StageTypeConfiguration.objects.filter(is_deleted=False)
            with transaction.atomic():
                for c in configs:
                    sla_val = request.POST.get(f'sla_{c.stage_type}')
                    cap_val = request.POST.get(f'capacity_{c.stage_type}')
                    if sla_val:
                        c.default_sla_days = int(sla_val)
                    if cap_val:
                        c.monthly_capacity = int(cap_val)
                    c.save()
            return redirect('planning_config')

        # 2. Add Holiday
        elif action == 'add_holiday':
            title = request.POST.get('title', '').strip()
            date_str = request.POST.get('date', '').strip()
            g_date = parse_jalali_to_gregorian(date_str)
            
            if title and g_date:
                Holiday.objects.get_or_create(
                    date=g_date,
                    defaults={'title': title, 'is_deleted': False}
                )
            return redirect('planning_config')

        # 3. Delete Holiday
        elif action == 'delete_holiday':
            holiday_id = request.POST.get('holiday_id')
            if holiday_id:
                Holiday.objects.filter(pk=holiday_id).update(is_deleted=True)
            return redirect('planning_config')

        return redirect('planning_config')


class ExportPlanningExcelView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request):
        plans = JobRecruitmentPlan.objects.filter(
            is_deleted=False,
            job__is_deleted=False
        ).exclude(
            job__status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED, JobOpportunity.STATUS_SUSPENDED]
        ).prefetch_related(
            'job', 'stage_plans', 'stage_plans__stage'
        ).order_by('-created_at')

        headers = [
            "شناسه فرصت شغلی", "عنوان شغل", "کد شغل", "دپارتمان", "ظرفیت جذب (Headcount)",
            "تاریخ شروع فرآیند", "تاریخ پیش‌بینی شده اتمام", "وضعیت برنامه", "مراحل و زمان‌بندی جذب"
        ]

        rows = []
        for plan in plans:
            stage_plans = plan.stage_plans.filter(is_deleted=False).order_by('stage__sequence')
            stages_list = []
            for sp in stage_plans:
                stages_list.append(
                    f"{sp.stage.name} ({to_jalali_string(sp.planned_start_date)} تا {to_jalali_string(sp.planned_end_date)} - SLA: {sp.sla_days} روز)"
                )
            stages_str = " ➔ ".join(stages_list)

            rows.append([
                plan.job.id,
                plan.job.title,
                plan.job.code or "",
                plan.job.department or "",
                plan.job.headcount,
                to_jalali_string(plan.start_date),
                to_jalali_string(plan.predicted_end_date),
                plan.get_status_display(),
                stages_str
            ])

        from apps.core.utils import export_to_excel_response
        return export_to_excel_response("recruitment_planning_report.xlsx", headers, rows)


class PlanningCalendarView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request):
        today = datetime.date.today()
        j_today = jdatetime.date.fromgregorian(date=today)
        
        try:
            year = int(request.GET.get('year', j_today.year))
            month = int(request.GET.get('month', j_today.month))
        except (ValueError, TypeError):
            year = j_today.year
            month = j_today.month

        JALALI_MONTH_NAMES = [
            "", "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
            "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
        ]
        
        current_month_name = f"{JALALI_MONTH_NAMES[month]} {year}"
        
        # Calculate prev and next months
        prev_month = month - 1
        prev_year = year
        if prev_month < 1:
            prev_month = 12
            prev_year -= 1
            
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year += 1
            
        g_start, g_end = get_jalali_month_range(year, month)
        
        # Fetch active stage plans in this range
        stage_plans = JobStagePlan.objects.filter(
            plan__status=JobRecruitmentPlan.STATUS_ACTIVE,
            plan__is_deleted=False,
            plan__job__is_deleted=False,
            is_deleted=False,
            planned_start_date__lte=g_end,
            planned_end_date__gte=g_start
        ).exclude(
            plan__job__status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED, JobOpportunity.STATUS_SUSPENDED]
        ).select_related('plan__job', 'stage')
        
        # Fetch holidays in this range
        holidays = Holiday.objects.filter(
            is_deleted=False,
            date__range=(g_start, g_end)
        )
        holiday_dict = {h.date: h.title for h in holidays}
        
        # Build month grid
        if month <= 6:
            num_days = 31
        elif month <= 11:
            num_days = 30
        else:
            try:
                jdatetime.date(year, 12, 30)
                num_days = 30
            except ValueError:
                num_days = 29
                
        days = []
        first_day_date = jdatetime.date(year, month, 1)
        start_weekday = first_day_date.weekday()
        
        # Pad beginning
        for _ in range(start_weekday):
            days.append(None)
            
        # Add actual days
        for day in range(1, num_days + 1):
            g_date = jdatetime.date(year, month, day).togregorian()
            is_holiday = (g_date.weekday() == 4) or (g_date in holiday_dict)
            holiday_title = "جمعه" if g_date.weekday() == 4 else holiday_dict.get(g_date, "")
            
            day_events = []
            for sp in stage_plans:
                if sp.planned_start_date == g_date:
                    day_events.append({
                        'type': 'START',
                        'label': f"شروع {sp.stage.name}",
                        'job_title': sp.plan.job.title,
                        'color': 'success',
                        'job_id': sp.plan.job.id,
                    })
                if sp.planned_end_date == g_date:
                    day_events.append({
                        'type': 'END',
                        'label': f"پایان {sp.stage.name}",
                        'job_title': sp.plan.job.title,
                        'color': 'danger',
                        'job_id': sp.plan.job.id,
                    })
            
            days.append({
                'day': day,
                'date': g_date,
                'is_today': g_date == today,
                'is_holiday': is_holiday,
                'holiday_title': holiday_title,
                'events': day_events
            })
            
        # Pad end
        while len(days) % 7 != 0:
            days.append(None)
            
        # Group into weeks
        weeks = [days[i:i+7] for i in range(0, len(days), 7)]
        
        context = {
            'current_month_name': current_month_name,
            'prev_year': prev_year,
            'prev_month': prev_month,
            'next_year': next_year,
            'next_month': next_month,
            'selected_year': year,
            'selected_month': month,
            'weeks': weeks,
            'today_jalali': to_jalali_string(today),
        }
        return render(request, 'recruitment_planning/calendar.html', context)


class ExportWeeklyAgendaExcelView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request):
        today = datetime.date.today()
        
        headers = [
            "تاریخ شمسی", "روز هفته", "نوع رویداد", "عنوان شغل", "مرحله ارزیابی", "نوع مرحله"
        ]
        
        rows = []
        for i in range(7):
            target_date = today + datetime.timedelta(days=i)
            j_date = jdatetime.date.fromgregorian(date=target_date)
            date_label = f"{j_date.year:04d}/{j_date.month:02d}/{j_date.day:02d}"
            
            weekdays = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یک‌شنبه"]
            day_name = weekdays[target_date.weekday()]
            
            starts = JobStagePlan.objects.filter(
                planned_start_date=target_date,
                plan__status=JobRecruitmentPlan.STATUS_ACTIVE,
                plan__is_deleted=False,
                plan__job__is_deleted=False,
                is_deleted=False
            ).exclude(
                plan__job__status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED, JobOpportunity.STATUS_SUSPENDED]
            ).select_related('plan__job', 'stage')

            ends = JobStagePlan.objects.filter(
                planned_end_date=target_date,
                plan__status=JobRecruitmentPlan.STATUS_ACTIVE,
                plan__is_deleted=False,
                plan__job__is_deleted=False,
                is_deleted=False
            ).exclude(
                plan__job__status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED, JobOpportunity.STATUS_SUSPENDED]
            ).select_related('plan__job', 'stage')

            for sp in starts:
                rows.append([
                    date_label,
                    day_name,
                    "شروع مرحله",
                    sp.plan.job.title,
                    sp.stage.name,
                    sp.get_stage_type_display()
                ])
                
            for sp in ends:
                rows.append([
                    date_label,
                    day_name,
                    "پایان مرحله",
                    sp.plan.job.title,
                    sp.stage.name,
                    sp.get_stage_type_display()
                ])

        from apps.core.utils import export_to_excel_response
        return export_to_excel_response("weekly_agenda_report.xlsx", headers, rows)


class WeeklyAgendaPrintView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request):
        today = datetime.date.today()
        
        JALALI_MONTH_NAMES = [
            "", "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
            "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
        ]
        
        start_jalali = to_jalali_string(today)
        end_date = today + datetime.timedelta(days=6)
        end_jalali = to_jalali_string(end_date)
        
        agenda_events = []
        for i in range(7):
            target_date = today + datetime.timedelta(days=i)
            j_date = jdatetime.date.fromgregorian(date=target_date)
            date_label = f"{JALALI_MONTH_NAMES[j_date.month]} {j_date.day}"
            
            weekdays = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یک‌شنبه"]
            day_name = weekdays[target_date.weekday()]
            
            starts = JobStagePlan.objects.filter(
                planned_start_date=target_date,
                plan__status=JobRecruitmentPlan.STATUS_ACTIVE,
                plan__is_deleted=False,
                plan__job__is_deleted=False,
                is_deleted=False
            ).exclude(
                plan__job__status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED, JobOpportunity.STATUS_SUSPENDED]
            ).select_related('plan__job', 'stage')

            ends = JobStagePlan.objects.filter(
                planned_end_date=target_date,
                plan__status=JobRecruitmentPlan.STATUS_ACTIVE,
                plan__is_deleted=False,
                plan__job__is_deleted=False,
                is_deleted=False
            ).exclude(
                plan__job__status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED, JobOpportunity.STATUS_SUSPENDED]
            ).select_related('plan__job', 'stage')

            events = []
            for sp in starts:
                events.append({
                    'type': 'START',
                    'job_title': sp.plan.job.title,
                    'stage_name': sp.stage.name,
                    'stage_type_display': sp.get_stage_type_display(),
                })
            for sp in ends:
                events.append({
                    'type': 'END',
                    'job_title': sp.plan.job.title,
                    'stage_name': sp.stage.name,
                    'stage_type_display': sp.get_stage_type_display(),
                })

            if events:
                agenda_events.append({
                    'date': target_date,
                    'jalali_str': f"{day_name} ({date_label})",
                    'events': events
                })
                
        context = {
            'agenda_events': agenda_events,
            'start_jalali': start_jalali,
            'end_jalali': end_jalali,
            'today_jalali': to_jalali_string(today),
        }
        return render(request, 'recruitment_planning/agenda_print.html', context)


class JobPlanningSuggestionsView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request, job_id):
        from django.db.models import Sum
        job = get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)
        
        # 1. Monthly capacity statistics for the current month and the next 5 months
        today_j = jdatetime.date.today()
        year = today_j.year
        month = today_j.month
        
        persian_months = ["", "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
        labels = {
            'SCREENING': 'غربالگری اولیه',
            'EXAM': 'آزمون کتبی/عملی',
            'SKILL_TEST': 'آزمون مهارتی',
            'INTERVIEW': 'مصاحبه حضوری',
            'ASSESSMENT': 'کانون ارزیابی'
        }
        
        configs = {c.stage_type: c for c in StageTypeConfiguration.objects.filter(is_deleted=False)}
        
        months_to_analyze = []
        curr_y, curr_m = year, month
        for _ in range(6):
            months_to_analyze.append((curr_y, curr_m))
            curr_m += 1
            if curr_m > 12:
                curr_m = 1
                curr_y += 1
                
        month_capacity = []
        for y, m in months_to_analyze:
            g_start, g_end = get_jalali_month_range(y, m)
            stages_data = []
            for stype in ['SCREENING', 'EXAM', 'SKILL_TEST', 'INTERVIEW', 'ASSESSMENT']:
                from .utils import get_consumed_capacity
                consumed = get_consumed_capacity(stype, g_start, g_end, y, m, exclude_job=job)
                
                config = configs.get(stype)
                limit = config.monthly_capacity if config else 100
                remaining = max(0, limit - consumed)
                percentage = round((consumed / limit) * 100, 1) if limit > 0 else 0
                
                stages_data.append({
                    'type': stype,
                    'label': labels.get(stype, stype),
                    'consumed': consumed,
                    'limit': limit,
                    'remaining': remaining,
                    'percentage': percentage
                })
            
            month_capacity.append({
                'label': f"{persian_months[m]} {y}",
                'stages': stages_data
            })
            
        # 2. Simulate start dates to suggest best dates
        holidays_set = set(Holiday.objects.filter(is_deleted=False).values_list('date', flat=True))
        suggestions = []
        start_sim_date = datetime.date.today() + datetime.timedelta(days=1)
        
        for i in range(45):
            candidate_date = start_sim_date + datetime.timedelta(days=i)
            # Skip Fridays and holidays
            if candidate_date.weekday() == 4 or candidate_date in holidays_set:
                continue
                
            schedule = calculate_recruitment_schedule(job, candidate_date)
            if not schedule:
                continue
                
            shifted_count = sum(1 for s in schedule if s.get('capacity_shifted', False))
            end_date = schedule[-1]['planned_end_date']
            total_duration = (end_date - candidate_date).days
            
            suggestions.append({
                'start_date_gregorian': candidate_date,
                'start_date_jalali': to_jalali_string(candidate_date),
                'end_date_jalali': to_jalali_string(end_date),
                'duration_days': total_duration,
                'shifted_count': shifted_count,
            })
            
        suggestions.sort(key=lambda x: (x['shifted_count'], x['start_date_gregorian']))
        best_suggestions = suggestions[:3]
        
        context = {
            'job': job,
            'best_suggestions': best_suggestions,
            'month_capacity': month_capacity
        }
        return render(request, 'recruitment_planning/partials/date_suggestions.html', context)


class SlaDelaysDashboardView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request):
        from datetime import datetime
        from django.utils import timezone
        from django.db.models import Q, Count
        from apps.candidates.models import JobApplication, ApplicationStageState
        from .models import JobStagePlan, StageTypeConfiguration
        
        # 1. فیلترها و جستجو
        search_query = request.GET.get('q', '').strip()
        unit_filter = request.GET.get('unit', '').strip()
        priority_filter = request.GET.get('priority', '').strip()
        
        # دریافت متقاضیان فعال در جریان ارزیابی فعال
        apps = JobApplication.objects.filter(
            status=JobApplication.STATUS_IN_PROGRESS,
            is_deleted=False,
            job__is_deleted=False
        ).exclude(job__status__in=['CLOSED', 'CANCELLED', 'SUSPENDED']).select_related('candidate', 'job')
        
        if search_query:
            apps = apps.filter(
                Q(candidate__first_name__icontains=search_query) |
                Q(candidate__last_name__icontains=search_query) |
                Q(candidate__national_id__icontains=search_query) |
                Q(job__title__icontains=search_query) |
                Q(job__request_number__icontains=search_query)
            )
            
        if unit_filter:
            apps = apps.filter(job__unit=unit_filter)
            
        # تفکیک آمار به ازای فرصت شغلی
        job_groups = {}
        total_delayed_count = 0
        total_active_count = 0
        total_critical_jobs = 0
        total_delay_days_sum = 0
        
        STAGE_TYPE_LABELS = {
            'EXAM':      'آزمون کتبی',
            'INTERVIEW': 'مصاحبه حضوری',
            'SKILL_TEST':'آزمون مهارتی',
            'ASSESSMENT':'کانون ارزیابی',
        }
        
        for app in apps:
            total_active_count += 1
            job = app.job
            
            # پیدا کردن مرحله ارزیابی متناظر با وضعیت شغل
            stage = job.stages.filter(stage_type=job.status, is_deleted=False).first()
            if not stage:
                stage = app.current_stage or job.stages.filter(is_deleted=False).order_by('sequence').first()
            
            if not stage:
                continue
                
            # دریافت تعداد روزهای مجاز طبق SLA
            stage_plan = JobStagePlan.objects.filter(
                plan__job=job,
                stage=stage,
                plan__is_deleted=False,
                is_deleted=False
            ).first()
            if stage_plan:
                sla_days = stage_plan.sla_days
            else:
                config = StageTypeConfiguration.objects.filter(
                    stage_type=stage.stage_type,
                    is_deleted=False
                ).first()
                sla_days = config.default_sla_days if config else 5
                
            # تعیین تاریخ شروع حضور در مرحله فعلی
            active_since = None
            if stage.sequence == 1:
                if job.start_date:
                    active_since = timezone.make_aware(datetime.combine(job.start_date, datetime.min.time()))
                else:
                    active_since = app.created_at
            else:
                prev_state = app.stage_states.filter(
                    stage__sequence__lt=stage.sequence,
                    status__in=['COMPLETED', 'FAILED'],
                    is_deleted=False
                ).order_by('-stage__sequence').first()
                
                if prev_state:
                    if prev_state.evaluation_date:
                        active_since = timezone.make_aware(datetime.combine(prev_state.evaluation_date, datetime.min.time()))
                      # convert datetime.date to datetime
                        active_since = timezone.make_aware(datetime.combine(prev_state.evaluation_date, datetime.min.time()))
                    else:
                        active_since = prev_state.updated_at
                else:
                    if job.start_date:
                        active_since = timezone.make_aware(datetime.combine(job.start_date, datetime.min.time()))
                    else:
                        active_since = app.created_at
                        
            if active_since:
                days_waiting = (timezone.now() - active_since).days
                is_delayed = days_waiting > sla_days
                overdue_days = max(0, days_waiting - sla_days)
                
                # اولویت تأخیر
                priority = 'ON_TRACK'
                priority_label = 'بدون تاخیر'
                if is_delayed:
                    if overdue_days > 30:
                        priority = 'CRITICAL'
                        priority_label = 'بیشتر از ۳۰ روز'
                    elif overdue_days >= 10:
                        priority = 'HIGH'
                        priority_label = '۱۰ تا ۳۰ روز'
                    else:
                        priority = 'MEDIUM'
                        priority_label = 'زیر ۱۰ روز'
                        
                # ساخت داده کاندیدا
                cand_data = {
                    'app_id': app.id,
                    'candidate': app.candidate,
                    'stage_name': STAGE_TYPE_LABELS.get(stage.stage_type, stage.name),
                    'active_since': active_since,
                    'days_waiting': days_waiting,
                    'sla_days': sla_days,
                    'overdue_days': overdue_days,
                    'is_delayed': is_delayed,
                    'priority': priority,
                    'priority_label': priority_label
                }
                
                # اضافه کردن به گروه‌بندی فرصت شغلی
                if job.id not in job_groups:
                    job_groups[job.id] = {
                        'job': job,
                        'delayed_candidates': [],
                        'all_candidates_count': 0,
                        'delayed_count': 0,
                        'max_delay': 0,
                        'avg_delay': 0,
                        'priority': 'ON_TRACK',
                        'priority_label': 'عادی',
                        'priority_order': 0,
                    }
                    
                job_groups[job.id]['all_candidates_count'] += 1
                
                if is_delayed:
                    job_groups[job.id]['delayed_candidates'].append(cand_data)
                    job_groups[job.id]['delayed_count'] += 1
                    total_delayed_count += 1
                    total_delay_days_sum += overdue_days
                    
                    if overdue_days > job_groups[job.id]['max_delay']:
                        job_groups[job.id]['max_delay'] = overdue_days
                        
                    # تعیین اولویت کلی شغل بر اساس بالاترین اولویت کاندیداها
                    p_order_map = {'ON_TRACK': 0, 'MEDIUM': 1, 'HIGH': 2, 'CRITICAL': 3}
                    curr_p = job_groups[job.id]['priority']
                    if p_order_map[priority] > p_order_map[curr_p]:
                        job_groups[job.id]['priority'] = priority
                        job_groups[job.id]['priority_label'] = priority_label
                        job_groups[job.id]['priority_order'] = p_order_map[priority]
        
        # محاسبه میانگین تاخیرها برای هر شغل
        for j_id, j_data in job_groups.items():
            if j_data['delayed_count'] > 0:
                total_delays = sum(c['overdue_days'] for c in j_data['delayed_candidates'])
                j_data['avg_delay'] = round(total_delays / j_data['delayed_count'], 1)
            if j_data['priority'] == 'CRITICAL':
                total_critical_jobs += 1
                
        # تبدیل به لیست و اعمال فیلتر اولویت و مرتب‌سازی
        jobs_list = list(job_groups.values())
        
        # فیلتر بر اساس اولویت کلی شغل در صورت انتخاب
        if priority_filter:
            jobs_list = [j for j in jobs_list if j['priority'] == priority_filter]
        else:
            # اگر فیلتر اولویت فعال نباشد، پیش‌فرض مشاغلی که کاندیدای تاخیردار دارند را نشان می‌دهیم
            # مگر اینکه کاربر جستجوی خاصی کرده باشد
            if not search_query and not unit_filter:
                # فقط مشاغلی که حداقل یک متقاضی تاخیردار دارند
                jobs_list = [j for j in jobs_list if j['delayed_count'] > 0]
                
        # مرتب‌سازی: بر اساس رتبه اولویت نزولی و سپس بیشترین تاخیر
        jobs_list.sort(key=lambda x: (-x['priority_order'], -x['max_delay']))
        
        # دریافت واحدهای سازمانی متمایز جهت فیلتر کشویی
        units = list(JobOpportunity.objects.filter(is_deleted=False).exclude(
            status__in=['CLOSED', 'CANCELLED', 'SUSPENDED']
        ).exclude(unit='').exclude(unit=None).values_list('unit', flat=True).order_by().distinct())
        
        # میانگین کل روزهای تاخیر متقاضیان تاخیردار
        avg_total_delay = round(total_delay_days_sum / total_delayed_count, 1) if total_delayed_count > 0 else 0
        
        context = {
            'jobs_list': jobs_list,
            'units': units,
            'selected_unit': unit_filter,
            'selected_priority': priority_filter,
            'search_query': search_query,
            'total_active_count': total_active_count,
            'total_delayed_count': total_delayed_count,
            'total_critical_jobs': total_critical_jobs,
            'avg_total_delay': avg_total_delay,
        }
        return render(request, 'recruitment_planning/sla_delays.html', context)


class OverlapMonitorView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request):
        from datetime import date
        from apps.candidates.models import JobApplication, Candidate
        from apps.jobs.models import JobOpportunity
        from .models import JobStagePlan
        
        STAGE_TYPE_LABELS = {
            'EXAM':      'آزمون کتبی',
            'INTERVIEW': 'مصاحبه حضوری',
            'SKILL_TEST':'آزمون مهارتی',
            'ASSESSMENT':'کانون ارزیابی',
        }
        
        # ۱. فیلتر همزمانی بر اساس نوع مرحله
        selected_stage_type = request.GET.get('stage_type', 'ASSESSMENT')
        
        # پیدا کردن کاندیداهای فعال در جریان ارزیابی فعال
        active_apps = JobApplication.objects.filter(
            status=JobApplication.STATUS_IN_PROGRESS,
            is_deleted=False,
            job__is_deleted=False
        ).exclude(job__status__in=['CLOSED', 'CANCELLED', 'SUSPENDED']).select_related('candidate', 'job')
        
        same_stage_candidates = []
        for app in active_apps:
            job = app.job
            stage = job.stages.filter(stage_type=job.status, is_deleted=False).first()
            if not stage:
                stage = app.current_stage or job.stages.filter(is_deleted=False).order_by('sequence').first()
            
            if stage and stage.stage_type == selected_stage_type:
                stage_plan = JobStagePlan.objects.filter(
                    plan__job=job,
                    stage=stage,
                    plan__is_deleted=False,
                    is_deleted=False
                ).first()
                
                same_stage_candidates.append({
                    'candidate': app.candidate,
                    'job': job,
                    'stage': stage,
                    'planned_start_date': stage_plan.planned_start_date if stage_plan else None,
                    'planned_end_date': stage_plan.planned_end_date if stage_plan else None,
                })
        
        # مرتب‌سازی بر اساس تاریخ شروع زمان‌بندی
        same_stage_candidates.sort(key=lambda x: x['planned_start_date'] or date.max)
        
        # ۲. تداخل‌های زمانی متقاضیان (مراحل فعال کاندیداهای چندگزینه‌ای که بازه‌های همپوشانی دارند)
        from django.db.models import Count
        candidates_with_multiple_apps = Candidate.objects.filter(
            is_deleted=False,
            applications__status=JobApplication.STATUS_IN_PROGRESS,
            applications__is_deleted=False
        ).annotate(active_apps_count=Count('applications')).filter(active_apps_count__gt=1)
        
        conflicts = []
        for candidate in candidates_with_multiple_apps:
            cand_apps = JobApplication.objects.filter(
                candidate=candidate,
                status=JobApplication.STATUS_IN_PROGRESS,
                is_deleted=False
            ).exclude(job__status__in=['CLOSED', 'CANCELLED', 'SUSPENDED']).select_related('job')
            
            active_stages_schedules = []
            for app in cand_apps:
                job = app.job
                stage = job.stages.filter(stage_type=job.status, is_deleted=False).first()
                if not stage:
                    stage = app.current_stage or job.stages.filter(is_deleted=False).order_by('sequence').first()
                
                if stage:
                    stage_plan = JobStagePlan.objects.filter(
                        plan__job=job,
                        stage=stage,
                        plan__is_deleted=False,
                        is_deleted=False
                    ).first()
                    
                    if stage_plan and stage_plan.planned_start_date and stage_plan.planned_end_date:
                        active_stages_schedules.append({
                            'app': app,
                            'job': job,
                            'stage': stage,
                            'start': stage_plan.planned_start_date,
                            'end': stage_plan.planned_end_date
                        })
            
            # بررسی تداخل‌ها
            n = len(active_stages_schedules)
            for i in range(n):
                for j in range(i + 1, n):
                    s1 = active_stages_schedules[i]
                    s2 = active_stages_schedules[j]
                    
                    max_start = max(s1['start'], s2['start'])
                    min_end = min(s1['end'], s2['end'])
                    
                    if max_start <= min_end:
                        overlap_days = (min_end - max_start).days + 1
                        conflicts.append({
                            'candidate': candidate,
                            'schedule1': s1,
                            'schedule2': s2,
                            'overlap_start': max_start,
                            'overlap_end': min_end,
                            'overlap_days': overlap_days,
                        })
                        
        context = {
            'selected_stage_type': selected_stage_type,
            'stage_type_choices': [
                ('EXAM', 'آزمون کتبی'),
                ('INTERVIEW', 'مصاحبه حضوری'),
                ('SKILL_TEST', 'آزمون مهارتی'),
                ('ASSESSMENT', 'کانون ارزیابی'),
            ],
            'same_stage_candidates': same_stage_candidates,
            'conflicts': conflicts,
            'STAGE_TYPE_LABELS': STAGE_TYPE_LABELS,
        }
        return render(request, 'recruitment_planning/conflicts.html', context)


class EditJobStagePlanView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request, job_id, stage_id):
        job = get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)
        stage = get_object_or_404(JobOpportunityStage, pk=stage_id, is_deleted=False)
        stage_plan = None
        if hasattr(job, 'recruitment_plan') and job.recruitment_plan and not job.recruitment_plan.is_deleted:
            stage_plan = job.recruitment_plan.stage_plans.filter(stage=stage, is_deleted=False).first()
        
        context = {
            'job': job,
            'stage': stage,
            'stage_plan': stage_plan,
        }
        return render(request, 'recruitment_planning/partials/stage_plan_edit.html', context)

    def post(self, request, job_id, stage_id):
        job = get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)
        stage = get_object_or_404(JobOpportunityStage, pk=stage_id, is_deleted=False)
        
        start_date_str = request.POST.get('planned_start_date', '').strip()
        end_date_str = request.POST.get('planned_end_date', '').strip()
        
        start_date = parse_jalali_to_gregorian(start_date_str)
        end_date = parse_jalali_to_gregorian(end_date_str)
        
        if not start_date or not end_date:
            return HttpResponse('<div class="text-danger text-xxs font-bold mt-1">فرمت تاریخ نامعتبر است.</div>', status=400)
            
        if start_date > end_date:
            return HttpResponse('<div class="text-danger text-xxs font-bold mt-1">تاریخ شروع باید قبل از پایان باشد.</div>', status=400)
            
        with transaction.atomic():
            # Create/Retrieve JobRecruitmentPlan
            plan = JobRecruitmentPlan.all_objects.filter(job=job).first()
            if plan:
                if plan.is_deleted:
                    plan.is_deleted = False
                    plan.status = JobRecruitmentPlan.STATUS_ACTIVE
                    plan.save()
            else:
                plan = JobRecruitmentPlan.objects.create(
                    job=job,
                    start_date=start_date,
                    predicted_end_date=end_date,
                    status=JobRecruitmentPlan.STATUS_ACTIVE
                )
            
            # Create/Retrieve JobStagePlan
            stage_plan = JobStagePlan.all_objects.filter(plan=plan, stage=stage).first()
            
            # Calculate sla_days based on working days between start_date and end_date
            holidays_set = set(Holiday.objects.filter(is_deleted=False).values_list('date', flat=True))
            current = start_date
            working_days = 0
            while current < end_date:
                current += datetime.timedelta(days=1)
                if current.weekday() == 4 or current in holidays_set:
                    continue
                working_days += 1
            
            if stage_plan:
                stage_plan.planned_start_date = start_date
                stage_plan.planned_end_date = end_date
                stage_plan.sla_days = working_days
                stage_plan.is_deleted = False
                stage_plan.save()
            else:
                stage_plan = JobStagePlan.objects.create(
                    plan=plan,
                    stage=stage,
                    stage_type=stage.stage_type or 'OTHER',
                    planned_start_date=start_date,
                    planned_end_date=end_date,
                    sla_days=working_days
                )
            
            # Proactively update candidate evaluation dates for consistency (excluding manually edited ones)
            states_to_update = ApplicationStageState.objects.filter(
                application__job=job,
                stage=stage,
                is_manually_edited=False,
                is_deleted=False
            )
            if states_to_update.exists():
                for state in states_to_update:
                    state.evaluation_date = end_date
                    state.save()

            # Update plan's overall start_date and predicted_end_date
            all_sps = plan.stage_plans.filter(is_deleted=False)
            if all_sps.exists():
                min_start = min(sp.planned_start_date for sp in all_sps)
                max_end = max(sp.planned_end_date for sp in all_sps)
                plan.start_date = min_start
                plan.predicted_end_date = max_end
                plan.save()
                
        context = {
            'job': job,
            'stage': stage,
            'stage_plan': stage_plan,
        }
        return render(request, 'recruitment_planning/partials/stage_plan_view.html', context)


class ViewJobStagePlanView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request, job_id, stage_id):
        job = get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)
        stage = get_object_or_404(JobOpportunityStage, pk=stage_id, is_deleted=False)
        stage_plan = None
        if hasattr(job, 'recruitment_plan') and job.recruitment_plan and not job.recruitment_plan.is_deleted:
            stage_plan = job.recruitment_plan.stage_plans.filter(stage=stage, is_deleted=False).first()
            
        context = {
            'job': job,
            'stage': stage,
            'stage_plan': stage_plan,
        }
        return render(request, 'recruitment_planning/partials/stage_plan_view.html', context)


class AnalyticsDashboardView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request):
        from apps.candidates.models import JobApplication, ApplicationStageState, Candidate
        from django.contrib.auth.models import User
        from django.db.models import Q, Count
        from django.utils import timezone
        from datetime import datetime
        import datetime as dt
        
        # Get list of all jobs for the dropdown filter
        jobs_list = JobOpportunity.objects.filter(is_deleted=False).order_by('title')
        
        selected_job_id = request.GET.get('job_id')
        selected_job = None
        if selected_job_id:
            try:
                selected_job = JobOpportunity.objects.get(id=int(selected_job_id), is_deleted=False)
            except (ValueError, TypeError, JobOpportunity.DoesNotExist):
                pass
                
        # 1. Conversion Funnel (قیف تبدیل)
        funnel_data = []
        if selected_job:
            # Funnel for specific job
            stages = sorted([s for s in selected_job.stages.all() if not s.is_deleted], key=lambda x: x.sequence)
            job_apps = JobApplication.objects.filter(job=selected_job, is_deleted=False).prefetch_related('stage_states', 'stage_states__stage')
            total_apps = job_apps.count()
            
            funnel_data.append({
                'stage_name': 'کل متقاضیان',
                'reached': total_apps,
                'passed': total_apps,
                'pass_rate': 100.0,
                'conversion_rate': 100.0
            })
            
            for stage in stages:
                reached_count = 0
                passed_count = 0
                for app in job_apps:
                    states_by_type = {s.stage.stage_type: s for s in app.stage_states.all() if not s.is_deleted}
                    
                    reached = True
                    prior_stages = [s for s in stages if s.sequence < stage.sequence]
                    for prior in prior_stages:
                        p_state = states_by_type.get(prior.stage_type)
                        if not p_state or (p_state.status != 'COMPLETED' and not p_state.is_conditional_pass):
                            reached = False
                            break
                            
                    if reached:
                        reached_count += 1
                        curr_state = states_by_type.get(stage.stage_type)
                        if curr_state and (curr_state.status == 'COMPLETED' or curr_state.is_conditional_pass):
                            passed_count += 1
                
                pass_rate = round((passed_count / reached_count) * 100, 1) if reached_count > 0 else 0.0
                conversion_rate = round((passed_count / total_apps) * 100, 1) if total_apps > 0 else 0.0
                
                funnel_data.append({
                    'stage_name': stage.name,
                    'reached': reached_count,
                    'passed': passed_count,
                    'pass_rate': pass_rate,
                    'conversion_rate': conversion_rate
                })
            
            # Now calculate final selection (جذب نهایی)
            reached_selected_count = 0
            passed_selected_count = 0
            for app in job_apps:
                states_by_type = {s.stage.stage_type: s for s in app.stage_states.all() if not s.is_deleted}
                reached_selected = True
                for s in stages:
                    s_state = states_by_type.get(s.stage_type)
                    if not s_state or (s_state.status != 'COMPLETED' and not s_state.is_conditional_pass):
                        reached_selected = False
                        break
                if reached_selected or app.status == 'SELECTED':
                    reached_selected_count += 1
                    if app.status == 'SELECTED':
                        passed_selected_count += 1
            
            pass_rate = round((passed_selected_count / reached_selected_count) * 100, 1) if reached_selected_count > 0 else 0.0
            conversion_rate = round((passed_selected_count / total_apps) * 100, 1) if total_apps > 0 else 0.0
            funnel_data.append({
                'stage_name': 'جذب نهایی',
                'reached': reached_selected_count,
                'passed': passed_selected_count,
                'pass_rate': pass_rate,
                'conversion_rate': conversion_rate
            })
        else:
            # Global funnel using standard stage types
            global_apps = JobApplication.objects.filter(is_deleted=False).select_related('job').prefetch_related('stage_states', 'stage_states__stage', 'job__stages')
            total_apps = global_apps.count()
            
            stats = {
                'SCREENING': {'reached': 0, 'passed': 0, 'name': 'غربالگری اولیه'},
                'EXAM': {'reached': 0, 'passed': 0, 'name': 'آزمون کتبی'},
                'SKILL_TEST': {'reached': 0, 'passed': 0, 'name': 'آزمون مهارتی'},
                'INTERVIEW': {'reached': 0, 'passed': 0, 'name': 'مصاحبه حضوری'},
                'ASSESSMENT': {'reached': 0, 'passed': 0, 'name': 'کانون ارزیابی'},
                'SELECTED': {'reached': 0, 'passed': 0, 'name': 'جذب نهایی'},
            }
            
            for app in global_apps:
                job = app.job
                if not job:
                    continue
                stages = sorted([s for s in job.stages.all() if not s.is_deleted], key=lambda x: x.sequence)
                states_by_type = {s.stage.stage_type: s for s in app.stage_states.all() if not s.is_deleted}
                
                # Check stages that exist in this job
                for stage in stages:
                    stype = stage.stage_type
                    if stype not in stats:
                        continue
                    
                    # A candidate reached this stage if all prior active stages of the job are completed
                    reached = True
                    prior_stages = [s for s in stages if s.sequence < stage.sequence]
                    for prior in prior_stages:
                        p_state = states_by_type.get(prior.stage_type)
                        if not p_state or (p_state.status != 'COMPLETED' and not p_state.is_conditional_pass):
                            reached = False
                            break
                            
                    if reached:
                        stats[stype]['reached'] += 1
                        curr_state = states_by_type.get(stype)
                        if curr_state and (curr_state.status == 'COMPLETED' or curr_state.is_conditional_pass):
                            stats[stype]['passed'] += 1
                
                # Check Selected
                reached_selected = True
                for s in stages:
                    s_state = states_by_type.get(s.stage_type)
                    if not s_state or (s_state.status != 'COMPLETED' and not s_state.is_conditional_pass):
                        reached_selected = False
                        break
                if reached_selected or app.status == 'SELECTED':
                    stats['SELECTED']['reached'] += 1
                    if app.status == 'SELECTED':
                        stats['SELECTED']['passed'] += 1
            
            funnel_data = [
                {
                    'stage_name': 'کل متقاضیان',
                    'reached': total_apps,
                    'passed': total_apps,
                    'pass_rate': 100.0,
                    'conversion_rate': 100.0
                }
            ]
            for key in ['SCREENING', 'EXAM', 'SKILL_TEST', 'INTERVIEW', 'ASSESSMENT', 'SELECTED']:
                s_info = stats[key]
                reached = s_info['reached']
                passed = s_info['passed']
                pass_rate = round((passed / reached) * 100, 1) if reached > 0 else 0.0
                conversion_rate = round((passed / total_apps) * 100, 1) if total_apps > 0 else 0.0
                funnel_data.append({
                    'stage_name': s_info['name'],
                    'reached': reached,
                    'passed': passed,
                    'pass_rate': pass_rate,
                    'conversion_rate': conversion_rate
                })

        # 2. Trend Chart (۶ ماه گذشته)
        today_j = jdatetime.date.today()
        trend_months = []
        y, m = today_j.year, today_j.month
        for _ in range(6):
            trend_months.append((y, m))
            m -= 1
            if m < 1:
                m = 12
                y -= 1
        trend_months.reverse()
        
        JALALI_MONTH_NAMES = ["", "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
        
        trend_labels = []
        applied_trend = []
        hired_trend = []
        rejected_trend = []
        
        for ty, tm in trend_months:
            trend_labels.append(f"{JALALI_MONTH_NAMES[tm]} {ty}")
            g_start, g_end = get_jalali_month_range(ty, tm)
            
            apps_cnt = JobApplication.objects.filter(created_at__date__range=(g_start, g_end), is_deleted=False).count()
            applied_trend.append(apps_cnt)
            
            hires_cnt = JobApplication.objects.filter(
                status='SELECTED',
                is_deleted=False
            ).filter(
                Q(admission_date__range=(g_start, g_end)) |
                Q(admission_date__isnull=True, updated_at__date__range=(g_start, g_end))
            ).count()
            hired_trend.append(hires_cnt)
            
            rej_cnt = JobApplication.objects.filter(
                status='REJECTED',
                is_deleted=False,
                updated_at__date__range=(g_start, g_end)
            ).count()
            rejected_trend.append(rej_cnt)
            
        # 3. Recruiter Performance (عملکرد کارشناسان)
        recruiters = User.objects.filter(profile__is_deleted=False).exclude(profile__role='CANDIDATE').select_related('profile')
        recruiter_stats = []
        
        from apps.recruitment_planning.models import JobStagePlan, StageTypeConfiguration
        
        for rec in recruiters:
            rec_jobs = JobOpportunity.objects.filter(assigned_recruiter=rec, is_deleted=False)
            total_jobs = rec_jobs.count()
            active_jobs = rec_jobs.exclude(status__in=['CLOSED', 'CANCELLED', 'SUSPENDED']).count()
            
            rec_apps = JobApplication.objects.filter(job__assigned_recruiter=rec, is_deleted=False)
            total_apps = rec_apps.count()
            hires_count = rec_apps.filter(status='SELECTED').count()
            
            closed_jobs = rec_jobs.filter(status='CLOSED')
            fill_times = []
            for j in closed_jobs:
                pub_date = j.start_date or j.created_at.date()
                selected_app = j.applications.filter(status='SELECTED', is_deleted=False).order_by('updated_at').first()
                if selected_app:
                    close_date = selected_app.updated_at.date()
                else:
                    close_date = j.updated_at.date()
                fill_times.append((close_date - pub_date).days)
            avg_time_to_fill = round(sum(fill_times) / len(fill_times), 1) if fill_times else None
            
            active_apps = rec_apps.filter(status='IN_PROGRESS').exclude(job__status__in=['CLOSED', 'CANCELLED', 'SUSPENDED']).select_related('job')
            total_active = active_apps.count()
            delayed_count = 0
            
            for app in active_apps:
                job = app.job
                stage = job.stages.filter(stage_type=job.status, is_deleted=False).first()
                if not stage:
                    stage = app.current_stage or job.stages.filter(is_deleted=False).order_by('sequence').first()
                if not stage:
                    continue
                    
                stage_plan = JobStagePlan.objects.filter(
                    plan__job=job,
                    stage=stage,
                    plan__is_deleted=False,
                    is_deleted=False
                ).first()
                if stage_plan:
                    sla_days = stage_plan.sla_days
                else:
                    config = StageTypeConfiguration.objects.filter(stage_type=stage.stage_type, is_deleted=False).first()
                    sla_days = config.default_sla_days if config else 5
                    
                active_since = None
                if stage.sequence == 1:
                    active_since = timezone.make_aware(datetime.combine(job.start_date, datetime.min.time())) if job.start_date else app.created_at
                else:
                    prev_state = app.stage_states.filter(
                        stage__sequence__lt=stage.sequence,
                        status__in=['COMPLETED', 'FAILED'],
                        is_deleted=False
                    ).order_by('-stage__sequence').first()
                    if prev_state:
                        active_since = timezone.make_aware(datetime.combine(prev_state.evaluation_date, datetime.min.time())) if prev_state.evaluation_date else prev_state.updated_at
                    else:
                        active_since = timezone.make_aware(datetime.combine(job.start_date, datetime.min.time())) if job.start_date else app.created_at
                
                if active_since:
                    days_waiting = (timezone.now() - active_since).days
                    if days_waiting > sla_days:
                        delayed_count += 1
                        
            sla_compliance = round(((total_active - delayed_count) / total_active) * 100, 1) if total_active > 0 else 100.0
            
            recruiter_stats.append({
                'recruiter': rec,
                'name': rec.get_full_name() or rec.username,
                'total_jobs': total_jobs,
                'active_jobs': active_jobs,
                'total_apps': total_apps,
                'hires_count': hires_count,
                'avg_time_to_fill': avg_time_to_fill if avg_time_to_fill is not None else '-',
                'sla_compliance': sla_compliance
            })

        # 4. Score Distribution (توزیع نمرات)
        stage_types = [
            ('EXAM', 'آزمون کتبی'),
            ('SKILL_TEST', 'آزمون مهارتی'),
            ('INTERVIEW', 'مصاحبه حضوری'),
            ('ASSESSMENT', 'کانون ارزیابی')
        ]
        score_distributions = {}
        for code, label in stage_types:
            states = ApplicationStageState.objects.filter(
                stage__stage_type=code,
                score__gt=0,
                is_deleted=False
            )
            if code == 'ASSESSMENT':
                buckets = [0, 0, 0, 0]
                labels = ["0-40", "40-50", "50-60", "۶۰ به بالا"]
                colors = [
                    'rgba(239, 68, 68, 0.7)',  # 0-40
                    'rgba(245, 158, 11, 0.7)', # 40-50
                    'rgba(245, 158, 11, 0.7)', # 50-60
                    'rgba(16, 185, 129, 0.8)'  # Above 60
                ]
                borders = [
                    '#ef4444',
                    '#f59e0b',
                    '#f59e0b',
                    '#10b981'
                ]
                for state in states:
                    val = state.score
                    if val < 40:
                        buckets[0] += 1
                    elif val < 50:
                        buckets[1] += 1
                    elif val < 60:
                        buckets[2] += 1
                    else:
                        buckets[3] += 1
            else:
                buckets = [0, 0, 0, 0, 0, 0]
                labels = ["0-50", "50-60", "60-70", "70-80", "80-90", "90-100"]
                colors = [
                    'rgba(239, 68, 68, 0.7)',  # 0-50
                    'rgba(245, 158, 11, 0.7)', # 50-60
                    'rgba(79, 70, 229, 0.8)',  # 60-70
                    'rgba(79, 70, 229, 0.8)',  # 70-80
                    'rgba(79, 70, 229, 0.8)',  # 80-90
                    'rgba(16, 185, 129, 0.8)'  # 90-100
                ]
                borders = [
                    '#ef4444',
                    '#f59e0b',
                    '#4f46e5',
                    '#4f46e5',
                    '#4f46e5',
                    '#10b981'
                ]
                for state in states:
                    val = state.score
                    if val < 50:
                        buckets[0] += 1
                    elif val < 60:
                        buckets[1] += 1
                    elif val < 70:
                        buckets[2] += 1
                    elif val < 80:
                        buckets[3] += 1
                    elif val < 90:
                        buckets[4] += 1
                    else:
                        buckets[5] += 1

            score_distributions[code] = {
                'label': label,
                'data': buckets,
                'labels': labels,
                'colors': colors,
                'borders': borders,
                'total_scores': sum(buckets)
            }

        # ۵. گزارش اعلانات ارسالی (ایمیل و پیامک)
        from apps.candidates.models import NotificationLog
        from django.core.paginator import Paginator
        
        log_type = request.GET.get('log_type', '')
        log_status = request.GET.get('log_status', '')
        log_q = request.GET.get('log_q', '')
        
        logs_query = NotificationLog.objects.filter(is_deleted=False)
        if log_type in ['SMS', 'EMAIL']:
            logs_query = logs_query.filter(notification_type=log_type)
        if log_status in ['SENT', 'FAILED']:
            logs_query = logs_query.filter(status=log_status)
        if log_q:
            logs_query = logs_query.filter(
                Q(recipient__icontains=log_q) |
                Q(subject__icontains=log_q) |
                Q(body__icontains=log_q) |
                Q(error_message__icontains=log_q)
            )
            
        paginator = Paginator(logs_query, 20)  # ۲۰ لاگ در هر صفحه
        page_number = request.GET.get('page', 1)
        log_page_obj = paginator.get_page(page_number)

        completed_trend = [h + r for h, r in zip(hired_trend, rejected_trend)]

        context = {
            'jobs_list': jobs_list,
            'selected_job': selected_job,
            'funnel_data': funnel_data,
            'trend_labels': trend_labels,
            'applied_trend': applied_trend,
            'hired_trend': hired_trend,
            'rejected_trend': rejected_trend,
            'completed_trend': completed_trend,
            'recruiter_stats': recruiter_stats,
            'score_distributions': score_distributions,
            
            # متغیرهای مربوط به تب اعلانات
            'log_page_obj': log_page_obj,
            'log_type': log_type,
            'log_status': log_status,
            'log_q': log_q,
            'active_tab': request.GET.get('tab', 'charts'),
        }
        return render(request, 'recruitment_planning/analytics.html', context)



