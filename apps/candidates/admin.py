from django.contrib import admin
from .models import (
    Candidate, CandidateEducation, CandidateExperience, JobApplication, 
    ApplicationStageState, InterviewerScore, AssessorCompetencyScore, ExternalInterviewerScore,
    JobDefaultInterviewer
)

class CandidateEducationInline(admin.TabularInline):
    model = CandidateEducation
    extra = 1
    fields = ('degree', 'major', 'university', 'gpa', 'graduation_year')


class CandidateExperienceInline(admin.TabularInline):
    model = CandidateExperience
    extra = 1
    fields = ('company', 'job_title', 'start_date', 'end_date', 'description')


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'email', 'phone_number', 'national_id', 'created_at')
    search_fields = ('first_name', 'last_name', 'email', 'national_id', 'phone_number')
    readonly_fields = ('created_at', 'updated_at', 'deleted_at')
    inlines = [CandidateEducationInline, CandidateExperienceInline]


class ApplicationStageStateInline(admin.TabularInline):
    model = ApplicationStageState
    extra = 0
    fields = ('stage', 'status', 'score', 'evaluator')
    readonly_fields = ('stage',)


@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = ('candidate', 'job', 'current_stage', 'status', 'final_score', 'created_at')
    list_filter = ('status', 'job')
    search_fields = ('candidate__first_name', 'candidate__last_name', 'candidate__national_id', 'job__title')
    readonly_fields = ('created_at', 'updated_at', 'deleted_at')
    inlines = [ApplicationStageStateInline]


@admin.register(InterviewerScore)
class InterviewerScoreAdmin(admin.ModelAdmin):
    list_display = ('stage_state', 'interviewer', 'score', 'status')
    list_filter = ('status', 'interviewer')
    search_fields = ('stage_state__application__candidate__last_name', 'interviewer__username')


@admin.register(AssessorCompetencyScore)
class AssessorCompetencyScoreAdmin(admin.ModelAdmin):
    list_display = ('interviewer_score', 'competency', 'score')
    list_filter = ('competency',)
    search_fields = ('interviewer_score__interviewer__username', 'competency__name')


@admin.register(ExternalInterviewerScore)
class ExternalInterviewerScoreAdmin(admin.ModelAdmin):
    list_display = ('stage_state', 'interviewer_name', 'score', 'weight')
    search_fields = ('stage_state__application__candidate__last_name', 'interviewer_name')


@admin.register(JobDefaultInterviewer)
class JobDefaultInterviewerAdmin(admin.ModelAdmin):
    list_display = ('job', 'interviewer_name', 'weight')
    list_filter = ('job',)
    search_fields = ('interviewer_name', 'job__title')
