import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ats.settings')
django.setup()

from apps.candidates.models import JobApplication
from django.db.models.functions import TruncDay
from django.db.models import Count

res = JobApplication.objects.annotate(day=TruncDay('created_at')).values('day').annotate(count=Count('id')).order_by('day')
print("Day-by-day distribution of JobApplication.created_at:")
for r in res:
    print(f"Day: {r['day']} | Count: {r['count']}")
