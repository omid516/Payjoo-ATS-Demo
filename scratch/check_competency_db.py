import os
import sys
import django

sys.path.insert(0, '/Users/omidsalehi/Desktop/ATS')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ats.settings')
django.setup()

from apps.jobs.models import CentralCompetency

total = CentralCompetency.objects.count()
active = CentralCompetency.objects.filter(is_deleted=False).count()
print(f"Total CentralCompetency objects: {total}")
print(f"Active CentralCompetency objects: {active}")

if active > 0:
    print("\nFirst 10 active CentralCompetency objects:")
    for cc in CentralCompetency.objects.filter(is_deleted=False)[:10]:
        print(f"  ID: {cc.id}, Post Code: {cc.post_code}, Post Title: {cc.post_title}, Code: {cc.code}, Title: {cc.title}, Type: {cc.competency_type}, Importance: {cc.importance}, Level: {cc.level}")

    # Let's count by type
    print("\nCount by type:")
    from django.db.models import Count
    types = CentralCompetency.objects.filter(is_deleted=False).values('competency_type').annotate(count=Count('id'))
    for t in types:
        print(f"  Type {t['competency_type']}: {t['count']}")
else:
    print("No active competencies found!")
