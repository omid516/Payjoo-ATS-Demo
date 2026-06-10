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

        # Active plans
        active_plans = JobRecruitmentPlan.objects.filter(status=JobRecruitmentPlan.STATUS_ACTIVE, is_deleted=False)
        draft_plans = JobRecruitmentPlan.objects.filter(status=JobRecruitmentPlan.STATUS_DRAFT, is_deleted=False)
        
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
        stage_types = ['SCREENING', 'EXAM', 'SKILL_TEST', 'INTERVIEW', 'ASSESSMENT']
        capacity_stats = []
        configs = {c.stage_type: c for c in StageTypeConfiguration.objects.filter(is_deleted=False)}
        
        for stype in stage_types:
            config = configs.get(stype)
            capacity_limit = config.monthly_capacity if config else 100
            
            # Total headcount consuming this stage type in current month
            from django.db.models import Sum
            consumed = JobStagePlan.objects.filter(
                stage_type=stype,
                planned_end_date__range=(g_start, g_end),
                plan__status=JobRecruitmentPlan.STATUS_ACTIVE,
                plan__is_deleted=False,
                is_deleted=False
            ).aggregate(total=Sum('plan__job__headcount'))['total'] or 0
            
            remaining = max(0, capacity_limit - consumed)
            percentage = round((consumed / capacity_limit) * 100, 1) if capacity_limit > 0 else 0
            
            # Map type to Farsi label
            labels = {
                'SCREENING': 'غربالگری اولیه',
                'EXAM': 'آزمون کتبی',
                'SKILL_TEST': 'آزمون مهارتی',
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
            status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED]
        ).exclude(
            recruitment_plan__isnull=False
        )

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
                is_deleted=False
            ).select_related('plan__job', 'stage')

            ends = JobStagePlan.objects.filter(
                planned_end_date=target_date,
                plan__status=JobRecruitmentPlan.STATUS_ACTIVE,
                plan__is_deleted=False,
                is_deleted=False
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
        }
        return render(request, 'recruitment_planning/dashboard.html', context)


class JobPlanningView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_RECRUITMENT_DIRECTOR, UserProfile.ROLE_RECRUITMENT_SPECIALIST]

    def get(self, request, job_id):
        job = get_object_or_404(JobOpportunity, pk=job_id, is_deleted=False)
        plan = getattr(job, 'recruitment_plan', None)
        
        stages = job.stages.filter(is_deleted=False).order_by('sequence')
        
        context = {
            'job': job,
            'plan': plan,
            'stages': stages,
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

        # Generate schedule preview
        schedule = calculate_recruitment_schedule(job, start_date)
        
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
                    capacity_shifted=s['capacity_shifted']
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
        plans = JobRecruitmentPlan.objects.filter(is_deleted=False).prefetch_related(
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
            is_deleted=False,
            planned_start_date__lte=g_end,
            planned_end_date__gte=g_start
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
                is_deleted=False
            ).select_related('plan__job', 'stage')

            ends = JobStagePlan.objects.filter(
                planned_end_date=target_date,
                plan__status=JobRecruitmentPlan.STATUS_ACTIVE,
                plan__is_deleted=False,
                is_deleted=False
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
                is_deleted=False
            ).select_related('plan__job', 'stage')

            ends = JobStagePlan.objects.filter(
                planned_end_date=target_date,
                plan__status=JobRecruitmentPlan.STATUS_ACTIVE,
                plan__is_deleted=False,
                is_deleted=False
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
                consumed = JobStagePlan.objects.filter(
                    stage_type=stype,
                    planned_end_date__range=(g_start, g_end),
                    plan__is_deleted=False,
                    is_deleted=False
                ).aggregate(total=Sum('plan__job__headcount'))['total'] or 0
                
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
            is_deleted=False
        ).exclude(job__status__in=['CLOSED', 'CANCELLED']).select_related('candidate', 'job')
        
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
                priority_label = 'در جریان / عادی'
                if is_delayed:
                    if overdue_days > 10:
                        priority = 'CRITICAL'
                        priority_label = 'بحرانی'
                    elif overdue_days > 5:
                        priority = 'HIGH'
                        priority_label = 'بالا'
                      # overdue_days <= 5 and > 0
                    else:
                        priority = 'MEDIUM'
                        priority_label = 'متوسط'
                        
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
            status__in=['CLOSED', 'CANCELLED']
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



