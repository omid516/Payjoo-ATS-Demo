from django.contrib import admin
from .models import WorkflowTemplate, WorkflowStageTemplate, JobOpportunity, JobOpportunityStage, JobStageInterviewer, AssessmentCompetency

class WorkflowStageTemplateInline(admin.TabularInline):
    model = WorkflowStageTemplate
    extra = 1
    fields = ('name', 'default_weight', 'sequence')


@admin.register(WorkflowTemplate)
class WorkflowTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)
    inlines = [WorkflowStageTemplateInline]


class JobOpportunityStageInline(admin.TabularInline):
    model = JobOpportunityStage
    extra = 1
    fields = ('name', 'weight', 'sequence')


@admin.register(JobOpportunity)
class JobOpportunityAdmin(admin.ModelAdmin):
    list_display = ('title', 'code', 'request_number', 'department', 'unit', 'headcount', 'recruitment_type', 'assigned_recruiter', 'status', 'created_at')
    list_filter = ('status', 'department', 'recruitment_type')
    search_fields = ('title', 'code', 'request_number', 'department', 'unit')
    readonly_fields = ('created_at', 'updated_at', 'deleted_at')
    inlines = [JobOpportunityStageInline]


@admin.register(JobStageInterviewer)
class JobStageInterviewerAdmin(admin.ModelAdmin):
    list_display = ('job', 'stage', 'user', 'weight', 'group_name')
    list_filter = ('job', 'group_name')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'group_name')


@admin.register(AssessmentCompetency)
class AssessmentCompetencyAdmin(admin.ModelAdmin):
    list_display = ('stage', 'name', 'weight')
    list_filter = ('stage__job', 'stage')
    search_fields = ('name',)


from .models import CentralCompetency, JobOpportunityCompetency

@admin.register(CentralCompetency)
class CentralCompetencyAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'post_code', 'post_title', 'competency_type', 'importance', 'level', 'management_name')
    list_filter = ('competency_type', 'importance', 'level', 'management_name')
    search_fields = ('code', 'title', 'post_code', 'post_title')


@admin.register(JobOpportunityCompetency)
class JobOpportunityCompetencyAdmin(admin.ModelAdmin):
    list_display = ('job', 'code', 'title', 'competency_type', 'importance', 'level')
    list_filter = ('job', 'competency_type', 'importance', 'level')
    search_fields = ('code', 'title', 'job__title', 'job__code')
