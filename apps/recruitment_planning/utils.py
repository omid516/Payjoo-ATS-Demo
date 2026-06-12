import datetime
import jdatetime
from django.db.models import Sum
from .models import Holiday, StageTypeConfiguration, JobStagePlan

def to_jalali_string(date_obj):
    if not date_obj:
        return ""
    j_date = jdatetime.date.fromgregorian(date=date_obj)
    return f"{j_date.year:04d}/{j_date.month:02d}/{j_date.day:02d}"

def parse_jalali_to_gregorian(val):
    if not val:
        return None
    try:
        parts = [int(p) for p in val.strip().split('/')]
        if len(parts) == 3:
            return jdatetime.date(parts[0], parts[1], parts[2]).togregorian()
    except Exception:
        pass
    return None

def add_working_days(start_date, days, holidays_set=None):
    if holidays_set is None:
        holidays_set = set(Holiday.objects.filter(is_deleted=False).values_list('date', flat=True))
    
    current_date = start_date
    added_days = 0
    while added_days < days:
        current_date += datetime.timedelta(days=1)
        # Friday is 4 (weekday() has Monday=0, Tuesday=1, Wednesday=2, Thursday=3, Friday=4, Saturday=5, Sunday=6)
        if current_date.weekday() == 4:
            continue
        if current_date in holidays_set:
            continue
        added_days += 1
    return current_date

def get_next_working_day(date_obj, holidays_set=None):
    if holidays_set is None:
        holidays_set = set(Holiday.objects.filter(is_deleted=False).values_list('date', flat=True))
    
    current_date = date_obj + datetime.timedelta(days=1)
    while current_date.weekday() == 4 or current_date in holidays_set:
        current_date += datetime.timedelta(days=1)
    return current_date

def get_jalali_month_range(year, month):
    g_start = jdatetime.date(year, month, 1).togregorian()
    if month < 12:
        g_end = (jdatetime.date(year, month + 1, 1) - datetime.timedelta(days=1)).togregorian()
    else:
        g_end = (jdatetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)).togregorian()
    return g_start, g_end

def calculate_recruitment_schedule(job, start_date, overrides=None):
    """
    Calculates stage-by-stage planned dates for a job opportunity based on SLAs and monthly capacities.
    Plans only from the current stage onwards. Accepts overrides dictionary to customize stage dates manually.
    """
    all_stages = list(job.stages.filter(is_deleted=False).order_by('sequence'))
    if not all_stages:
        return []

    current_stage = job.current_stage
    if not current_stage:
        current_stage = all_stages[0]

    holidays_set = set(Holiday.objects.filter(is_deleted=False).values_list('date', flat=True))
    
    # Pre-fetch configurations
    configs = {c.stage_type: c for c in StageTypeConfiguration.objects.filter(is_deleted=False)}
    
    schedule = []
    
    # 1. Past stages: Keep existing dates if available, otherwise set to start_date with sla_days=0
    plan = getattr(job, 'recruitment_plan', None)
    if plan and plan.is_deleted:
        plan = None

    for stage in all_stages:
        if stage.sequence < current_stage.sequence:
            existing_sp = None
            if plan:
                existing_sp = plan.stage_plans.filter(stage=stage, is_deleted=False).first()
            
            if existing_sp:
                p_start = existing_sp.planned_start_date
                p_end = existing_sp.planned_end_date
                sla = existing_sp.sla_days
                is_exact = existing_sp.is_exact
            else:
                p_start = start_date
                p_end = start_date
                sla = 0
                is_exact = False

            schedule.append({
                'stage': stage,
                'stage_type': stage.stage_type or 'OTHER',
                'planned_start_date': p_start,
                'planned_end_date': p_end,
                'sla_days': sla,
                'capacity_shifted': False,
                'capacity_limit': 100,
                'consumed_capacity': 0,
                'is_past': True,
                'is_exact': is_exact
            })

    # 2. Active stages: Plan starting from start_date
    current_start = start_date
    while current_start.weekday() == 4 or current_start in holidays_set:
        current_start += datetime.timedelta(days=1)

    for stage in all_stages:
        if stage.sequence >= current_stage.sequence:
            stage_type = stage.stage_type or 'OTHER'
            config = configs.get(stage_type)
            if config:
                sla_days = config.default_sla_days
                capacity_limit = config.monthly_capacity
            else:
                defaults = {
                    'SCREENING': 5,
                    'EXAM': 15,
                    'SKILL_TEST': 15,
                    'INTERVIEW': 10,
                    'ASSESSMENT': 15,
                    'OTHER': 5
                }
                sla_days = defaults.get(stage_type, 5)
                capacity_limit = 100

            # Determine if this stage is exact-day or a range
            is_exact = False
            if overrides and stage.id in overrides and 'is_exact' in overrides[stage.id]:
                is_exact = overrides[stage.id]['is_exact']
            elif plan:
                existing_sp = plan.stage_plans.filter(stage=stage, is_deleted=False).first()
                if existing_sp:
                    is_exact = existing_sp.is_exact
                else:
                    is_exact = True if stage_type in ['EXAM', 'INTERVIEW'] else False
            else:
                is_exact = True if stage_type in ['EXAM', 'INTERVIEW'] else False

            # Check if there are overridden dates for this stage
            has_override_dates = False
            override_start = None
            override_end = None
            if overrides and stage.id in overrides:
                override_start = overrides[stage.id].get('planned_start_date')
                override_end = overrides[stage.id].get('planned_end_date')
                if override_start:
                    has_override_dates = True

            if has_override_dates:
                planned_start = override_start
                if is_exact:
                    planned_end = planned_start
                else:
                    planned_end = override_end if override_end else add_working_days(planned_start, sla_days, holidays_set)
                
                capacity_shifted = False
                
                # Fetch consumed capacity for the month to display in preview
                j_end = jdatetime.date.fromgregorian(date=planned_end)
                g_month_start, g_month_end = get_jalali_month_range(j_end.year, j_end.month)
                consumed = JobStagePlan.objects.filter(
                    stage_type=stage_type,
                    planned_end_date__range=(g_month_start, g_month_end),
                    plan__is_deleted=False,
                    is_deleted=False
                ).exclude(plan__job=job).aggregate(total=Sum('plan__job__headcount'))['total'] or 0
            else:
                planned_start = current_start
                if is_exact:
                    planned_end = planned_start
                else:
                    planned_end = add_working_days(planned_start, sla_days, holidays_set)

                capacity_shifted = False
                
                # Capacity validation loop (only for non-overridden stages!)
                while True:
                    j_end = jdatetime.date.fromgregorian(date=planned_end)
                    g_month_start, g_month_end = get_jalali_month_range(j_end.year, j_end.month)
                    
                    consumed = JobStagePlan.objects.filter(
                        stage_type=stage_type,
                        planned_end_date__range=(g_month_start, g_month_end),
                        plan__is_deleted=False,
                        is_deleted=False
                    ).exclude(plan__job=job).aggregate(total=Sum('plan__job__headcount'))['total'] or 0
                    
                    if consumed + job.headcount <= capacity_limit:
                        break
                    
                    capacity_shifted = True
                    
                    next_j_year = j_end.year
                    next_j_month = j_end.month + 1
                    if next_j_month > 12:
                        next_j_month = 1
                        next_j_year += 1
                    
                    planned_start = jdatetime.date(next_j_year, next_j_month, 1).togregorian()
                    while planned_start.weekday() == 4 or planned_start in holidays_set:
                        planned_start += datetime.timedelta(days=1)
                        
                    if is_exact:
                        planned_end = planned_start
                    else:
                        planned_end = add_working_days(planned_start, sla_days, holidays_set)

            schedule.append({
                'stage': stage,
                'stage_type': stage_type,
                'planned_start_date': planned_start,
                'planned_end_date': planned_end,
                'sla_days': sla_days,
                'capacity_shifted': capacity_shifted,
                'capacity_limit': capacity_limit,
                'consumed_capacity': consumed,
                'is_past': False,
                'is_exact': is_exact
            })
            
            current_start = get_next_working_day(planned_end, holidays_set)

    return schedule

