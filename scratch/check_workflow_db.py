import os
import sys
import django

sys.path.insert(0, '/Users/omidsalehi/Desktop/ATS')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ats.settings')
django.setup()

from apps.jobs.models import WorkflowTemplate, WorkflowStageTemplate

total = WorkflowTemplate.objects.count()
active = WorkflowTemplate.objects.filter(is_deleted=False).count()
print(f"Total WorkflowTemplate: {total}")
print(f"Active WorkflowTemplate: {active}")

for wt in WorkflowTemplate.objects.filter(is_deleted=False):
    print(f"\nWorkflowTemplate ID: {wt.id}, Name: {wt.name}")
    for stage in wt.stages.filter(is_deleted=False):
        print(f"  Stage ID: {stage.id}, Name: {stage.name}, Type: {stage.stage_type}, Weight: {stage.default_weight}")
