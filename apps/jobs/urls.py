from django.urls import path
from .views import (
    JobOpportunityListView,
    JobOpportunityCreateView,
    JobOpportunityUpdateView,
    JobOpportunityDeleteView,
    WorkflowTemplateListView,
    WorkflowTemplateCreateView,
    WorkflowTemplateUpdateView,
    WorkflowTemplateDeleteView,
    ExportJobsExcelView,
    WorkflowStagesPreviewView,
    JobOpportunityPrintDocView,
    JobOpportunityBulkStatusView
)

urlpatterns = [
    path('', JobOpportunityListView.as_view(), name='job_list'),
    path('add/', JobOpportunityCreateView.as_view(), name='job_add'),
    path('<int:pk>/edit/', JobOpportunityUpdateView.as_view(), name='job_edit'),
    path('<int:pk>/delete/', JobOpportunityDeleteView.as_view(), name='job_delete'),
    path('<int:pk>/print/', JobOpportunityPrintDocView.as_view(), name='job_print_doc'),
    path('export/excel/', ExportJobsExcelView.as_view(), name='job_export_excel'),
    path('bulk-status-update/', JobOpportunityBulkStatusView.as_view(), name='job_bulk_status_update'),
    
    path('workflows/', WorkflowTemplateListView.as_view(), name='workflow_list'),
    path('workflows/add/', WorkflowTemplateCreateView.as_view(), name='workflow_add'),
    path('workflows/<int:pk>/edit/', WorkflowTemplateUpdateView.as_view(), name='workflow_edit'),
    path('workflows/<int:pk>/delete/', WorkflowTemplateDeleteView.as_view(), name='workflow_delete'),
    path('workflows/<int:pk>/stages/', WorkflowStagesPreviewView.as_view(), name='workflow_stages_preview'),
]
