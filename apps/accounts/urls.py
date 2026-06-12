from django.urls import path
from .views import (
    CustomLoginView, CustomLogoutView, UserListView, UserCreateView,
    UserUpdateView, UserDeleteView, AuditLogListView,
    SystemBackupView, DownloadBackupView, RestoreBackupView,
    SystemUpdateCheckView, SystemUpdateRunView, SystemHealthCheckView, SystemRestartView,
    SMSPanelDashboardView, JobStagesOptionsView, SMSCandidatesPreviewView, SMSExportExcelView,
    ExportUnitStatsExcelView
)

urlpatterns = [
    path('login/', CustomLoginView.as_view(), name='login'),
    path('logout/', CustomLogoutView.as_view(), name='logout'),
    path('users/', UserListView.as_view(), name='user_list'),
    path('users/add/', UserCreateView.as_view(), name='user_add'),
    path('users/<int:pk>/edit/', UserUpdateView.as_view(), name='user_edit'),
    path('users/<int:pk>/delete/', UserDeleteView.as_view(), name='user_delete'),
    path('audit-logs/', AuditLogListView.as_view(), name='audit_log_list'),
    path('system-backup/', SystemBackupView.as_view(), name='system_backup'),
    path('system-backup/download/', DownloadBackupView.as_view(), name='download_backup'),
    path('system-backup/restore/', RestoreBackupView.as_view(), name='restore_backup'),
    path('system-backup/update-check/', SystemUpdateCheckView.as_view(), name='system_update_check'),
    path('system-backup/update-run/', SystemUpdateRunView.as_view(), name='system_update_run'),
    path('system-backup/health/', SystemHealthCheckView.as_view(), name='system_health_check'),
    path('system-backup/restart/', SystemRestartView.as_view(), name='system_restart'),
    path('sms-panel/', SMSPanelDashboardView.as_view(), name='sms_panel'),
    path('sms-panel/stages/', JobStagesOptionsView.as_view(), name='sms_panel_stages'),
    path('sms-panel/preview/', SMSCandidatesPreviewView.as_view(), name='sms_panel_preview'),
    path('sms-panel/export/', SMSExportExcelView.as_view(), name='sms_panel_export'),
    path('dashboard/export-unit-stats/', ExportUnitStatsExcelView.as_view(), name='export_unit_stats'),
]

