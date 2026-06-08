from django.urls import path
from .views import (
    PlanningDashboardView, JobPlanningView, PlanningConfigView, ExportPlanningExcelView,
    PlanningCalendarView, ExportWeeklyAgendaExcelView, WeeklyAgendaPrintView, JobPlanningSuggestionsView
)

urlpatterns = [
    path('dashboard/', PlanningDashboardView.as_view(), name='planning_dashboard'),
    path('job/<int:job_id>/', JobPlanningView.as_view(), name='job_planning'),
    path('job/<int:job_id>/suggestions/', JobPlanningSuggestionsView.as_view(), name='job_planning_suggestions'),
    path('config/', PlanningConfigView.as_view(), name='planning_config'),
    path('export/excel/', ExportPlanningExcelView.as_view(), name='planning_export_excel'),
    path('calendar/', PlanningCalendarView.as_view(), name='planning_calendar'),
    path('export/weekly/', ExportWeeklyAgendaExcelView.as_view(), name='planning_agenda_export_excel'),
    path('agenda/print/', WeeklyAgendaPrintView.as_view(), name='planning_agenda_print'),
]
