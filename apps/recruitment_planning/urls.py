from django.urls import path
from .views import (
    PlanningDashboardView, JobPlanningView, PlanningConfigView, ExportPlanningExcelView,
    PlanningCalendarView, ExportWeeklyAgendaExcelView, WeeklyAgendaPrintView, JobPlanningSuggestionsView,
    SlaDelaysDashboardView, OverlapMonitorView, EditJobStagePlanView, ViewJobStagePlanView
)

urlpatterns = [
    path('dashboard/', PlanningDashboardView.as_view(), name='planning_dashboard'),
    path('sla-delays/', SlaDelaysDashboardView.as_view(), name='sla_delays_dashboard'),
    path('job/<int:job_id>/', JobPlanningView.as_view(), name='job_planning'),
    path('job/<int:job_id>/suggestions/', JobPlanningSuggestionsView.as_view(), name='job_planning_suggestions'),
    path('config/', PlanningConfigView.as_view(), name='planning_config'),
    path('export/excel/', ExportPlanningExcelView.as_view(), name='planning_export_excel'),
    path('calendar/', PlanningCalendarView.as_view(), name='planning_calendar'),
    path('export/weekly/', ExportWeeklyAgendaExcelView.as_view(), name='planning_agenda_export_excel'),
    path('agenda/print/', WeeklyAgendaPrintView.as_view(), name='planning_agenda_print'),
    path('conflicts/', OverlapMonitorView.as_view(), name='planning_conflicts'),
    path('job/<int:job_id>/stage/<int:stage_id>/edit-plan/', EditJobStagePlanView.as_view(), name='edit_job_stage_plan'),
    path('job/<int:job_id>/stage/<int:stage_id>/view-plan/', ViewJobStagePlanView.as_view(), name='view_job_stage_plan'),
]
