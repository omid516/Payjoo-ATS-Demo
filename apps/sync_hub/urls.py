from django.urls import path
from . import views

app_name = 'sync_hub'

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('ping/', views.ping_server_view, name='ping_server'),
    path('export-upload/', views.export_and_upload_view, name='export_upload'),
    path('download-file/<str:package_id>/', views.download_package_file_view, name='download_file'),
    path('fetch-packages/', views.fetch_server_packages_view, name='fetch_packages'),
    path('preview-diff/', views.preview_diff_view, name='preview_diff'),
    path('apply-merge/', views.apply_merge_view, name='apply_merge'),
    path('batch-scan/', views.batch_scan_view, name='batch_scan'),
    path('batch-apply/', views.batch_apply_view, name='batch_apply'),
    path('settings/save/', views.save_settings_view, name='save_settings'),
]
