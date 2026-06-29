#!/usr/bin/env python3
import os
import django
import random
from datetime import datetime, date, timedelta

# Initialize Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ats.settings')
django.setup()

from django.conf import settings
from django.core.management import call_command
from django.contrib.auth.models import User

# Define new database path on Desktop
DESKTOP_DB_PATH = '/Users/omidsalehi/Desktop/demo_db.sqlite3'

# Remove existing file if present
if os.path.exists(DESKTOP_DB_PATH):
    try:
        os.remove(DESKTOP_DB_PATH)
    except Exception:
        pass

# Switch database dynamically
settings.DATABASES['default']['NAME'] = DESKTOP_DB_PATH

print("1. Running database migrations on the new database...")
call_command('migrate', verbosity=0)

# Import models after switching DB connection
from apps.jobs.models import (
    OrganizationSetting, JobOpportunity, JobOpportunityStage,
    CentralCompetency, CompetencyModel, CompetencyModelItem,
    AssessmentCompetency
)
from apps.candidates.models import (
    Candidate, CandidateEducation, CandidateExperience,
    JobApplication, ApplicationStageState, InterviewerScore,
    AssessorCompetencyScore
)

print("2. Creating superuser (admin / admin1234)...")
admin_user = User.objects.create_superuser(
    username='admin',
    email='admin@company.com',
    password='admin1234'
)

print("3. Creating organization settings...")
org = OrganizationSetting.objects.create(
    name="شرکت توسعه فناوری پترو‌آرا",
    logo=None,
    reg_email_enabled=True,
    reg_sms_enabled=True
)

print("4. Creating competency models & items...")
comp_model = CompetencyModel.objects.create(
    name="مدل شایستگی شایسته‌گزینی عمومی و کارشناسی",
    description="مدل ارزیابی شایستگی‌های عمومی، رفتاری و دانشی مناسب برای نقش‌های کارشناسی و کارشناسی ارشد"
)

competencies_data = [
    {"title": "حل مسئله و تصمیم‌گیری", "type": "GE", "importance": 1, "level": 3, "code": "COMP-001"},
    {"title": "تفکر تحلیلی و تفکر سیستم‌ها", "type": "GE", "importance": 1, "level": 2, "code": "COMP-002"},
    {"title": "کار تیمی و همکاری اثربخش", "type": "GE", "importance": 1, "level": 2, "code": "COMP-003"},
    {"title": "هوش هیجانی و همدلی", "type": "GE", "importance": 2, "level": 2, "code": "COMP-004"},
    {"title": "خلاقیت و نوآوری", "type": "GE", "importance": 2, "level": 1, "code": "COMP-005"},
    {"title": "توسعه فردی و یادگیری مستمر", "type": "GE", "importance": 1, "level": 2, "code": "COMP-006"},
]

model_items = []
for c in competencies_data:
    item = CompetencyModelItem.objects.create(
        competency_model=comp_model,
        title=c["title"],
        competency_type=c["type"],
        importance=c["importance"],
        level=c["level"],
        code=c["code"]
    )
    model_items.append(item)

print("5. Populating Central Competency bank...")
central_data = [
    # Developer Competencies
    ("DEV-001", "کارشناس توسعه نرم‌افزار", "KN-001", "Python programming language", "KN", 1, 3),
    ("DEV-002", "کارشناس توسعه نرم‌افزار", "KN-002", "Django web framework", "KN", 1, 2),
    ("DEV-003", "کارشناس توسعه نرم‌افزار", "KN-003", "PostgreSQL database design", "KN", 2, 2),
    ("DEV-004", "کارشناس توسعه نرم‌افزار", "SK-001", "Git version control", "SK", 1, 2),
    
    # HR Competencies
    ("HR-001", "کارشناس ارشد منابع انسانی", "KN-010", "Competency-based Interview (BEI)", "KN", 1, 3),
    ("HR-002", "کارشناس ارشد منابع انسانی", "SK-011", "Job Description analysis", "SK", 1, 2),
    ("HR-003", "کارشناس ارشد منابع انسانی", "KN-012", "Labor and social security law", "KN", 2, 2),
    
    # Project Manager Competencies
    ("PM-001", "مدیر پروژه فناوری اطلاعات", "KN-020", "Agile & Scrum frameworks", "KN", 1, 3),
    ("PM-002", "مدیر پروژه فناوری اطلاعات", "SK-021", "Project scheduling (MS Project/Jira)", "SK", 1, 2),
    ("PM-003", "مدیر پروژه فناوری اطلاعات", "SK-022", "Risk Management & negotiation", "SK", 1, 2)
]

for post_code, post_title, code, title, c_type, imp, lvl in central_data:
    CentralCompetency.objects.create(
        post_code=post_code,
        post_title=post_title,
        code=code,
        title=title,
        competency_type=c_type,
        importance=imp,
        level=lvl
    )

print("6. Creating 3 Job Opportunities...")
jobs = [
    {
        "title": "برنامه‌نویس ارشد پایتون (Senior Python Developer)",
        "code": "JOB-PY-01",
        "req_num": "REQ-2026-001",
        "department": "فناوری اطلاعات",
        "stages": ["غربالگری اولیه رزومه", "آزمون آنلاین فنی", "مصاحبه فنی حضوری", "کانون ارزیابی شایستگی"]
    },
    {
        "title": "کارشناس ارشد جذب و استخدام (HR Talent Acquisition)",
        "code": "JOB-HR-02",
        "req_num": "REQ-2026-002",
        "department": "منابع انسانی",
        "stages": ["بررسی رزومه و غربالگری", "مصاحبه تلفنی اولیه", "مصاحبه شایستگی‌محور عمومی"]
    },
    {
        "title": "مدیر پروژه فناوری اطلاعات (IT Project Manager)",
        "code": "JOB-PM-03",
        "req_num": "REQ-2026-003",
        "department": "مدیریت پروژه‌ها",
        "stages": ["غربالگری مدارک و سوابق", "ارزیابی فنی مدیریت پروژه", "مصاحبه نهایی پنل مدیریتی"]
    }
]

job_objects = []
for j in jobs:
    job_obj = JobOpportunity.objects.create(
        title=j["title"],
        code=j["code"],
        request_number=j["req_num"],
        department=j["department"],
        status=JobOpportunity.STATUS_PUBLISHED,
        description=f"جذب نیروی با انگیزه و متخصص جهت تصدی پست {j['title']}"
    )
    job_objects.append(job_obj)
    
    # Create stages
    for idx, stage_name in enumerate(j["stages"]):
        stage_obj = JobOpportunityStage.objects.create(
            job=job_obj,
            name=stage_name,
            sequence=idx + 1
        )
        # For evaluation stages (technical or competency), add assessment competencies
        if "ارزیابی" in stage_name or "فنی" in stage_name or "شایستگی" in stage_name:
            AssessmentCompetency.objects.create(stage=stage_obj, name="تفکر تحلیلی و تخصصی", weight=40)
            AssessmentCompetency.objects.create(stage=stage_obj, name="کار تیمی و انطباق پذیری", weight=30)
            AssessmentCompetency.objects.create(stage=stage_obj, name="تعهد و انگیزه کاری", weight=30)

print("7. Creating 10 Candidates...")
candidates_data = [
    ("علی", "حسینی", "ali.hosseini@gmail.com", "09121111111", "0012345678", "BACHELOR", "مهندسی کامپیوتر", "دانشگاه صنعتی شریف", 17.5, 1399),
    ("سارا", "احمدی", "sara.ahmadi@yahoo.com", "09122222222", "0022345678", "MASTER", "مدیریت دولتی - منابع انسانی", "دانشگاه تهران", 18.2, 1401),
    ("محمد", "کریمی", "m.karimi@gmail.com", "09123333333", "0032345678", "BACHELOR", "مهندسی صنایع", "دانشگاه صنعتی امیرکبیر", 16.8, 1400),
    ("مریم", "رضایی", "m.rezaei@gmail.com", "09124444444", "0042345678", "MASTER", "مهندسی نرم افزار", "دانشگاه شهید بهشتی", 19.0, 1402),
    ("رضا", "امیری", "r.amiri@outlook.com", "09125555555", "0052345678", "BACHELOR", "مدیریت بازرگانی", "دانشگاه علامه طباطبایی", 15.5, 1398),
    ("الناز", "شادمان", "e.shadman@gmail.com", "09126666666", "0062345678", "PHD", "روانشناسی صنعتی سازمانی", "دانشگاه خوارزمی", 18.9, 1403),
    ("پیمان", "مرادی", "p.moradi@gmail.com", "09127777777", "0072345678", "MASTER", "مدیریت پروژه", "دانشگاه تربیت مدرس", 17.2, 1400),
    ("فرزانه", "نجفی", "f.najafi@gmail.com", "09128888888", "0082345678", "BACHELOR", "مهندسی فناوری اطلاعات", "دانشگاه تهران", 17.0, 1401),
    ("حمید", "صادقی", "h.sadeghi@gmail.com", "09129999999", "0092345678", "BACHELOR", "مهندسی سخت افزار", "دانشگاه شیراز", 16.2, 1399),
    ("مهسا", "علیزاده", "m.alizadeh@gmail.com", "09121010101", "0102345678", "MASTER", "مدیریت کسب و کار MBA", "دانشگاه صنعتی شریف", 18.5, 1402),
]

candidates = []
for index, c in enumerate(candidates_data):
    cand = Candidate.objects.create(
        first_name=c[0],
        last_name=c[1],
        email=c[2],
        phone_number=c[3],
        national_id=c[4]
    )
    
    # Add Education
    CandidateEducation.objects.create(
        candidate=cand,
        degree=c[5],
        major=c[6],
        university=c[7],
        gpa=c[8],
        graduation_year=c[9]
    )
    
    # Add Experience
    CandidateExperience.objects.create(
        candidate=cand,
        company=f"شرکت نمونه {index + 1}",
        job_title="کارشناس مربوطه",
        start_date=date(2021, 1, 1),
        description="ارائه خدمات تخصصی، توسعه سیستم‌ها و بهبود فرآیندهای درون سازمانی"
    )
    
    candidates.append(cand)

print("8. Creating Applications and Stage States (Hired, Rejected, In Progress)...")
# Distribute candidates to job opportunities
# Python Dev: Ali, Mohammad, Maryam, Hamid
# HR Specialist: Sara, Reza, Elnaz, Mahsa
# Project Manager: Peyman, Farzaneh

mapping = [
    (candidates[0], job_objects[0]), # Ali -> Python Dev
    (candidates[2], job_objects[0]), # Mohammad -> Python Dev
    (candidates[3], job_objects[0]), # Maryam -> Python Dev
    (candidates[8], job_objects[0]), # Hamid -> Python Dev
    
    (candidates[1], job_objects[1]), # Sara -> HR Specialist
    (candidates[4], job_objects[1]), # Reza -> HR Specialist
    (candidates[5], job_objects[1]), # Elnaz -> HR Specialist
    (candidates[9], job_objects[1]), # Mahsa -> HR Specialist
    
    (candidates[6], job_objects[2]), # Peyman -> Project Manager
    (candidates[7], job_objects[2]), # Farzaneh -> Project Manager
]

for cand, job in mapping:
    # Create Application
    stages = list(job.stages.filter(is_deleted=False).order_by('sequence'))
    
    # Select current stage randomly or based on index
    if cand.last_name in ["حسینی", "احمدی", "مرادی"]:
        # Advanced candidates (Hired or final stages)
        curr_stage = stages[-1]
        status = JobApplication.STATUS_SELECTED
    elif cand.last_name in ["کریمی", "امیری"]:
        # Rejected candidates
        curr_stage = stages[1]
        status = JobApplication.STATUS_REJECTED
    else:
        # In progress
        curr_stage = stages[random.randint(0, len(stages)-2)]
        status = JobApplication.STATUS_IN_PROGRESS

    app = JobApplication.objects.create(
        job=job,
        candidate=cand,
        current_stage=curr_stage,
        status=status,
        admission_date=date.today() if status == JobApplication.STATUS_SELECTED else None
    )
    
    # Create ApplicationStageState for each stage up to current
    for stage in stages:
        if stage.sequence <= curr_stage.sequence:
            # Set stage state status
            if status == JobApplication.STATUS_REJECTED and stage.sequence == curr_stage.sequence:
                stage_status = ApplicationStageState.STATUS_FAILED
                score = 45.0
            elif stage.sequence < curr_stage.sequence:
                stage_status = ApplicationStageState.STATUS_COMPLETED
                score = random.randint(70, 95)
            else:
                # current stage (in progress or final selection)
                if status == JobApplication.STATUS_SELECTED:
                    stage_status = ApplicationStageState.STATUS_COMPLETED
                    score = random.randint(85, 98)
                else:
                    stage_status = ApplicationStageState.STATUS_PENDING
                    score = 0.0
            
            # Get the pre-created State record and update it
            state_rec = ApplicationStageState.objects.get(application=app, stage=stage)
            state_rec.status = stage_status
            state_rec.score = score
            state_rec.evaluator = admin_user if stage_status != ApplicationStageState.STATUS_PENDING else None
            state_rec.notes = "ارزیابی به صورت تخصصی انجام شد و پرونده به مرحله بعدی هدایت گردید." if stage_status == ApplicationStageState.STATUS_COMPLETED else ""
            state_rec.evaluation_date = date.today() if stage_status != ApplicationStageState.STATUS_PENDING else None
            state_rec.save()
            
            # If evaluated, add competency scores
            if stage_status != ApplicationStageState.STATUS_PENDING:
                # Add InterviewerScore
                int_score = InterviewerScore.objects.create(
                    stage_state=state_rec,
                    interviewer=admin_user,
                    score=score,
                    status=stage_status,
                    notes="امتیازدهی نهایی شایستگی متقاضی"
                )
                
                # Add competency scores
                for comp in stage.competencies.all():
                    AssessorCompetencyScore.objects.create(
                        interviewer_score=int_score,
                        competency=comp,
                        score=score + random.randint(-5, 5),
                        notes="ارزیابی منطبق بر شایستگی تخصصی و عمومی"
                    )

print(f"\n✅ All sample demo data populated successfully!")
print(f"👉 Pre-populated Database saved to: {DESKTOP_DB_PATH}")
print(f"📁 You can now copy this file to your git repository root and rename it to 'db.sqlite3' to run the Demo.")
