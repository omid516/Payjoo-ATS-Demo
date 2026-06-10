from django.urls import path
from .views import UploadExcelView, MappingView, PreviewView, SuccessView

urlpatterns = [
    path('upload/', UploadExcelView.as_view(), name='import_upload'),
    path('mapping/<int:session_id>/', MappingView.as_view(), name='import_mapping'),
    path('preview/<int:session_id>/', PreviewView.as_view(), name='import_preview'),
    path('success/<int:session_id>/', SuccessView.as_view(), name='import_success'),
]
