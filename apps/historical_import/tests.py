import datetime
import jdatetime
from django.test import TestCase
from django.contrib.auth.models import User
from apps.accounts.models import UserProfile
from apps.jobs.models import JobOpportunity, WorkflowTemplate, WorkflowStageTemplate, JobOpportunityStage
from apps.candidates.models import Candidate, JobApplication, ApplicationStageState
from apps.historical_import.models import ImportSession, StagingJobOpportunity, StagingCandidate, ImportSessionLog
from apps.historical_import.utils import (
    normalize_persian_digits,
    parse_date_safely,
    validate_national_id,
    execute_final_import
)

class UtilsTestCase(TestCase):
    def test_normalize_persian_digits(self):
        self.assertEqual(normalize_persian_digits("۱۲۳۴۵۶۷۸۹۰"), "1234567890")
        self.assertEqual(normalize_persian_digits("١٢٣٤٥٦٧٨٩٠"), "1234567890")
        self.assertEqual(normalize_persian_digits("abc 123"), "abc 123")
        self.assertEqual(normalize_persian_digits(None), "")

    def test_parse_date_safely(self):
        # Jalali string format
        self.assertEqual(parse_date_safely("1402/05/12"), datetime.date(2023, 8, 3))
        self.assertEqual(parse_date_safely("۱۴۰۱-۱۲-۰۵"), datetime.date(2023, 2, 24))
        
        # Already Python date or datetime
        d = datetime.date(2022, 1, 1)
        dt = datetime.datetime(2022, 1, 1, 12, 0)
        self.assertEqual(parse_date_safely(d), d)
        self.assertEqual(parse_date_safely(dt), d)
        
        # Excel float dates (approximate epoch matching)
        self.assertEqual(parse_date_safely("44197"), datetime.date(2021, 1, 1))

        # Invalid formats
        self.assertIsNone(parse_date_safely("invalid-date"))
        self.assertIsNone(parse_date_safely(""))
        self.assertIsNone(parse_date_safely(None))

    def test_validate_national_id(self):
        # Valid ID (using a mathematically valid national ID)
        self.assertTrue(validate_national_id("7731689956"))
        
        # Invalid IDs
        self.assertFalse(validate_national_id("1111111111")) # repeating
        self.assertFalse(validate_national_id("123456")) # short
        self.assertFalse(validate_national_id("abcdefghij")) # non-numeric
        self.assertFalse(validate_national_id(""))
        self.assertFalse(validate_national_id(None))


class ExecuteImportTestCase(TestCase):
    def setUp(self):
        # Create user
        self.user = User.objects.create_user(username='admin_test', password='password')
        self.profile, created = UserProfile.objects.get_or_create(user=self.user)
        self.profile.role = UserProfile.ROLE_ADMIN
        self.profile.save()
        
        # Create standard workflow template
        self.wf = WorkflowTemplate.objects.create(name="آزمون کتبی و مصاحبه")
        self.stage1 = WorkflowStageTemplate.objects.create(
            workflow=self.wf, name="آزمون کتبی", sequence=1, stage_type="EXAM", default_weight=40
        )
        self.stage2 = WorkflowStageTemplate.objects.create(
            workflow=self.wf, name="مصاحبه فنی", sequence=2, stage_type="INTERVIEW", default_weight=60
        )
        
        # Create import session
        self.session = ImportSession.objects.create(
            excel_file="historical_imports/test.xlsx",
            created_by=self.user,
            status="PREVIEWED",
            mapping_config={
                "main_sheet": "وضعیت",
                "workflow_mappings": {
                    "کتبی + مصاحبه": str(self.wf.id)
                }
            }
        )

    def test_execute_final_import_new_job(self):
        # Create staging job
        sj = StagingJobOpportunity.objects.create(
            import_session=self.session,
            row_index=2,
            job_code="JOB-TEST-100",
            title="برنامه‌نویس پایتون",
            department="فناوری اطلاعات",
            headcount="3",
            status="آزمون کتبی",
            start_date_str="1402/01/15",
            workflow_pattern="کتبی + مصاحبه"
        )
        
        # Create staging candidate
        sc = StagingCandidate.objects.create(
            import_session=self.session,
            sheet_name="آزمون کتبی",
            row_index=2,
            job_code="JOB-TEST-100",
            national_id="7731689956",
            first_name="امید",
            last_name="صالحی",
            phone_number="09123456789",
            email="omid@example.com",
            score="85.5",
            evaluation_date_str="1402/02/10",
            stage_type="EXAM"
        )

        execute_final_import(self.session, "UPDATE", self.user)
        
        # Verify job opportunity created
        job = JobOpportunity.objects.filter(code="JOB-TEST-100", is_deleted=False).first()
        self.assertIsNotNone(job)
        self.assertEqual(job.title, "برنامه‌نویس پایتون")
        self.assertEqual(job.headcount, 3)
        self.assertEqual(job.workflow, self.wf)
        self.assertEqual(job.start_date, datetime.date(2023, 4, 4))
        
        # Verify job stage counts
        stages = job.stages.filter(is_deleted=False)
        self.assertEqual(stages.count(), 2)
        
        # Verify candidate created
        candidate = Candidate.objects.filter(national_id="7731689956", is_deleted=False).first()
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.first_name, "امید")
        self.assertEqual(candidate.last_name, "صالحی")
        
        # Verify application created
        app = JobApplication.objects.filter(job=job, candidate=candidate, is_deleted=False).first()
        self.assertIsNotNone(app)
        
        # Verify stage state created and marked complete
        state = app.stage_states.filter(stage__stage_type="EXAM", is_deleted=False).first()
        self.assertIsNotNone(state)
        self.assertEqual(state.status, ApplicationStageState.STATUS_COMPLETED)
        self.assertEqual(state.score, 85.5)
        self.assertEqual(state.evaluation_date, datetime.date(2023, 4, 30))

    def test_execute_final_import_prior_stages_completion(self):
        # If candidate is in INTERVIEW, the prior stage (EXAM) should be marked COMPLETED automatically
        sj = StagingJobOpportunity.objects.create(
            import_session=self.session,
            row_index=2,
            job_code="JOB-TEST-200",
            title="کارشناس شبکه",
            department="فناوری اطلاعات",
            headcount="1",
            status="مصاحبه حضوری",
            start_date_str="1402/01/15",
            workflow_pattern="کتبی + مصاحبه"
        )
        
        sc = StagingCandidate.objects.create(
            import_session=self.session,
            sheet_name="مصاحبه",
            row_index=2,
            job_code="JOB-TEST-200",
            national_id="7731689956",
            first_name="امید",
            last_name="صالحی",
            phone_number="09123456789",
            email="omid@example.com",
            score="90",
            evaluation_date_str="1402/03/15",
            stage_type="INTERVIEW"
        )

        execute_final_import(self.session, "UPDATE", self.user)
        
        job = JobOpportunity.objects.filter(code="JOB-TEST-200").first()
        candidate = Candidate.objects.filter(national_id="7731689956").first()
        app = JobApplication.objects.filter(job=job, candidate=candidate).first()
        
        # Interview stage state should be completed with score 90
        intv_state = app.stage_states.filter(stage__stage_type="INTERVIEW").first()
        self.assertEqual(intv_state.status, ApplicationStageState.STATUS_COMPLETED)
        self.assertEqual(intv_state.score, 90.0)
        
        # Exam stage state (prior stage) should be completed automatically with cutoff score
        exam_state = app.stage_states.filter(stage__stage_type="EXAM").first()
        self.assertEqual(exam_state.status, ApplicationStageState.STATUS_COMPLETED)
        self.assertEqual(exam_state.score, 60.0) # default passing score of stage

    def test_execute_final_import_conflict_skip(self):
        # Create pre-existing JobOpportunity
        existing_job = JobOpportunity.objects.create(
            code="JOB-EXISTS-1",
            request_number="JOB-EXISTS-1",
            title="فرصت شغلی قدیمی",
            department="فروش",
            headcount=5,
            workflow=self.wf,
            status=JobOpportunity.STATUS_RECEIVED
        )
        
        sj = StagingJobOpportunity.objects.create(
            import_session=self.session,
            row_index=2,
            job_code="JOB-EXISTS-1",
            title="فرصت شغلی بروزرسانی شده", # different title
            department="پشتیبانی",
            headcount="10",
            status="آزمون کتبی",
            start_date_str="1402/01/15",
            workflow_pattern="کتبی + مصاحبه"
        )

        execute_final_import(self.session, "SKIP", self.user)
        
        # Refresh from DB
        existing_job.refresh_from_db()
        self.assertEqual(existing_job.title, "فرصت شغلی قدیمی") # should not have changed
        self.assertEqual(existing_job.headcount, 5)

    def test_execute_final_import_conflict_update(self):
        existing_job = JobOpportunity.objects.create(
            code="JOB-EXISTS-2",
            request_number="JOB-EXISTS-2",
            title="فرصت شغلی قدیمی",
            department="فروش",
            headcount=5,
            workflow=self.wf,
            status=JobOpportunity.STATUS_RECEIVED
        )
        
        sj = StagingJobOpportunity.objects.create(
            import_session=self.session,
            row_index=2,
            job_code="JOB-EXISTS-2",
            title="فرصت شغلی بروزرسانی شده",
            department="پشتیبانی",
            headcount="10",
            status="آزمون کتبی",
            start_date_str="1402/01/15",
            workflow_pattern="کتبی + مصاحبه"
        )

        execute_final_import(self.session, "UPDATE", self.user)
        
        existing_job.refresh_from_db()
        self.assertEqual(existing_job.title, "فرصت شغلی بروزرسانی شده") # title updated!
        self.assertEqual(existing_job.department, "پشتیبانی")
        self.assertEqual(existing_job.headcount, 10)
