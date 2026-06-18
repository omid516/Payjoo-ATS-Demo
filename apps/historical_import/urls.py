from django.urls import path
from .views import (
    UploadExcelView, MappingView, PreviewView, SuccessView, 
    RollbackScreeningView, FixSelectedCandidatesView,
    DownloadFixedTemplateView, FixedTemplateImportView,
    ResetDatabaseView
)

urlpatterns = [
    path('upload/', UploadExcelView.as_view(), name='import_upload'),
    path('mapping/<int:session_id>/', MappingView.as_view(), name='import_mapping'),
    path('preview/<int:session_id>/', PreviewView.as_view(), name='import_preview'),
    path('success/<int:session_id>/', SuccessView.as_view(), name='import_success'),
    path('rollback-screening/', RollbackScreeningView.as_view(), name='rollback_screening'),
    path('fix-selected-rejected/', FixSelectedCandidatesView.as_view(), name='fix_selected_rejected'),
    path('fixed-template/download/', DownloadFixedTemplateView.as_view(), name='download_fixed_template'),
    path('fixed-template/import/', FixedTemplateImportView.as_view(), name='fixed_template_import'),
    path('reset-db/', ResetDatabaseView.as_view(), name='reset_database'),
]

