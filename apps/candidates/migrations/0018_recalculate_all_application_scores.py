from django.db import migrations


def recalculate_all_application_scores(apps, schema_editor):
    JobApplication = apps.get_model('candidates', 'JobApplication')
    JobOpportunity = apps.get_model('jobs', 'JobOpportunity')
    ApplicationStageState = apps.get_model('candidates', 'ApplicationStageState')

    # Iterate through all active jobs and their applications
    applications_to_update = []
    for job in JobOpportunity.objects.filter(is_deleted=False):
        job_apps = list(JobApplication.objects.filter(job=job, is_deleted=False))
        if not job_apps:
            continue
        
        # Fetch active stages and active stage states
        states = list(ApplicationStageState.objects.filter(
            application__in=job_apps,
            is_deleted=False,
            stage__is_deleted=False
        ).select_related('stage'))
        
        app_states_map = {}
        for st in states:
            app_states_map.setdefault(st.application_id, []).append(st)
            
        for app in job_apps:
            total_weighted_score = 0.0
            for st in app_states_map.get(app.id, []):
                total_weighted_score += (st.score * st.stage.weight) / 100.0
            calc_score = round(total_weighted_score, 2)
            if round(app.final_score, 2) != calc_score:
                app.final_score = calc_score
                applications_to_update.append(app)

    if applications_to_update:
        JobApplication.objects.bulk_update(applications_to_update, ['final_score'])


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('candidates', '0017_notificationlog'),
        ('jobs', '0036_organizationsetting_general_requirements'),
    ]

    operations = [
        migrations.RunPython(recalculate_all_application_scores, reverse_noop),
    ]
