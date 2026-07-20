import os
import sys
import django
from django.db import transaction

sys.path.append('/Users/omidsalehi/Desktop/ATS')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ats.settings')
django.setup()

from apps.candidates.models import JobApplication

def run():
    with transaction.atomic():
        selected_apps = JobApplication.objects.filter(status='SELECTED', is_deleted=False)
        print(f"Found {selected_apps.count()} SELECTED applications to process.")
        
        updated_count = 0
        blank_count = 0
        for app in selected_apps:
            # Set admission_date to job.end_date
            if app.job.end_date:
                app.admission_date = app.job.end_date
                app.save(update_fields=['admission_date'])
                updated_count += 1
            else:
                app.admission_date = None
                app.save(update_fields=['admission_date'])
                blank_count += 1
                
        print(f"Successfully updated {updated_count} applications with job end_date.")
        print(f"Left {blank_count} applications with blank admission_date.")

if __name__ == '__main__':
    run()
