from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.urls import reverse
from datetime import date, datetime
import jdatetime

from apps.jobs.models import (
    WorkflowTemplate, WorkflowStageTemplate, JobOpportunity, JobOpportunityStage,
    CentralCompetency, JobOpportunityCompetency
)
from apps.jobs.forms import JobOpportunityFormSet, JobOpportunityForm
from apps.core.templatetags.jalali_tags import to_jalali

class JobOpportunityAndWorkflowTests(TestCase):
    def setUp(self):
        # Create a recruiter user
        self.recruiter = User.objects.create_user(username='recruiter_test', password='password123')
        self.recruiter.profile.role = 'RECRUITMENT_SPECIALIST'
        self.recruiter.profile.save()

        # Create a WorkflowTemplate with default stages
        self.workflow = WorkflowTemplate.objects.create(
            name='آزمون و مصاحبه استاندارد',
            description='شامل آزمون کتبی و مصاحبه تخصصی'
        )
        self.stage1 = WorkflowStageTemplate.objects.create(
            workflow=self.workflow,
            name='آزمون کتبی',
            default_weight=40,
            sequence=1
        )
        self.stage2 = WorkflowStageTemplate.objects.create(
            workflow=self.workflow,
            name='مصاحبه حضوری',
            default_weight=60,
            sequence=2
        )

        # Create CentralCompetency records for validation in form-based tests
        CentralCompetency.objects.create(
            post_code='DEVOPS-01', post_title='DevOps', code='KN_DEV_01', title='DevOps Knowledge',
            competency_type='KN', category_raw='KN- دانش', cluster_raw='3-عمومی', importance=1, level=2
        )
        CentralCompetency.objects.create(
            post_code='AI-02', post_title='AI', code='KN_AI_02', title='AI Knowledge',
            competency_type='KN', category_raw='KN- دانش', cluster_raw='3-عمومی', importance=1, level=2
        )
        CentralCompetency.objects.create(
            post_code='SYS-1402', post_title='System Specialist', code='KN_SYS_1402', title='System Knowledge',
            competency_type='KN', category_raw='KN- دانش', cluster_raw='3-عمومی', importance=1, level=2
        )

    def test_workflow_template_creation(self):
        """تست ایجاد موفقیت‌آمیز قالب فرآیند کاری و مراحل پیش‌فرض آن"""
        self.assertEqual(self.workflow.stages.count(), 2)
        self.assertEqual(self.stage1.default_weight, 40)
        self.assertEqual(self.stage2.default_weight, 60)

    def test_job_list_filtering_and_sorting_state_preservation(self):
        """تست حفظ وضعیت فیلترها و مرتب‌سازی در لیست فرصت‌های شغلی با استفاده از سشن"""
        self.client.login(username='recruiter_test', password='password123')

        # 1. Initially request list view with query parameters
        url = reverse('job_list') + '?q=Python&sort=title&order=asc'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Verify that parameters are stored in session
        self.assertEqual(self.client.session.get('jobs_filter_params'), 'q=Python&sort=title&order=asc')

        # 2. Access the list view WITHOUT parameters (simulating going back to the page)
        response_back = self.client.get(reverse('job_list'))
        # Should redirect to preserve state
        self.assertEqual(response_back.status_code, 302)
        self.assertIn('q=Python&sort=title&order=asc', response_back.url)

        # 3. Request clear parameter to clear filters
        response_clear = self.client.get(reverse('job_list') + '?clear=1')
        self.assertEqual(response_clear.status_code, 302)
        self.assertEqual(response_clear.url, reverse('job_list'))

        # Verify session is cleared
        self.assertNotIn('jobs_filter_params', self.client.session)

    def test_job_opportunity_copies_workflow_stages(self):
        """تست اینکه با ایجاد فرصت شغلی جدید، مراحل پیش‌فرض از الگوی فرآیند کپی می‌شوند"""
        job = JobOpportunity.objects.create(
            request_number='REQ-1402-005',
            title='برنامه‌نویس پایتون',
            code='PY-1402',
            department='فناوری اطلاعات',
            assigned_recruiter=self.recruiter,
            workflow=self.workflow,
            status=JobOpportunity.STATUS_PLANNING,
            description='برنامه‌نویس مسلط به جنگو'
        )
        
        # Verify stages are copied
        job_stages = JobOpportunityStage.objects.filter(job=job).order_by('sequence')
        self.assertEqual(job_stages.count(), 2)
        self.assertEqual(job_stages[0].name, 'آزمون کتبی')
        self.assertEqual(job_stages[0].weight, 40)
        self.assertEqual(job_stages[1].name, 'مصاحبه حضوری')
        self.assertEqual(job_stages[1].weight, 60)

    def test_formset_validation_weight_sum(self):
        """تست اعتبارسنجی فرم‌ست به نحوی که مجموع وزن مراحل باید دقیقاً ۱۰۰٪ باشد"""
        job = JobOpportunity.objects.create(
            request_number='REQ-1402-006',
            title='طراح رابط کاربری',
            code='UI-1402',
            department='طراحی',
            description='طراح UI/UX'
        )
        
        # Scenario 1: Total weight is 90% (Invalid)
        data = {
            'stages-TOTAL_FORMS': '2',
            'stages-INITIAL_FORMS': '0',
            'stages-MIN_NUM_FORMS': '0',
            'stages-MAX_NUM_FORMS': '1000',
            'stages-0-name': 'آزمون عملی',
            'stages-0-weight': '40',
            'stages-0-sequence': '1',
            'stages-1-name': 'مصاحبه فنی',
            'stages-1-weight': '50',
            'stages-1-sequence': '2',
        }
        formset = JobOpportunityFormSet(data, instance=job)
        self.assertFalse(formset.is_valid())

        # Scenario 2: Total weight is 100% (Valid)
        data_valid = {
            'stages-TOTAL_FORMS': '2',
            'stages-INITIAL_FORMS': '0',
            'stages-MIN_NUM_FORMS': '0',
            'stages-MAX_NUM_FORMS': '1000',
            'stages-0-name': 'آزمون عملی',
            'stages-0-weight': '40',
            'stages-0-sequence': '1',
            'stages-1-name': 'مصاحبه فنی',
            'stages-1-weight': '60',
            'stages-1-sequence': '2',
        }
        formset_valid = JobOpportunityFormSet(data_valid, instance=job)
        self.assertTrue(formset_valid.is_valid())

    def test_soft_delete_job_opportunity(self):
        """تست حذف نرم فرصت‌های شغلی بدون حذف فیزیکی از دیتابیس"""
        job = JobOpportunity.objects.create(
            request_number='REQ-1402-007',
            title='مدیر پروژه',
            code='PM-1402',
            department='مدیریت',
            description='مدیر پروژه چابک'
        )
        
        job_pk = job.pk
        job.delete() # Soft delete
        
        # Verify not accessible via default objects manager
        self.assertFalse(JobOpportunity.objects.filter(pk=job_pk).exists())
        # Verify accessible via all_objects manager and is_deleted is True
        job_from_db = JobOpportunity.all_objects.get(pk=job_pk)
        self.assertTrue(job_from_db.is_deleted)
        self.assertIsNotNone(job_from_db.deleted_at)

    def test_jalali_date_template_filter(self):
        """تست عملکرد صحیح فیلتر تبدیل تاریخ به شمسی"""
        gregorian_date = date(2026, 6, 4)
        jalali_str = to_jalali(gregorian_date)
        self.assertEqual(jalali_str, '1405/03/14') # 2026-06-04 is 1405-03-14 in Jalali

        gregorian_datetime = datetime(2026, 6, 4, 15, 30)
        jalali_datetime_str = to_jalali(gregorian_datetime)
        self.assertEqual(jalali_datetime_str, '1405/03/14 - 15:30')

    def test_job_form_jalali_date_input_handling(self):
        """تست دریافت تاریخ شمسی از ورودی فرم و تبدیل صحیح آن به تاریخ میلادی برای ذخیره‌سازی"""
        form_data = {
            'request_number': 'REQ-1405-100',
            'title': 'کارشناس DevOps',
            'code': 'DEVOPS-01',
            'department': 'مهندسی زیرساخت',
            'unit': 'کلود',
            'headcount': '1',
            'recruitment_type': 'EXTERNAL',
            'status': 'PLANNING',
            'start_date': '1405/03/14',  # Jalali for 2026-06-04
            'end_date': '1405/04/14',    # Jalali for 2026-07-04
            'description': 'شرح وظایف کارشناس دیواپس',
        }
        form = JobOpportunityForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        job = form.save()

        # Check that stored date is Gregorian
        self.assertEqual(job.start_date, date(2026, 6, 4))
        self.assertEqual(job.end_date, date(2026, 7, 5))

    def test_workflow_template_crud_views(self):
        """تست ویوها و فرآیند ایجاد و مدیریت الگوهای فرآیند استخدام"""
        self.client.login(username='recruiter_test', password='password123')
        
        # Test List view
        response = self.client.get(reverse('workflow_list'))
        self.assertEqual(response.status_code, 200)
        
        # Test Create view
        data = {
            'name': 'الگوی برنامه‌نویس ارشد',
            'description': 'مراحل استاندارد جذب برنامه‌نویس ارشد',
            'stages-TOTAL_FORMS': '2',
            'stages-INITIAL_FORMS': '0',
            'stages-MIN_NUM_FORMS': '0',
            'stages-MAX_NUM_FORMS': '1000',
            'stages-0-name': 'مصاحبه فنی اولیه',
            'stages-0-default_weight': '50',
            'stages-0-sequence': '1',
            'stages-1-name': 'کانون ارزیابی تخصصی',
            'stages-1-default_weight': '50',
            'stages-1-sequence': '2',
        }
        response = self.client.post(reverse('workflow_add'), data)
        self.assertEqual(response.status_code, 302) # Redirects to list on success
        
        # Verify database
        wf = WorkflowTemplate.objects.get(name='الگوی برنامه‌نویس ارشد')
        self.assertEqual(wf.stages.count(), 2)

    def test_job_export_excel(self):
        """تست خروجی اکسل فرصت‌های شغلی"""
        # Create a job opportunity
        JobOpportunity.objects.create(
            request_number='REQ-1402-009',
            title='برنامه‌نویس فرانت‌اند',
            code='FE-1402',
            department='فناوری اطلاعات',
            assigned_recruiter=self.recruiter,
            workflow=self.workflow,
            status=JobOpportunity.STATUS_PLANNING,
            description='مسلط به ری‌اکت'
        )

        self.client.login(username='recruiter_test', password='password123')
        response = self.client.get(reverse('job_export_excel'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertTrue(len(response.content) > 0)

    def test_job_category_saving(self):
        """تست ثبت و ویرایش فیلد رده شغلی در فرصت‌های شغلی"""
        job = JobOpportunity.objects.create(
            request_number='REQ-1402-999',
            title='مدیر فنی',
            code='PM-999',
            department='فناوری اطلاعات',
            job_category='کارشناس',
            description='مدیریت تیم توسعه'
        )
        self.assertEqual(job.job_category, 'کارشناس')

        # Test through form
        form_data = {
            'request_number': 'REQ-1405-101',
            'title': 'کارشناس هوش مصنوعی ارشد',
            'code': 'AI-02',
            'department': 'مهندسی داده',
            'unit': 'هوش مصنوعی',
            'job_category': 'کارشناس مسئول',
            'headcount': '1',
            'recruitment_type': 'EXTERNAL',
            'status': 'PLANNING',
            'description': 'مسلط به پایتون',
        }
        form = JobOpportunityForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        job_from_form = form.save()
        self.assertEqual(job_from_form.job_category, 'کارشناس مسئول')

    def test_job_print_doc_view(self):
        """تست نمایش صفحه چاپ سند آزمون به همراه جزئیات برنامه‌ریزی جذب"""
        job = JobOpportunity.objects.create(
            request_number='REQ-1402-991',
            title='مدیر مالی',
            code='FIN-991',
            department='مالی',
            description='مدیریت امور مالی'
        )
        stage = JobOpportunityStage.objects.create(
            job=job,
            name='غربالگری اولیه',
            weight=100,
            sequence=1,
            stage_type='SCREENING'
        )

        self.client.login(username='recruiter_test', password='password123')
        
        # Scenario 1: Without recruitment plan
        url = reverse('job_print_doc', kwargs={'pk': job.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'تاریخ شروع جذب (برنامه‌ریزی)')

        # Scenario 2: With recruitment plan
        from apps.recruitment_planning.models import JobRecruitmentPlan, JobStagePlan
        plan = JobRecruitmentPlan.objects.create(
            job=job,
            start_date=date(2026, 6, 8),
            predicted_end_date=date(2026, 6, 15),
            status=JobRecruitmentPlan.STATUS_ACTIVE
        )
        JobStagePlan.objects.create(
            plan=plan,
            stage=stage,
            stage_type='SCREENING',
            planned_start_date=date(2026, 6, 8),
            planned_end_date=date(2026, 6, 13),
            sla_days=5
        )

        response_with_plan = self.client.get(url)
        self.assertEqual(response_with_plan.status_code, 200)
        self.assertContains(response_with_plan, 'تاریخ شروع جذب (برنامه‌ریزی)')
        self.assertContains(response_with_plan, '1405/03/18') # 2026-06-08 is 1405-03-18
        self.assertContains(response_with_plan, '1405/03/23') # 2026-06-13 is 1405-03-23

    def test_job_exam_specification_print_view(self):
        """تست نمایش صفحه چاپ سند مشخصات آزمون کتبی به همراه شایستگی‌ها"""
        job = JobOpportunity.objects.create(
            request_number='REQ-1402-992',
            title='مهندس برق نورد گرم',
            code='EE-992',
            department='نورد گرم',
            description='مدیریت سیستم‌های برق'
        )
        stage_exam = JobOpportunityStage.objects.create(
            job=job,
            name='آزمون کتبی',
            weight=40,
            sequence=1,
            stage_type='EXAM'
        )
        
        # Create an assessment competency linked to the exam stage
        from apps.jobs.models import AssessmentCompetency, JobOpportunityCompetency
        AssessmentCompetency.objects.create(
            stage=stage_exam,
            name='نقشه‌خوانی برق صنعتی',
            weight=100
        )
        
        # Link to JobOpportunityCompetency snapshot
        JobOpportunityCompetency.objects.create(
            job=job,
            title='نقشه‌خوانی برق صنعتی',
            code='KNEL0012',
            competency_type='KN',
            importance=1, # محوری
            level=3 # تسلط
        )
        
        self.client.login(username='recruiter_test', password='password123')
        
        url = reverse('job_exam_specification_print', kwargs={'job_id': job.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'سند مشخصات و ساختار آزمون کتبی')
        self.assertContains(response, 'نقشه‌خوانی برق صنعتی')
        self.assertContains(response, 'KNEL0012')

    def test_job_opportunity_empty_stages_assigned_workflow(self):
        """تست اختصاص مراحل پیش‌فرض به فرصت شغلی ویرایش شده که فاقد مرحله بوده است"""
        # Create job opportunity with NO workflow template
        job = JobOpportunity.objects.create(
            request_number='REQ-TEST-001',
            title='برنامه‌نویس بک‌اند',
            code='BE-1402',
            department='فناوری',
            description='طراح وب'
        )
        self.assertEqual(job.stages.count(), 0)

        # Assign workflow template to the job and save
        job.workflow = self.workflow
        job.save()

        # Check if workflow stages are replicated
        self.assertEqual(job.stages.filter(is_deleted=False).count(), 2)

    def test_job_opportunity_update_workflow_template(self):
        """تست بروزرسانی الگوی فرآیند فرصت شغلی در نمای ویرایش و بازنشانی صحیح مراحل"""
        # Create standard workflow
        another_workflow = WorkflowTemplate.objects.create(
            name='فرآیند جایگزین',
            description='یک مرحله مصاحبه'
        )
        WorkflowStageTemplate.objects.create(
            workflow=another_workflow,
            name='مصاحبه مدیر عامل',
            default_weight=100,
            sequence=1
        )

        job = JobOpportunity.objects.create(
            request_number='REQ-TEST-002',
            title='کارشناس سیستم',
            code='SYS-1402',
            department='فناوری',
            workflow=self.workflow,
            description='ادمین شبکه'
        )
        self.assertEqual(job.stages.filter(is_deleted=False).count(), 2)

        self.client.login(username='recruiter_test', password='password123')
        
        # Post request to change workflow template to another_workflow
        url = reverse('job_edit', kwargs={'pk': job.pk})
        form_data = {
            'request_number': 'REQ-TEST-002',
            'title': 'کارشناس سیستم',
            'code': 'SYS-1402',
            'department': 'فناوری',
            'workflow': another_workflow.id,
            'headcount': 1,
            'recruitment_type': 'EXTERNAL',
            'status': 'PLANNING',
            'stages-TOTAL_FORMS': '2',
            'stages-INITIAL_FORMS': '2',
            'stages-MIN_NUM_FORMS': '0',
            'stages-MAX_NUM_FORMS': '1000',
            # Old stages in the formset (simulated from HTML rendering)
            'stages-0-id': job.stages.all()[0].id,
            'stages-0-name': 'آزمون کتبی',
            'stages-0-weight': '40',
            'stages-0-sequence': '1',
            'stages-1-id': job.stages.all()[1].id,
            'stages-1-name': 'مصاحبه حضوری',
            'stages-1-weight': '60',
            'stages-1-sequence': '2',
        }
        
        response = self.client.post(url, form_data)
        self.assertEqual(response.status_code, 302)

        # Verify stages are reset and updated to the new template's stage (مصاحبه مدیر عامل)
        job.refresh_from_db()
        self.assertEqual(job.workflow, another_workflow)
        active_stages = job.stages.filter(is_deleted=False)
        self.assertEqual(active_stages.count(), 1)
        self.assertEqual(active_stages[0].name, 'مصاحبه مدیر عامل')


class JobOpportunityReportTests(TestCase):
    def setUp(self):
        self.recruiter = User.objects.create_user(username='report_recruiter', password='password123')
        self.recruiter.profile.role = 'RECRUITMENT_SPECIALIST'
        self.recruiter.profile.save()

        self.job = JobOpportunity.objects.create(
            request_number='REQ-REPORT-01',
            title='مهندس صنایع',
            code='IND-01',
            department='تولید',
            assigned_recruiter=self.recruiter,
            status=JobOpportunity.STATUS_INTERVIEW,
            description='شرح مهندس صنایع'
        )
        self.stage = JobOpportunityStage.objects.create(
            job=self.job,
            name='مصاحبه عمومی',
            weight=100,
            sequence=1,
            stage_type='INTERVIEW'
        )

        # Create Candidates and Job Applications
        from apps.candidates.models import Candidate, JobApplication, ApplicationStageState
        
        self.cand1 = Candidate.objects.create(first_name='علی', last_name='علوی', national_id='1111111111', phone_number='09121111111')
        self.cand2 = Candidate.objects.create(first_name='رضا', last_name='رضایی', national_id='2222222222', phone_number='09122222222')

        self.app1 = JobApplication.objects.create(job=self.job, candidate=self.cand1, status='SELECTED', final_score=85.0)
        self.app2 = JobApplication.objects.create(job=self.job, candidate=self.cand2, status='IN_PROGRESS', final_score=60.0)

    def test_job_opportunity_report_anonymous_redirect(self):
        """تست اینکه کاربران وارد نشده به صفحه لاگین هدایت می‌شوند"""
        url = reverse('job_opportunity_report', kwargs={'pk': self.job.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_job_opportunity_report_authorized_user(self):
        """تست مشاهده شناسنامه فرصت شغلی توسط کاربر مجاز"""
        self.client.login(username='report_recruiter', password='password123')
        url = reverse('job_opportunity_report', kwargs={'pk': self.job.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'jobs/job_report.html')
        self.assertContains(response, 'مهندس صنایع')
        self.assertContains(response, 'IND-01')
        # Check context
        self.assertEqual(response.context['total_registered'], 2)
        self.assertEqual(response.context['status_counts']['selected'], 1)
        self.assertEqual(response.context['status_counts']['inprogress'], 1)

    def test_job_opportunity_report_no_assigned_recruiter(self):
        """تست مشاهده شناسنامه فرصت شغلی زمانی که کارشناس جذب مسئول مشخص نشده است (None)"""
        self.job.assigned_recruiter = None
        self.job.save()
        
        self.client.login(username='report_recruiter', password='password123')
        url = reverse('job_opportunity_report', kwargs={'pk': self.job.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'jobs/job_report.html')
        self.assertContains(response, 'مهندس صنایع')
        # Checks that the null recruiter is rendered as "-"
        self.assertContains(response, '-')


class JobOpportunityBulkStatusTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_user(username='bulk_admin', password='password123')
        self.admin_user.profile.role = 'ADMIN'
        self.admin_user.profile.save()
        
        self.normal_user = User.objects.create_user(username='bulk_normal', password='password123')
        self.normal_user.profile.role = 'INTERVIEWER'  # Not authorized to manage jobs
        self.normal_user.profile.save()

        self.job1 = JobOpportunity.objects.create(
            request_number='REQ-BULK-01', title='برنامه‌نویس', code='DEV-BULK-01',
            department='فناوری', status=JobOpportunity.STATUS_PUBLISHED
        )
        self.job2 = JobOpportunity.objects.create(
            request_number='REQ-BULK-02', title='مدیر پروژه', code='PM-BULK-02',
            department='فناوری', status=JobOpportunity.STATUS_PUBLISHED
        )

    def test_bulk_status_update_anonymous_redirect(self):
        url = reverse('job_bulk_status_update')
        response = self.client.post(url, {'job_codes': 'DEV-BULK-01', 'new_status': 'SUSPENDED'})
        self.assertEqual(response.status_code, 302)

    def test_bulk_status_update_unauthorized_user(self):
        self.client.login(username='bulk_normal', password='password123')
        url = reverse('job_bulk_status_update')
        response = self.client.post(url, {'job_codes': 'DEV-BULK-01', 'new_status': 'SUSPENDED'})
        self.assertEqual(response.status_code, 403)

    def test_bulk_status_update_success(self):
        self.client.login(username='bulk_admin', password='password123')
        url = reverse('job_bulk_status_update')
        response = self.client.post(url, {
            'job_codes': 'DEV-BULK-01, PM-BULK-02\nINVALID-CODE',
            'new_status': 'SUSPENDED'
        })
        self.assertEqual(response.status_code, 302)
        
        self.job1.refresh_from_db()
        self.job2.refresh_from_db()
        self.assertEqual(self.job1.status, JobOpportunity.STATUS_SUSPENDED)
        self.assertEqual(self.job2.status, JobOpportunity.STATUS_SUSPENDED)


class JobOpportunitySortingTests(TestCase):
    def setUp(self):
        self.recruiter = User.objects.create_user(username='sorting_recruiter', password='password123')
        self.recruiter.profile.role = 'RECRUITMENT_SPECIALIST'
        self.recruiter.profile.save()

        # Create opportunities with different attributes
        self.job_a = JobOpportunity.objects.create(
            request_number='REQ-SORT-A', title='A_Python Developer', code='DEV-A',
            department='Tech', headcount=5, status=JobOpportunity.STATUS_RECEIVED
        )
        self.job_b = JobOpportunity.objects.create(
            request_number='REQ-SORT-B', title='B_Project Manager', code='DEV-B',
            department='Biz', headcount=2, status=JobOpportunity.STATUS_PLANNING
        )
        self.job_c = JobOpportunity.objects.create(
            request_number='REQ-SORT-C', title='C_QA Engineer', code='DEV-C',
            department='Tech', headcount=1, status=JobOpportunity.STATUS_PUBLISHED
        )

    def test_sorting_by_code_asc(self):
        self.client.login(username='sorting_recruiter', password='password123')
        url = reverse('job_list') + '?sort=code&order=asc'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        jobs = list(response.context['jobs'])
        self.assertEqual([j.code for j in jobs], ['DEV-A', 'DEV-B', 'DEV-C'])

    def test_sorting_by_title_desc(self):
        self.client.login(username='sorting_recruiter', password='password123')
        url = reverse('job_list') + '?sort=title&order=desc'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        jobs = list(response.context['jobs'])
        self.assertEqual([j.title for j in jobs], ['C_QA Engineer', 'B_Project Manager', 'A_Python Developer'])

    def test_sorting_by_headcount_asc(self):
        self.client.login(username='sorting_recruiter', password='password123')
        url = reverse('job_list') + '?sort=headcount&order=asc'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        jobs = list(response.context['jobs'])
        self.assertEqual([j.headcount for j in jobs], [1, 2, 5])


class JobOpportunityDeletionAndReuseTests(TestCase):
    def setUp(self):
        self.recruiter = User.objects.create_user(username='delete_recruiter', password='password123')
        self.recruiter.profile.role = 'RECRUITMENT_SPECIALIST'
        self.recruiter.profile.save()
        self.client.login(username='delete_recruiter', password='password123')

        from apps.candidates.models import Candidate, JobApplication
        self.Candidate = Candidate
        self.JobApplication = JobApplication

    def test_reusing_code_and_request_number_after_deletion(self):
        """تست استفاده مجدد از کد و شماره درخواست پس از حذف نرم"""
        job1 = JobOpportunity.objects.create(
            request_number='REQ-REUSE-01',
            title='شغل اول',
            code='CODE-REUSE-01',
            department='فناوری'
        )
        job1.delete()

        # Should be able to create a new one with same fields
        try:
            job2 = JobOpportunity.objects.create(
                request_number='REQ-REUSE-01',
                title='شغل دوم',
                code='CODE-REUSE-01',
                department='فناوری'
            )
        except Exception as e:
            self.fail(f"Could not create job with reused code/request_number: {e}")

        self.assertEqual(JobOpportunity.objects.filter(code='CODE-REUSE-01').count(), 1)
        self.assertEqual(JobOpportunity.all_objects.filter(code='CODE-REUSE-01').count(), 2)

    def test_active_jobs_cannot_have_duplicate_code_or_request_number(self):
        """تست عدم امکان ثبت دو فرصت شغلی فعال با کد یا شماره درخواست یکسان"""
        from django.db import IntegrityError, transaction

        JobOpportunity.objects.create(
            request_number='REQ-DUP-01',
            title='شغل فعال',
            code='CODE-DUP-01',
            department='فناوری'
        )

        # Test duplicate code under DIFFERENT request_number is allowed (Issue #1 requirement)
        job_same_code = JobOpportunity.objects.create(
            request_number='REQ-DUP-02',
            title='شغل دیگر با همان کد',
            code='CODE-DUP-01',
            department='فناوری'
        )
        self.assertIsNotNone(job_same_code.pk)

        # Test duplicate (request_number, code) compound uniqueness
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                JobOpportunity.objects.create(
                    request_number='REQ-DUP-01',
                    title='شغل دیگر با همان شماره درخواست و کد',
                    code='CODE-DUP-01',
                    department='فناوری'
                )

        # Test duplicate request_number
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                JobOpportunity.objects.create(
                    request_number='REQ-DUP-01',
                    title='شغل دیگر با همان شماره درخواست',
                    code='CODE-DUP-02',
                    department='فناوری'
                )

    def test_delete_job_and_keep_exclusive_candidates(self):
        """تست حذف فرصت شغلی و حفظ متقاضیان اختصاصی در بانک استعدادها"""
        job = JobOpportunity.objects.create(
            request_number='REQ-DEL-K',
            title='تست حذف و حفظ',
            code='CODE-DEL-K',
            department='فناوری'
        )
        candidate = self.Candidate.objects.create(
            first_name='حسن',
            last_name='رضایی',
            national_id='1111111112',
            phone_number='09121111112'
        )
        app = self.JobApplication.objects.create(job=job, candidate=candidate)

        url = reverse('job_delete', kwargs={'pk': job.pk})
        response = self.client.post(url, {'cleanup_option': 'keep'})
        self.assertEqual(response.status_code, 200)

        # Job and Application should be soft-deleted
        self.assertTrue(JobOpportunity.all_objects.get(pk=job.pk).is_deleted)
        self.assertTrue(self.JobApplication.all_objects.get(pk=app.pk).is_deleted)
        # Candidate should NOT be deleted
        candidate.refresh_from_db()
        self.assertFalse(candidate.is_deleted)

    def test_delete_job_and_delete_exclusive_candidates(self):
        """تست حذف فرصت شغلی و حذف متقاضیان اختصاصی آن"""
        job = JobOpportunity.objects.create(
            request_number='REQ-DEL-D',
            title='تست حذف و حذف متقاضی',
            code='CODE-DEL-D',
            department='فناوری'
        )
        candidate = self.Candidate.objects.create(
            first_name='حسین',
            last_name='احمدی',
            national_id='1111111113',
            phone_number='09121111113'
        )
        app = self.JobApplication.objects.create(job=job, candidate=candidate)

        url = reverse('job_delete', kwargs={'pk': job.pk})
        response = self.client.post(url, {'cleanup_option': 'delete_exclusive'})
        self.assertEqual(response.status_code, 200)

        # Job, Application and Candidate should be soft-deleted
        self.assertTrue(JobOpportunity.all_objects.get(pk=job.pk).is_deleted)
        self.assertTrue(self.JobApplication.all_objects.get(pk=app.pk).is_deleted)
        
        # Candidate profile is soft-deleted
        candidate_from_db = self.Candidate.all_objects.get(pk=candidate.pk)
        self.assertTrue(candidate_from_db.is_deleted)

    def test_delete_job_does_not_delete_non_exclusive_candidates(self):
        """تست اینکه حذف فرصت شغلی با انتخاب حذف متقاضیان، متقاضیانی که درخواست دیگری دارند را حذف نمی‌کند"""
        job1 = JobOpportunity.objects.create(
            request_number='REQ-DEL-N1',
            title='تست حذف غیر اختصاصی ۱',
            code='CODE-DEL-N1',
            department='فناوری'
        )
        job2 = JobOpportunity.objects.create(
            request_number='REQ-DEL-N2',
            title='تست حذف غیر اختصاصی ۲',
            code='CODE-DEL-N2',
            department='فناوری'
        )
        candidate = self.Candidate.objects.create(
            first_name='جعفر',
            last_name='عباسی',
            national_id='1111111114',
            phone_number='09121111114'
        )
        app1 = self.JobApplication.objects.create(job=job1, candidate=candidate)
        app2 = self.JobApplication.objects.create(job=job2, candidate=candidate)

        url = reverse('job_delete', kwargs={'pk': job1.pk})
        response = self.client.post(url, {'cleanup_option': 'delete_exclusive'})
        self.assertEqual(response.status_code, 200)

        # Job1 and App1 should be soft-deleted
        self.assertTrue(JobOpportunity.all_objects.get(pk=job1.pk).is_deleted)
        self.assertTrue(self.JobApplication.all_objects.get(pk=app1.pk).is_deleted)

        # Job2 and App2 should NOT be deleted
        self.assertFalse(JobOpportunity.all_objects.get(pk=job2.pk).is_deleted)
        self.assertFalse(self.JobApplication.all_objects.get(pk=app2.pk).is_deleted)

        # Candidate should NOT be deleted because they have active application to Job2
        candidate.refresh_from_db()
        self.assertFalse(candidate.is_deleted)


class CompetencyEngineTests(TestCase):
    def setUp(self):
        # Create a user and log them in
        self.user = User.objects.create_superuser(username='admin_user', password='password123')
        self.client.login(username='admin_user', password='password123')

        # Create central competencies for tests
        self.cc1 = CentralCompetency.objects.create(
            post_code='8526', post_title='ریخته گری', code='KNHS0003', title='HSE',
            competency_type='KN', category_raw='KN- دانش', cluster_raw='3-عمومی',
            importance=1, level=3
        )
        self.cc2 = CentralCompetency.objects.create(
            post_code='8526', post_title='ریخته گری', code='SKHS0001', title='مهارت HSE',
            competency_type='SK', category_raw='SK- مهارت', cluster_raw='2-فنی',
            importance=2, level=2
        )
        self.cc3 = CentralCompetency.objects.create(
            post_code='8526', post_title='ریخته گری', code='GEHS0001', title='رفتار HSE',
            competency_type='GE', category_raw='GE-رفتاری', cluster_raw='3-عمومی',
            importance=3, level=1
        )

        # Create a job opportunity
        self.job = JobOpportunity.objects.create(
            request_number='REQ-COMP-01', title='کارشناس متالورژی', code='8526', department='تولید'
        )

    def test_calculate_assessment_plan_math(self):
        """تست ریاضی موتور ارزیابی و رعایت محدودیت‌های وزنی مراحل"""
        from apps.jobs.utils import calculate_assessment_plan
        
        # Test competency model mocks or real selected instances
        jc1 = JobOpportunityCompetency.objects.create(
            job=self.job, central_competency=self.cc1, code=self.cc1.code, title=self.cc1.title,
            competency_type=self.cc1.competency_type, importance=self.cc1.importance, level=self.cc1.level
        )
        jc2 = JobOpportunityCompetency.objects.create(
            job=self.job, central_competency=self.cc2, code=self.cc2.code, title=self.cc2.title,
            competency_type=self.cc2.competency_type, importance=self.cc2.importance, level=self.cc2.level
        )
        jc3 = JobOpportunityCompetency.objects.create(
            job=self.job, central_competency=self.cc3, code=self.cc3.code, title=self.cc3.title,
            competency_type=self.cc3.competency_type, importance=self.cc3.importance, level=self.cc3.level
        )
        
        res = calculate_assessment_plan([jc1, jc2, jc3])
        stages = res['stages']
        
        # Verify that weights sum to exactly 100%
        total_weight = sum(s['weight'] for s in stages.values())
        self.assertEqual(total_weight, 100)
        
        # Verify constraints are applied
        # EXAM (min 20, max 50)
        # SKILL_TEST (min 20, max 40)
        # INTERVIEW (min 10, max 25)
        # ASSESSMENT (min 15, max 40)
        if 'EXAM' in stages:
            self.assertTrue(20 <= stages['EXAM']['weight'] <= 50)
        if 'SKILL_TEST' in stages:
            self.assertTrue(20 <= stages['SKILL_TEST']['weight'] <= 40)
        if 'INTERVIEW' in stages:
            self.assertTrue(10 <= stages['INTERVIEW']['weight'] <= 25)
        if 'ASSESSMENT' in stages:
            self.assertTrue(15 <= stages['ASSESSMENT']['weight'] <= 40)

    def test_calculate_assessment_plan_bypass_limits(self):
        """تست عملکرد موتور ارزیابی با بایپس کردن رنج محدودیت اوزان مراحل"""
        from apps.jobs.utils import calculate_assessment_plan
        
        jc1 = JobOpportunityCompetency.objects.create(
            job=self.job, central_competency=self.cc1, code=self.cc1.code, title=self.cc1.title,
            competency_type=self.cc1.competency_type, importance=self.cc1.importance, level=self.cc1.level
        )
        jc2 = JobOpportunityCompetency.objects.create(
            job=self.job, central_competency=self.cc2, code=self.cc2.code, title=self.cc2.title,
            competency_type=self.cc2.competency_type, importance=self.cc2.importance, level=self.cc2.level
        )
        jc3 = JobOpportunityCompetency.objects.create(
            job=self.job, central_competency=self.cc3, code=self.cc3.code, title=self.cc3.title,
            competency_type=self.cc3.competency_type, importance=self.cc3.importance, level=self.cc3.level
        )
        
        custom_weights = {
            'EXAM': 70,
            'SKILL_TEST': 10,
            'INTERVIEW': 20
        }
        res = calculate_assessment_plan(
            [jc1, jc2, jc3],
            custom_weights=custom_weights,
            bypass_limits=True,
            deactivated_stages=['ASSESSMENT']
        )
        stages = res['stages']
        
        self.assertEqual(res['errors'], [])
        self.assertEqual(stages['EXAM']['weight'], 70)
        self.assertEqual(stages['SKILL_TEST']['weight'], 10)
        self.assertEqual(stages['INTERVIEW']['weight'], 20)

    def test_excel_import_logic(self):
        """تست همگام‌سازی و ایمپورت اکسل شایستگی‌ها"""
        import tempfile
        import openpyxl
        from apps.jobs.utils import parse_competencies_excel

        # Create a mock Excel sheet
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Result'
            
            headers = [
                'کد پست', 'پست', 'کد شایستگی', 'کد شایستگی قدیم', 'شایستگی',
                'نوع شایستگی', 'طبقه', 'خوشه', 'شایستگی از تاریخ', 'شایستگی تا تاریخ',
                'اهمیت شایستگی', 'سطح شایستگی', 'کد مدیریت', 'مدیریت',
                'کد معاونت', 'معاونت', 'کد قسمت', 'قسمت', 'کد مرکز هزینه', 'مرکز هزینه'
            ]
            ws.append(headers)
            
            row1 = [
                '8526', 'ریخته گری مداوم', 'KNHS0003', 'KN0065', 'نظام مدیریت HSE',
                '1- شایستگی شغل', 'KN- دانش', '3-عمومی', '1400/07/20', '1500/12/29',
                '1- محوری', '3- تسلط', '17', 'ریخته گری', '360', 'بهره برداری',
                'MPC/5', 'دفتر MPC', '2917', 'برنامه ریزی'
            ]
            row2 = [
                '9000', 'پست جدید', 'SKTECH01', 'SK0200', 'جوشکاری تخصصی',
                '2-شایستگی پست', 'SK- مهارت', '2-فنی', '1400/07/20', '1500/12/29',
                '2- تکلیف محور', '2- توانایی', '17', 'فنی', '360', 'بهره برداری',
                'MPC/5', 'دفتر فنی', '2918', 'تعمیرات'
            ]
            ws.append(row1)
            ws.append(row2)
            
            wb.save(tmp.name)
            tmp_path = tmp.name

        try:
            # Import mock Excel
            stats = parse_competencies_excel(tmp_path)
            
            # Check import stats
            # In setUp we created 3 competencies:
            # - (8526, KNHS0003) -> updated (was created in setup, exists in excel)
            # - (8526, SKHS0001) -> deleted (setup, doesn't exist in excel)
            # - (8526, GEHS0001) -> deleted (setup, doesn't exist in excel)
            # - (9000, SKTECH01) -> created (new in excel)
            self.assertEqual(stats['created'], 1)
            self.assertEqual(stats['updated'], 1)
            self.assertEqual(stats['deleted'], 2)
            
            # Verify database rows
            self.assertEqual(CentralCompetency.objects.filter(is_deleted=False).count(), 2)
            self.assertEqual(CentralCompetency.objects.filter(post_code='9000', code='SKTECH01').count(), 1)
        finally:
            import os
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_job_competency_config_views(self):
        """تست ویوی تخصیص شایستگی‌ها به فرصت شغلی"""
        url = reverse('job_competency_config', kwargs={'job_id': self.job.id})
        from apps.jobs.models import CompetencyModel
        comp_model = CompetencyModel.objects.create(name="مدل تست")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'jobs/job_competency_config.html')
        self.assertIn('competency_models', response.context)
        self.assertIn(comp_model, list(response.context['competency_models']))

        # 1. Test search posts dynamic GET action
        search_response = self.client.get(url, {'action': 'search_posts', 'q': '8526'})
        self.assertEqual(search_response.status_code, 200)
        import json
        res_data = json.loads(search_response.content)
        self.assertIn('items', res_data)
        # Ensure our cc1/cc2 post code '8526' is in the results
        post_codes = [item['post_code'] for item in res_data['items']]
        self.assertIn('8526', post_codes)

        # 2. Test load post competencies action
        load_response = self.client.post(url, {'action': 'load_post_comps', 'post_code': '8526'})
        self.assertEqual(load_response.status_code, 200)
        self.assertTemplateUsed(load_response, 'jobs/partials/post_competencies_list.html')
        self.assertContains(load_response, self.cc1.title)
        self.assertContains(load_response, self.cc2.title)

        # 3. Test preview competencies action
        preview_response = self.client.post(url, {
            'action': 'preview',
            'selected_competencies': f"{self.cc1.id},{self.cc2.id}"
        })
        self.assertEqual(preview_response.status_code, 200)
        self.assertTemplateUsed(preview_response, 'jobs/partials/competency_preview_table.html')
        self.assertContains(preview_response, 'آزمون کتبی')
        self.assertContains(preview_response, 'آزمون مهارتی')

        # 4. Select competencies KNHS0003 and SKHS0001
        data = {
            'action': 'save',
            'selected_competencies': [self.cc1.id, self.cc2.id]
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302) # Redirects to job list

        # Verify job stages and competencies are created
        self.job.refresh_from_db()
        self.assertEqual(self.job.stages.filter(is_deleted=False).count(), 4)
        # Stages created: SCREENING, EXAM, SKILL_TEST, INTERVIEW (because SCREENING is always active, and SK requires both skills test and interview)
        stage_names = set(s.stage_type for s in self.job.stages.filter(is_deleted=False))
        self.assertEqual(stage_names, {'SCREENING', 'EXAM', 'SKILL_TEST', 'INTERVIEW'})
        
        # Verify AssessmentPlan printable page
        print_url = reverse('job_assessment_plan_print', kwargs={'job_id': self.job.id})
        print_response = self.client.get(print_url)
        self.assertEqual(print_response.status_code, 200)
        self.assertTemplateUsed(print_response, 'jobs/assessment_plan_print.html')

    def test_custom_weights_and_validation(self):
        """تست اختصاص اوزان سفارشی و اعتبارسنجی محدودیت‌ها"""
        from apps.jobs.utils import calculate_assessment_plan
        
        # 1. Test valid custom weights
        # cc1 (KN) and cc2 (SK) are active. Active stages: EXAM, SKILL_TEST, INTERVIEW.
        # Limits: EXAM (20-50), SKILL_TEST (20-40), INTERVIEW (10-25).
        # We set: EXAM=40, SKILL_TEST=35, INTERVIEW=25. Sum=100.
        custom_weights = {
            'EXAM': 40,
            'SKILL_TEST': 35,
            'INTERVIEW': 25
        }
        res = calculate_assessment_plan([self.cc1, self.cc2], custom_weights=custom_weights)
        self.assertEqual(len(res['errors']), 0)
        self.assertEqual(res['stages']['EXAM']['weight'], 40)
        self.assertEqual(res['stages']['SKILL_TEST']['weight'], 35)
        self.assertEqual(res['stages']['INTERVIEW']['weight'], 25)
        
        # 2. Test invalid weights (violating min/max limits)
        # EXAM=10 (less than 20), SKILL_TEST=40, INTERVIEW=50 (more than 25)
        custom_weights_invalid = {
            'EXAM': 10,
            'SKILL_TEST': 40,
            'INTERVIEW': 50
        }
        res_invalid = calculate_assessment_plan([self.cc1, self.cc2], custom_weights=custom_weights_invalid)
        self.assertGreater(len(res_invalid['errors']), 0)
        self.assertTrue(any("کمتر از ۲۰" in err or "کمتر از 20" in err for err in res_invalid['errors']))
        self.assertTrue(any("بیشتر از ۲۵" in err or "بیشتر از 25" in err for err in res_invalid['errors']))
        
        # 3. Test sum != 100
        custom_weights_sum = {
            'EXAM': 30,
            'SKILL_TEST': 30,
            'INTERVIEW': 20
        } # sum = 80
        res_sum = calculate_assessment_plan([self.cc1, self.cc2], custom_weights=custom_weights_sum)
        self.assertIn("مجموع اوزان مراحل ارزیابی باید دقیقاً ۱۰۰٪ باشد. (مجموع فعلی: 80٪)", res_sum['errors'])

        # 4. Test view-level save with bypass_limits=True and invalid weights
        url = reverse('job_competency_config', kwargs={'job_id': self.job.id})
        data = {
            'action': 'save',
            'selected_competencies': [self.cc1.id, self.cc2.id],
            'stage_weight_EXAM': 70,
            'stage_weight_SKILL_TEST': 10,
            'stage_weight_INTERVIEW': 20,
            'bypass_limits': 'on'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302) # successfully saved and redirected
        self.job.refresh_from_db()
        self.assertTrue(self.job.bypass_limits)
        stages = {s.stage_type: s.weight for s in self.job.stages.filter(is_deleted=False)}
        self.assertEqual(stages['EXAM'], 70)
        self.assertEqual(stages['SKILL_TEST'], 10)
        self.assertEqual(stages['INTERVIEW'], 20)

    def test_workflow_template_recommendation_and_save(self):
        """تست پیشنهاد الگوی فرآیند استخدام منطبق و ثبت آن روی فرصت شغلی"""
        from apps.jobs.models import WorkflowTemplate, WorkflowStageTemplate
        from apps.jobs.utils import suggest_workflow_templates
        
        # Create a test workflow template that perfectly matches {'EXAM', 'INTERVIEW', 'SKILL_TEST'}
        workflow = WorkflowTemplate.objects.create(name="الگوی تست کتبی+مهارتی+مصاحبه")
        WorkflowStageTemplate.objects.create(workflow=workflow, name="کتبی", stage_type='EXAM', sequence=1)
        WorkflowStageTemplate.objects.create(workflow=workflow, name="مهارتی", stage_type='SKILL_TEST', sequence=2)
        WorkflowStageTemplate.objects.create(workflow=workflow, name="مصاحبه", stage_type='INTERVIEW', sequence=3)
        
        # Suggest templates based on active stages
        active_stages = ['EXAM', 'SKILL_TEST', 'INTERVIEW']
        suggestions = suggest_workflow_templates(active_stages)
        
        # The created workflow template should be a perfect match (100% match)
        perf_matches = [s for s in suggestions if s['template'].id == workflow.id]
        self.assertEqual(len(perf_matches), 1)
        self.assertEqual(perf_matches[0]['match_percentage'], 100)
        self.assertTrue(perf_matches[0]['is_perfect_match'])
        
        # Save config with custom weights and selected workflow template
        url = reverse('job_competency_config', kwargs={'job_id': self.job.id})
        data = {
            'action': 'save',
            'selected_competencies': [self.cc1.id, self.cc2.id],
            'stage_weight_EXAM': 40,
            'stage_weight_SKILL_TEST': 35,
            'stage_weight_INTERVIEW': 25,
            'workflow_template_id': workflow.id
        }
        response = self.client.post(url, data)
        
        self.job.refresh_from_db()
        self.assertEqual(response.status_code, 302) # Success redirect
        
        # Verify job stages weights and workflow template assignment
        self.assertEqual(self.job.workflow.id, workflow.id)
        self.assertEqual(self.job.stages.get(stage_type='EXAM').weight, 40)
        self.assertEqual(self.job.stages.get(stage_type='SKILL_TEST').weight, 35)
        self.assertEqual(self.job.stages.get(stage_type='INTERVIEW').weight, 25)

    def test_custom_passing_scores_validation_and_persistence(self):
        """تست تعیین حد نصاب‌های سفارشی و صحت ذخیره‌سازی در پایگاه داده"""
        url = reverse('job_competency_config', kwargs={'job_id': self.job.id})
        
        # 1. Validation error: Out of bounds (e.g. 120 or -10)
        data_invalid = {
            'action': 'save',
            'selected_competencies': [self.cc1.id, self.cc2.id],
            'stage_weight_EXAM': 40,
            'stage_weight_SKILL_TEST': 35,
            'stage_weight_INTERVIEW': 25,
            'stage_passing_score_EXAM': 120,
            'stage_passing_score_SKILL_TEST': 70,
            'stage_passing_score_INTERVIEW': -10
        }
        response_invalid = self.client.post(url, data_invalid)
        self.assertEqual(response_invalid.status_code, 200)
        self.assertContains(response_invalid, "باید بین ۰ و ۱۰۰ باشد")

        # 2. Valid scenario: correct weights and passing scores
        data_valid = {
            'action': 'save',
            'selected_competencies': [self.cc1.id, self.cc2.id],
            'stage_weight_EXAM': 40,
            'stage_weight_SKILL_TEST': 35,
            'stage_weight_INTERVIEW': 25,
            'stage_passing_score_EXAM': 75,
            'stage_passing_score_SKILL_TEST': 80,
            'stage_passing_score_INTERVIEW': 65
        }
        response_valid = self.client.post(url, data_valid)
        self.assertEqual(response_valid.status_code, 302)
        
        # Verify db stages values
        self.job.refresh_from_db()
        exam_stage = self.job.stages.get(stage_type='EXAM')
        skill_stage = self.job.stages.get(stage_type='SKILL_TEST')
        interview_stage = self.job.stages.get(stage_type='INTERVIEW')
        
        self.assertEqual(int(exam_stage.passing_score), 75)
        self.assertEqual(int(skill_stage.passing_score), 80)
        self.assertEqual(int(interview_stage.passing_score), 65)

    def test_job_opportunity_creation_redirects_to_config(self):
        """تست اینکه پس از ایجاد فرصت شغلی جدید، کاربر به صفحه پیکربندی شایستگی‌ها هدایت می‌شود"""
        # Create a new central competency with unique post code 8527
        CentralCompetency.objects.create(
            post_code='8527', post_title='ریخته گری ۲', code='KNHS0004', title='HSE 2',
            competency_type='KN', category_raw='KN- دانش', cluster_raw='3-عمومی',
            importance=1, level=3
        )
        
        form_data = {
            'request_number': 'REQ-REDIRECT-001',
            'title': 'شغل تستی ریدایرکت',
            'code': '8527',
            'department': 'فناوری اطلاعات',
            'unit': 'فناوری',
            'job_category': 'کارشناس',
            'headcount': 2,
            'recruitment_type': 'EXTERNAL',
            'status': 'RECEIVED',
            'stages-TOTAL_FORMS': '0',
            'stages-INITIAL_FORMS': '0',
            'stages-MIN_NUM_FORMS': '0',
            'stages-MAX_NUM_FORMS': '1000',
        }
        url = reverse('job_add')
        response = self.client.post(url, form_data)
        
        new_job = JobOpportunity.objects.get(request_number='REQ-REDIRECT-001')
        expected_redirect_url = reverse('job_competency_config', kwargs={'job_id': new_job.id})
        self.assertRedirects(response, expected_redirect_url)

    def test_job_opportunity_creation_planning_redirects_to_planning(self):
        """تست اینکه پس از ایجاد فرصت شغلی جدید با وضعیت برنامه‌ریزی، کاربر به صفحه برنامه‌ریزی هدایت می‌شود"""
        CentralCompetency.objects.create(
            post_code='8527', post_title='ریخته گری ۲', code='KNHS0004', title='HSE 2',
            competency_type='KN', category_raw='KN- دانش', cluster_raw='3-عمومی',
            importance=1, level=3
        )
        
        form_data = {
            'request_number': 'REQ-REDIRECT-002',
            'title': 'شغل تستی ریدایرکت برنامه‌ریزی',
            'code': '8527',
            'department': 'فناوری اطلاعات',
            'unit': 'فناوری',
            'job_category': 'کارشناس',
            'headcount': 2,
            'recruitment_type': 'EXTERNAL',
            'status': 'PLANNING',
            'stages-TOTAL_FORMS': '0',
            'stages-INITIAL_FORMS': '0',
            'stages-MIN_NUM_FORMS': '0',
            'stages-MAX_NUM_FORMS': '1000',
        }
        url = reverse('job_add')
        response = self.client.post(url, form_data)
        
        new_job = JobOpportunity.objects.get(request_number='REQ-REDIRECT-002')
        expected_redirect_url = reverse('job_planning', kwargs={'job_id': new_job.id}) + '?next=print_doc'
        self.assertRedirects(response, expected_redirect_url)

    def test_post_detail_api_auto_populates_fields(self):
        """تست گرفتن اطلاعات پست سازمانی برای پرکردن خودکار فرم شغل"""
        # Create a central competency with management/section metadata
        CentralCompetency.objects.create(
            post_code='8528',
            post_title='کارشناس مسئول ریخته گری',
            code='KNHS0005',
            title='HSE 3',
            competency_type='KN',
            category_raw='KN- دانش',
            cluster_raw='3-عمومی',
            importance=1,
            level=3,
            management_name='تولید فولاد',
            section_name='بخش ذوب'
        )

        url = reverse('post_detail_api') + '?post_code=8528'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        import json
        data = json.loads(response.content)
        self.assertEqual(data['title'], 'کارشناس مسئول ریخته گری')
        self.assertEqual(data['department'], 'تولید فولاد')
        self.assertEqual(data['unit'], 'بخش ذوب')
        self.assertEqual(data['job_category'], 'کارشناس مسئول')

    def test_custom_competencies_preview(self):
        """تست پیش‌نمایش زنده محاسبات با افزودن شایستگی‌های دستی"""
        url = reverse('job_competency_config', kwargs={'job_id': self.job.id})
        
        # We will send a manual competency of type 'ST' (Styles & Values)
        # ST type: triggers Assessment Center stage if importance is 1 or 2.
        import json
        custom_comp = {
            'title': 'ارزش سازمانی پیجو',
            'competency_type': 'ST',
            'importance': 1,
            'level': 3
        }
        
        preview_response = self.client.post(url, {
            'action': 'preview',
            'selected_competencies': f"{self.cc1.id}",
            'custom_competencies': [json.dumps(custom_comp)]
        })
        
        self.assertEqual(preview_response.status_code, 200)
        self.assertTemplateUsed(preview_response, 'jobs/partials/competency_preview_table.html')
        self.assertContains(preview_response, 'آزمون کتبی')
        self.assertContains(preview_response, 'کانون ارزیابی')

    def test_custom_competencies_persistence(self):
        """تست ذخیره‌سازی صحیح شایستگی‌های دستی در دیتابیس با فلگ is_custom=True"""
        url = reverse('job_competency_config', kwargs={'job_id': self.job.id})
        import json
        custom_comp = {
            'title': 'مهارت برنامه نویسی پایتون دستی',
            'competency_type': 'SK',
            'importance': 2,
            'level': 2
        }
        
        data = {
            'action': 'save',
            'selected_competencies': [self.cc1.id],
            'custom_competencies': [json.dumps(custom_comp)]
        }
        
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        
        # Verify from database
        self.job.refresh_from_db()
        selected = self.job.selected_competencies.filter(is_deleted=False)
        self.assertEqual(selected.count(), 2)
        
        custom_db = selected.filter(is_custom=True).first()
        self.assertIsNotNone(custom_db)
        self.assertEqual(custom_db.title, 'مهارت برنامه نویسی پایتون دستی')
        self.assertEqual(custom_db.competency_type, 'SK')
        self.assertEqual(custom_db.importance, 2)
        self.assertEqual(custom_db.level, 2)
        self.assertTrue(custom_db.is_custom)

    def test_custom_competencies_report_view_and_csv(self):
        """تست صفحه گزارش شایستگی‌های دستی و صحت خروجی CSV"""
        # Create a custom competency for test
        custom_jc = JobOpportunityCompetency.objects.create(
            job=self.job,
            code='MANUAL-TEST-123',
            title='شایستگی تست دستی گزارش',
            competency_type='GE',
            importance=1,
            level=3,
            is_custom=True
        )
        
        url = reverse('custom_competencies_report')
        
        # 1. HTML view rendering
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'jobs/custom_competencies_report.html')
        self.assertContains(response, 'شایستگی تست دستی گزارش')
        
        # 2. Filtering by query search 'تست دستی'
        response_filtered = self.client.get(url, {'q': 'تست دستی'})
        self.assertEqual(response_filtered.status_code, 200)
        self.assertContains(response_filtered, 'شایستگی تست دستی گزارش')
        
        response_empty = self.client.get(url, {'q': 'غیرموجود'})
        self.assertEqual(response_empty.status_code, 200)
        self.assertNotContains(response_empty, 'شایستگی تست دستی گزارش')
        
        # 3. CSV export download
        csv_response = self.client.get(url + '?export=csv')
        self.assertEqual(csv_response.status_code, 200)
        self.assertEqual(csv_response['Content-Type'], 'text/csv; charset=utf-8-sig')
        self.assertTrue(csv_response['Content-Disposition'].startswith('attachment; filename='))
        
        # Decode response content and check headers and values
        content_str = csv_response.content.decode('utf-8-sig')
        self.assertIn('عنوان شایستگی', content_str)
        self.assertIn('شایستگی تست دستی گزارش', content_str)

        # 4. Role restriction test (Department user should be forbidden)
        self.client.logout()
        dept_user = User.objects.create_user(username='dept_user', password='password123')
        from apps.accounts.models import UserProfile
        dept_user.profile.role = UserProfile.ROLE_DEPARTMENT_USER
        dept_user.profile.save()
        self.client.login(username='dept_user', password='password123')
        
        forbidden_response = self.client.get(url)
        self.assertEqual(forbidden_response.status_code, 403)


class SearchCompetenciesApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='admin_test', password='password123')
        self.user.profile.role = 'ADMIN'
        self.user.profile.save()
        self.client.login(username='admin_test', password='password123')

        CentralCompetency.objects.create(
            post_code='TEST-01', post_title='Test Title', code='KN_TEST_01', title='Python Mastery',
            competency_type='KN', category_raw='KN- دانش', cluster_raw='3-عمومی', importance=1, level=2
        )
        CentralCompetency.objects.create(
            post_code='TEST-02', post_title='Test Title 2', code='KN_TEST_02', title='Django Competency',
            competency_type='SK', category_raw='SK- مهارت', cluster_raw='3-عمومی', importance=2, level=3
        )
        # Duplicate title to verify deduplication
        CentralCompetency.objects.create(
            post_code='TEST-03', post_title='Test Title 3', code='KN_TEST_03', title='Python Mastery',
            competency_type='KN', category_raw='KN- دانش', cluster_raw='3-عمومی', importance=1, level=2
        )

    def test_search_competencies_success(self):
        url = reverse('search_competencies_api')
        response = self.client.get(url, {'q': 'Python'})
        self.assertEqual(response.status_code, 200)
        
        import json
        data = json.loads(response.content)
        self.assertIn('items', data)
        self.assertEqual(len(data['items']), 1) # Deduplicated
        self.assertEqual(data['items'][0]['title'], 'Python Mastery')
        self.assertEqual(data['items'][0]['competency_type'], 'KN')
        self.assertEqual(data['items'][0]['importance'], 1)
        self.assertEqual(data['items'][0]['level'], 2)

    def test_search_competencies_no_query(self):
        url = reverse('search_competencies_api')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        import json
        data = json.loads(response.content)
        self.assertEqual(len(data['items']), 2) # Both competencies returned (unique by title)


class JobOpportunityCascadeDeleteTests(TestCase):
    def setUp(self):
        self.recruiter = User.objects.create_user(username='test_user', password='password123')
        
        self.job = JobOpportunity.objects.create(
            request_number='REQ-DEL-1',
            title='Job to delete',
            code='DEL-01',
            department='Test Dep'
        )
        
        self.stage = JobOpportunityStage.objects.create(
            job=self.job,
            name='Test Stage',
            weight=100,
            sequence=1,
            stage_type='INTERVIEW'
        )
        
        # Create AssessmentCompetency
        from apps.jobs.models import AssessmentCompetency
        self.ac = AssessmentCompetency.objects.create(
            stage=self.stage,
            name='Cognitive ability',
            weight=100
        )
        
        # Create JobOpportunityCompetency
        self.joc = JobOpportunityCompetency.objects.create(
            job=self.job,
            code='JOC-01',
            title='Skill Title',
            competency_type='SK',
            importance=1,
            level=2,
            is_custom=True
        )

    def test_job_opportunity_cascade_delete(self):
        job_pk = self.job.pk
        stage_pk = self.stage.pk
        ac_pk = self.ac.pk
        joc_pk = self.joc.pk
        
        # Delete job opportunity
        self.job.delete()
        
        # Verify job is soft deleted
        self.assertFalse(JobOpportunity.objects.filter(pk=job_pk).exists())
        self.assertTrue(JobOpportunity.all_objects.get(pk=job_pk).is_deleted)
        
        # Verify stage is soft deleted
        self.assertFalse(JobOpportunityStage.objects.filter(pk=stage_pk).exists())
        self.assertTrue(JobOpportunityStage.all_objects.get(pk=stage_pk).is_deleted)
        
        # Verify AssessmentCompetency is soft deleted
        from apps.jobs.models import AssessmentCompetency
        self.assertFalse(AssessmentCompetency.objects.filter(pk=ac_pk).exists())
        self.assertTrue(AssessmentCompetency.all_objects.get(pk=ac_pk).is_deleted)
        
        # Verify JobOpportunityCompetency is soft deleted
        self.assertFalse(JobOpportunityCompetency.objects.filter(pk=joc_pk).exists())
        self.assertTrue(JobOpportunityCompetency.all_objects.get(pk=joc_pk).is_deleted)


class AssessmentPlanRoundingTests(TestCase):
    def test_calculate_assessment_plan_rounding_to_five(self):
        from apps.jobs.utils import calculate_assessment_plan
        
        class MockComp:
            def __init__(self, code, title, competency_type, importance, level):
                self.code = code
                self.title = title
                self.competency_type = competency_type
                self.importance = importance
                self.level = level

        comps = [
            MockComp('C1', 'Comp 1', 'KN', 1, 2),
            MockComp('C2', 'Comp 2', 'SK', 2, 3),
            MockComp('C3', 'Comp 3', 'GE', 1, 1),
        ]
        
        # Test with round_to_five = True
        res = calculate_assessment_plan(comps, round_to_five=True)
        stages = res['stages']
        
        # Verify that all stage weights are multiples of 5
        for s in stages.values():
            self.assertEqual(s['weight'] % 5, 0)
        self.assertEqual(sum(s['weight'] for s in stages.values()), 100)

        # Test with round_to_five = False
        res_false = calculate_assessment_plan(comps, round_to_five=False)
        stages_false = res_false['stages']
        # The weights shouldn't all be multiples of 5 (e.g. EXAM might be 28 or 29)
        has_non_multiple_of_five = any(s['weight'] % 5 != 0 for s in stages_false.values())
        self.assertTrue(has_non_multiple_of_five)


class RecruitmentPatternSimulatorTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_superuser(username='admin_test', password='password123')
        self.user.profile.role = 'ADMIN'
        self.user.profile.save()
        self.client.login(username='admin_test', password='password123')

        # Create CentralCompetency entries
        CentralCompetency.objects.create(
            post_code='DEV-01', post_title='برنامه‌نویس نرم‌افزار', code='KN-01', title='Python Programming',
            competency_type='KN', category_raw='KN- دانش', cluster_raw='3-عمومی', importance=1, level=3
        )
        CentralCompetency.objects.create(
            post_code='DEV-01', post_title='برنامه‌نویس نرم‌افزار', code='SK-01', title='Django Web Framework',
            competency_type='SK', category_raw='SK- مهارت', cluster_raw='3-عمومی', importance=1, level=2
        )
        CentralCompetency.objects.create(
            post_code='MGR-01', post_title='Project Manager', code='GE-01', title='Leadership Skills',
            competency_type='GE', category_raw='GE- رفتاری', cluster_raw='3-عمومی', importance=1, level=3
        )
        CentralCompetency.objects.create(
            post_code='MGR-01', post_title='Project Manager', code='KN-02', title='Python Programming',
            competency_type='KN', category_raw='KN- دانش', cluster_raw='3-عمومی', importance=2, level=2
        )

        # Create Candidate and candidate skills/experience
        from apps.candidates.models import Candidate, CandidateSkill, CandidateExperience
        self.candidate = Candidate.objects.create(
            first_name='Ali', last_name='Alavi', phone_number='09123456789', national_id='1234567890'
        )
        CandidateSkill.objects.create(
            candidate=self.candidate, name='Python Programming', level='EXPERT'
        )
        CandidateExperience.objects.create(
            candidate=self.candidate, company='Test Co', job_title='برنامه‌نویس نرم‌افزار', start_date='2020-01-01'
        )

        # Create Job Opportunity for MGR-01 so it has competency overlap
        from apps.jobs.models import JobOpportunity, JobOpportunityCompetency
        from apps.candidates.models import JobApplication
        
        job_mgr = JobOpportunity.objects.create(
            request_number='REQ-MGR1',
            title='Project Manager',
            code='MGR-01',
            status=JobOpportunity.STATUS_PUBLISHED
        )
        JobOpportunityCompetency.objects.create(
            job=job_mgr,
            code='KN-02',
            title='Python Programming',
            competency_type='KN',
            importance=2,
            level=2
        )
        JobOpportunityCompetency.objects.create(
            job=job_mgr,
            code='GE-01',
            title='Leadership Skills',
            competency_type='GE',
            importance=1,
            level=3
        )
        
        # Create JobApplication for candidate in job_mgr with score 70.0
        JobApplication.objects.create(
            job=job_mgr,
            candidate=self.candidate,
            status=JobApplication.STATUS_IN_PROGRESS,
            final_score=70.0
        )

    def test_dashboard_main_view(self):
        url = reverse('recruitment_patterns')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'توزیع انواع شایستگی‌ها')
        self.assertContains(response, 'شبیه‌ساز هوشمند آماده به کار است')

    def test_simulator_simulate_action(self):
        url = reverse('recruitment_patterns')
        response = self.client.get(url, {'action': 'simulate', 'post_code': 'DEV-01', 'round': 'true'})
        self.assertEqual(response.status_code, 200)
        # Should render post_pattern_simulation.html content
        self.assertContains(response, 'برنامه‌نویس نرم‌افزار')
        self.assertContains(response, 'Python Programming')
        self.assertContains(response, 'Django Web Framework')
        
        # Talent matching verification
        self.assertContains(response, 'Ali Alavi')
        self.assertContains(response, 'Python Programming')
        
        # Similar post verification
        self.assertContains(response, 'Project Manager') # Shares 'Python Programming'

    def test_simulator_ai_advise_action(self):
        url = reverse('recruitment_patterns')
        response = self.client.get(url, {'action': 'ai_advise', 'post_code': 'DEV-01'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'راهبرد استخدامی و ارزیابی پیشنهادی هوش مصنوعی')
        self.assertContains(response, 'آزمون مهارتی به میزان 40٪')

    def test_simulator_ai_advise_other_post_title(self):
        url = reverse('recruitment_patterns')
        response = self.client.get(url, {'action': 'ai_advise', 'post_code': 'MGR-01'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'راهبرد استخدامی')
        self.assertContains(response, 'آزمون کتبی به میزان 30٪')

    def test_simulator_candidate_match_score(self):
        url = reverse('recruitment_patterns')
        response = self.client.get(url, {'action': 'simulate', 'post_code': 'DEV-01'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '50٪ تطابق')

    def test_simulator_competency_overlap(self):
        from apps.jobs.models import CentralCompetency, JobOpportunity, JobOpportunityCompetency
        url = reverse('recruitment_patterns')
        
        # 1. Create two active JobOpportunity instances
        job1 = JobOpportunity.objects.create(
            request_number='REQ-101',
            title='برنامه‌نویس بک‌اند',
            code='DEV-01',
            status=JobOpportunity.STATUS_PUBLISHED
        )
        JobOpportunityCompetency.objects.create(
            job=job1,
            code='KN-01',
            title='Python Programming',
            competency_type='KN',
            importance=1,
            level=3
        )
        JobOpportunityCompetency.objects.create(
            job=job1,
            code='SK-01',
            title='Django Web Framework',
            competency_type='SK',
            importance=1,
            level=3
        )
        
        job2 = JobOpportunity.objects.create(
            request_number='REQ-102',
            title='برنامه‌نویس پایتون',
            code='DEV-XX',
            status=JobOpportunity.STATUS_PUBLISHED
        )
        JobOpportunityCompetency.objects.create(
            job=job2,
            code='KN-XX',
            title='Python Programming',
            competency_type='KN',
            importance=1,
            level=3
        )
        JobOpportunityCompetency.objects.create(
            job=job2,
            code='SK-XX',
            title='Django Web Framework',
            competency_type='SK',
            importance=1,
            level=3
        )
        
        # Now fetch dashboard page and verify overlap suggestions widget contains the shared suggestion between active JobOpportunities
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'برنامه‌نویس بک‌اند')
        self.assertContains(response, 'برنامه‌نویس پایتون')
        self.assertContains(response, 'آزمون کتبی')
        self.assertContains(response, 'آزمون مهارتی')
        
        # 2. Create DEV-XX in CentralCompetency so simulate action can match DEV-XX to check overlap
        CentralCompetency.objects.create(
            post_code='DEV-XX',
            post_title='توسعه‌دهنده پایتون',
            code='COMP-XX-1',
            title='Python Programming',
            competency_type='SK',
            importance=1,
            level=3
        )
        CentralCompetency.objects.create(
            post_code='DEV-XX',
            post_title='توسعه‌دهنده پایتون',
            code='COMP-XX-2',
            title='Django Web Framework',
            competency_type='SK',
            importance=1,
            level=3
        )

        # 3. Simulate DEV-01. Since DEV-XX has an active job opportunity, it should be highlighted as active!
        response = self.client.get(url, {'action': 'simulate', 'post_code': 'DEV-01'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ارزیابی‌های مشترک پیشنهادی')
        self.assertContains(response, 'توسعه‌دهنده پایتون')
        self.assertContains(response, '100٪')
        self.assertContains(response, 'فرصت شغلی فعال در جریان')
        self.assertContains(response, 'ارزیابی مهارتی مشترک')

    def test_simulator_auto_loads_cached_ai(self):
        from apps.jobs.models import AIPostRecommendation
        url = reverse('recruitment_patterns')
        
        # 1. Without cache: simulate action should render the manual advice button
        response = self.client.get(url, {'action': 'simulate', 'post_code': 'DEV-01'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'تولید سناریو و راهبرد استخدامی هوشمند')
        
        # 2. Add cached recommendation
        AIPostRecommendation.objects.create(
            post_code='DEV-01',
            opt_advice=[{"text": "Cached Advice"}],
            scenario="Cached Scenario",
            questions=["Cached Question"],
            benchmark_mappings=[]
        )
        
        # 3. With cache: simulate action should render the cached advice directly and NOT render the manual button
        response = self.client.get(url, {'action': 'simulate', 'post_code': 'DEV-01'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cached Advice')
        self.assertContains(response, 'Cached Scenario')
        self.assertNotContains(response, 'تولید سناریو و راهبرد استخدامی هوشمند')

    def test_ai_strategy_print_view(self):
        url = reverse('job_ai_strategy_print')
        response = self.client.get(url, {'post_code': 'DEV-01'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'توصیه‌های بهینه‌سازی شایستگی‌ها')
        self.assertContains(response, 'حالت پیش‌فرض آفلاین')

    def test_ai_competency_filtering(self):
        from apps.jobs.views import get_ai_recommendation
        class MockComp:
            def __init__(self, title, competency_type, importance=1, level=3, code='C-01'):
                self.title = title
                self.competency_type = competency_type
                self.importance = importance
                self.level = level
                self.code = code

        comps = [
            MockComp('Leadership Skills', 'GE'),
            MockComp('امنیت سایبری', 'KN'),
            MockComp('برنامه‌نویسی پایتون', 'KN'),
        ]

        result = get_ai_recommendation('TEST-P', 'Test Post', comps, refresh=True)
        questions = result['questions']
        self.assertTrue(any('برنامه‌نویسی پایتون' in q['question'] for q in questions))
        self.assertFalse(any('Leadership Skills' in q['question'] for q in questions))
        self.assertFalse(any('امنیت سایبری' in q['question'] for q in questions))

    def test_ai_advise_caching_and_refresh(self):
        from apps.jobs.models import AIPostRecommendation, AISetting
        url = reverse('recruitment_patterns')
        
        # Verify no cache initially exists
        self.assertEqual(AIPostRecommendation.objects.filter(post_code='DEV-01').count(), 0)

        # Create active live API setting
        setting = AISetting.objects.create(
            api_key='fake-api-key',
            base_url='http://localhost:8000',
            model_name='gpt-4o',
            is_active=True
        )

        from unittest.mock import patch, MagicMock
        mock_response_content = (
            '{"choices": [{"message": {"content": "{\\"opt_advice\\": [{\\"text\\": \\"Advice Live\\", \\"weights\\": {\\"EXAM\\": 40}}], \\"scenario\\": \\"Scenario Live\\", \\"questions\\": [{\\"competency\\": \\"Comp Live\\", \\"question\\": \\"Question Live\\", \\"criteria\\": \\"Criteria Live\\"}], \\"benchmark_mappings\\": [{\\"competency\\": \\"Comp Live\\", \\"framework\\": \\"Framework Live\\", \\"dimension\\": \\"Dim Live\\", \\"tool\\": \\"Tool Live\\", \\"behavioral_indicators\\": [\\"Ind 1\\"], \\"pass_benchmark\\": \\"3.5\\", \\"rationale\\": \\"Rationale Live\\"}]}"}}]}'
        )
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = mock_response_content.encode('utf-8')
        mock_response.__enter__.return_value = mock_response

        with patch('urllib.request.urlopen', return_value=mock_response) as mock_urlopen:
            # 1. Fetch live advice - should call the API and write to cache
            response = self.client.get(url, {'action': 'ai_advise', 'post_code': 'DEV-01'})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Advice Live')
            self.assertContains(response, 'Framework Live')
            mock_urlopen.assert_called_once()
            
            # Verify cache entry created
            self.assertEqual(AIPostRecommendation.objects.filter(post_code='DEV-01').count(), 1)
            rec = AIPostRecommendation.objects.get(post_code='DEV-01')
            self.assertEqual(rec.scenario, 'Scenario Live')
            self.assertEqual(rec.benchmark_mappings, [
                {"competency": "Comp Live", "framework": "Framework Live", "dimension": "Dim Live", "tool": "Tool Live", "behavioral_indicators": ["Ind 1"], "pass_benchmark": "3.5", "rationale": "Rationale Live"}
            ])

            # 2. Fetch again without refresh - should read from cache and NOT call urlopen again
            mock_urlopen.reset_mock()
            response = self.client.get(url, {'action': 'ai_advise', 'post_code': 'DEV-01'})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Advice Live')
            self.assertContains(response, 'Framework Live')
            self.assertContains(response, 'لود شده از کش')
            mock_urlopen.assert_not_called()

            # 3. Fetch again with refresh=True - should bypass cache and call urlopen again
            mock_urlopen.reset_mock()
            response = self.client.get(url, {'action': 'ai_advise', 'post_code': 'DEV-01', 'refresh': 'true'})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Advice Live')
            self.assertContains(response, 'Framework Live')
            mock_urlopen.assert_called_once()

    def test_simulator_similar_posts_peer_filtering(self):
        from apps.jobs.models import CentralCompetency
        
        CentralCompetency.objects.create(
            post_code='FE-01', post_title='کارشناس فرانت‌اند', code='KN-FE-01', title='Python Programming',
            competency_type='KN', category_raw='KN- دانش', cluster_raw='3-عمومی', importance=1, level=3
        )
        
        CentralCompetency.objects.create(
            post_code='NET-01', post_title='کاردان شبکه', code='KN-NET-01', title='Python Programming',
            competency_type='KN', category_raw='KN- دانش', cluster_raw='3-عمومی', importance=1, level=3
        )
        
        CentralCompetency.objects.create(
            post_code='BE-01', post_title='کارشناس بک‌اند', code='KN-BE-01', title='Python Programming',
            competency_type='KN', category_raw='KN- دانش', cluster_raw='3-عمومی', importance=1, level=3
        )
        
        # Simulate FE-01 (category: 'کارشناس')
        url = reverse('recruitment_patterns')
        response = self.client.get(url, {'action': 'simulate', 'post_code': 'FE-01'})
        self.assertEqual(response.status_code, 200)
        
        # Verify that similar_posts context variable contains the peer but excludes other categories
        similar_post_codes = [sp['post_code'] for sp in response.context['similar_posts']]
        self.assertIn('BE-01', similar_post_codes)
        self.assertNotIn('NET-01', similar_post_codes)
        self.assertNotIn('DEV-01', similar_post_codes)


class AISettingViewAndApiTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.admin = User.objects.create_superuser(username='admin_test2', password='password123')
        self.admin.profile.role = 'ADMIN'
        self.admin.profile.save()
        
        self.non_admin = User.objects.create_user(username='normal_test', password='password123')
        self.non_admin.profile.role = 'RECRUITMENT_SPECIALIST'
        self.non_admin.profile.save()

    def test_ai_settings_access_restricted(self):
        # Normal user shouldn't access
        self.client.login(username='normal_test', password='password123')
        url = reverse('ai_setting')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        
    def test_ai_settings_admin_access(self):
        # Admin should access
        self.client.login(username='admin_test2', password='password123')
        url = reverse('ai_setting')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'پیکربندی سرویس دهنده هوش مصنوعی')
        
    def test_ai_settings_save(self):
        self.client.login(username='admin_test2', password='password123')
        url = reverse('ai_setting')
        post_data = {
            'action': 'save',
            'api_key': 'test-api-key',
            'base_url': 'https://api.openai.com/v1',
            'model_name': 'gpt-4o',
            'is_active': 'on'
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302) # Redirects back
        
        # Verify saved in DB
        from apps.jobs.models import AISetting
        setting = AISetting.get_active_setting()
        self.assertIsNotNone(setting)
        self.assertEqual(setting.api_key, 'test-api-key')
        self.assertEqual(setting.base_url, 'https://api.openai.com/v1')
        self.assertEqual(setting.model_name, 'gpt-4o')

    def test_ai_settings_test_connection_fail(self):
        self.client.login(username='admin_test2', password='password123')
        url = reverse('ai_setting')
        
        # Test with empty API key
        post_data = {
            'action': 'test_connection',
            'api_key': '',
            'base_url': 'https://api.openai.com/v1',
            'model_name': 'gpt-4o'
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'لطفاً کلید API را وارد کنید')

    def test_ai_settings_test_connection_mock_success(self):
        self.client.login(username='admin_test2', password='password123')
        url = reverse('ai_setting')
        post_data = {
            'action': 'test_connection',
            'api_key': 'mock_key',
            'base_url': 'https://api.openai.com/v1',
            'model_name': 'gpt-4o'
        }
        
        # Mock urllib.request.urlopen
        from unittest.mock import patch, MagicMock
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.status = 200
        mock_response.read.return_value = b'{"choices": [{"message": {"content": "Connected"}}]}'
        
        with patch('urllib.request.urlopen', return_value=mock_response) as mock_urlopen:
            response = self.client.post(url, post_data)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'اتصال زنده با موفقیت برقرار شد')
            mock_urlopen.assert_called_once()

    def test_ai_advise_action_live_api_mock(self):
        # 1. Save an active AISetting in DB
        from apps.jobs.models import AISetting, CentralCompetency
        AISetting.objects.create(
            api_key='live-key',
            base_url='https://api.avalai.ir/v1',
            model_name='gpt-4o',
            is_active=True
        )
        
        # Create competency for DEV-02 (isolated test)
        CentralCompetency.objects.create(
            post_code='DEV-02', post_title='طراح سیستم', code='KN-99', title='System Design',
            competency_type='KN', category_raw='KN- دانش', cluster_raw='3-عمومی', importance=1, level=3
        )
        
        self.client.login(username='admin_test2', password='password123')
        url = reverse('recruitment_patterns')
        
        from unittest.mock import patch, MagicMock
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.status = 200
        mock_response.read.return_value = b'{"choices": [{"message": {"content": "{\\"opt_advice\\": [\\"Live Tip 1\\", \\"Live Tip 2\\", \\"Live Tip 3\\"], \\"scenario\\": \\"Live Scenario\\", \\"questions\\": [\\"Live Q1\\", \\"Live Q2\\", \\"Live Q3\\"]}"}}]}'
        
        with patch('urllib.request.urlopen', return_value=mock_response) as mock_urlopen:
            response = self.client.get(url, {'action': 'ai_advise', 'post_code': 'DEV-02'})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Live API')
            self.assertContains(response, 'Live Tip 1')
            self.assertContains(response, 'Live Scenario')
            self.assertContains(response, 'Live Q1')
            mock_urlopen.assert_called_once()


class SmartTalentMatchingTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from apps.accounts.models import UserProfile
        from apps.jobs.models import CentralCompetency, JobOpportunity, JobOpportunityCompetency
        from apps.candidates.models import Candidate, JobApplication
        
        # Setup users
        self.admin = User.objects.create_superuser(username='matching_admin', password='password123')
        self.admin.profile.role = UserProfile.ROLE_ADMIN
        self.admin.profile.save()
        self.client.login(username='matching_admin', password='password123')

        # 1. Create Target Post Competencies in CentralCompetency bank
        # Functional competencies (KN, SK, AB)
        CentralCompetency.objects.create(
            post_code='TARGET-POST', post_title='شغل هدف', code='TC-01', title='مهارت برنامه‌نویسی پایتون',
            competency_type='SK', importance=1, level=3
        )
        CentralCompetency.objects.create(
            post_code='TARGET-POST', post_title='شغل هدف', code='TC-02', title='دانش طراحی الگوریتم',
            competency_type='KN', importance=1, level=2
        )
        CentralCompetency.objects.create(
            post_code='TARGET-POST', post_title='شغل هدف', code='TC-03', title='توانایی کار تیمی',
            competency_type='AB', importance=2, level=2
        )
        # Organizational competency (should be ignored by matches)
        CentralCompetency.objects.create(
            post_code='TARGET-POST', post_title='شغل هدف', code='TC-04', title='تاب‌آوری',
            competency_type='GE', importance=2, level=2
        )

        # 2. Create Similar Job Opportunity (JOB-A: 2 shared out of 3 functional -> 67% overlap >= 50%)
        self.job_a = JobOpportunity.objects.create(
            request_number='REQ-JOBA', title='توسعه‌دهنده پایتون ارشد', code='JOB-A', status=JobOpportunity.STATUS_PUBLISHED
        )
        JobOpportunityCompetency.objects.create(
            job=self.job_a, code='JA-01', title='مهارت برنامه‌نویسی پایتون', competency_type='SK', importance=1, level=3
        )
        JobOpportunityCompetency.objects.create(
            job=self.job_a, code='JA-02', title='دانش طراحی الگوریتم', competency_type='KN', importance=1, level=3
        )

        # 3. Create Dissimilar Job Opportunity (JOB-B: 1 shared out of 3 functional -> 33% overlap < 50%)
        self.job_b = JobOpportunity.objects.create(
            request_number='REQ-JOBB', title='کارشناس امنیت شبکه', code='JOB-B', status=JobOpportunity.STATUS_PUBLISHED
        )
        JobOpportunityCompetency.objects.create(
            job=self.job_b, code='JB-01', title='دانش طراحی الگوریتم', competency_type='KN', importance=1, level=3
        )

        # 4. Create Job C for final acceptance test
        self.job_c = JobOpportunity.objects.create(
            request_number='REQ-JOBC', title='شغل نهایی', code='JOB-C', status=JobOpportunity.STATUS_CLOSED
        )

        # 5. Create Candidates
        # Candidate 1: Ali (JOB-A, final_score = 80.0)
        self.cand_ali = Candidate.objects.create(
            first_name='علی', last_name='رضایی', phone_number='09121111111', national_id='1111111111'
        )
        JobApplication.objects.create(
            job=self.job_a, candidate=self.cand_ali, status=JobApplication.STATUS_IN_PROGRESS, final_score=80.0
        )

        # Candidate 2: Reza (JOB-A, final_score = 90.0)
        self.cand_reza = Candidate.objects.create(
            first_name='رضا', last_name='احمدی', phone_number='09122222222', national_id='2222222222'
        )
        JobApplication.objects.create(
            job=self.job_a, candidate=self.cand_reza, status=JobApplication.STATUS_IN_PROGRESS, final_score=90.0
        )

        # Candidate 3: Sara (JOB-A, final_score = 95.0, but accepted in JOB-C)
        self.cand_sara = Candidate.objects.create(
            first_name='سارا', last_name='کریمی', phone_number='09123333333', national_id='3333333333'
        )
        JobApplication.objects.create(
            job=self.job_a, candidate=self.cand_sara, status=JobApplication.STATUS_IN_PROGRESS, final_score=95.0
        )
        # Accepted in JOB-C
        JobApplication.objects.create(
            job=self.job_c, candidate=self.cand_sara, status=JobApplication.STATUS_SELECTED, final_score=100.0
        )

        # Candidate 4: Gholi (JOB-B, final_score = 99.0)
        self.cand_gholi = Candidate.objects.create(
            first_name='قلی', last_name='قلی‌پور', phone_number='09124444444', national_id='4444444444'
        )
        JobApplication.objects.create(
            job=self.job_b, candidate=self.cand_gholi, status=JobApplication.STATUS_IN_PROGRESS, final_score=99.0
        )

    def test_optimized_talent_matching(self):
        url = reverse('recruitment_patterns')
        response = self.client.get(url, {'action': 'simulate', 'post_code': 'TARGET-POST'})
        self.assertEqual(response.status_code, 200)
        
        talents = response.context['talents']
        # Sara (selected in Job C) and Gholi (overlap 33% < 50%) must be excluded
        # Ali and Reza must be present
        self.assertEqual(len(talents), 2)
        
        # Sorted by final_score descending -> Reza (90%) then Ali (80%)
        self.assertEqual(talents[0]['id'], self.cand_reza.id)
        self.assertEqual(talents[0]['source_job_score'], 90)
        self.assertEqual(talents[0]['source_job_title'], 'توسعه‌دهنده پایتون ارشد')
        self.assertEqual(talents[0]['match_percent'], 67) # 2/3 * 100
        self.assertIn('دانش طراحی الگوریتم', talents[0]['shared_competencies'])
        self.assertIn('مهارت برنامه‌نویسی پایتون', talents[0]['shared_competencies'])

        self.assertEqual(talents[1]['id'], self.cand_ali.id)
        self.assertEqual(talents[1]['source_job_score'], 80)

    def test_ai_match_talent_scores_endpoint_offline_fallback(self):
        url = reverse('recruitment_patterns')
        response = self.client.get(url, {
            'action': 'ai_match_talent_scores',
            'post_code': 'TARGET-POST',
            'candidate_id': self.cand_reza.id
        })
        self.assertEqual(response.status_code, 200)
        
        # Test rendered components of the modal layout
        self.assertTemplateUsed(response, 'jobs/partials/ai_talent_suitability_match.html')
        self.assertContains(response, 'رضا احمدی')
        self.assertContains(response, 'توسعه‌دهنده پایتون ارشد')
        self.assertContains(response, '90٪')
        self.assertContains(response, '67٪ همپوشانی شایستگی‌ها')
        # Offline fallback text
        self.assertContains(response, 'صلاحیت عمومی کاندیدا در این بخش‌ها مطلوب')

    def test_ai_match_talent_scores_endpoint_live(self):
        from apps.jobs.models import AISetting
        AISetting.objects.create(
            api_key='fake-api-key',
            base_url='http://localhost:8000',
            model_name='gpt-4o',
            is_active=True
        )

        url = reverse('recruitment_patterns')
        
        from unittest.mock import patch, MagicMock
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.status = 200
        mock_response.read.return_value = b'{"choices": [{"message": {"content": "Live AI analysis for transferability."}}]}'
        
        with patch('urllib.request.urlopen', return_value=mock_response) as mock_urlopen:
            response = self.client.get(url, {
                'action': 'ai_match_talent_scores',
                'post_code': 'TARGET-POST',
                'candidate_id': self.cand_reza.id
            })
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, 'jobs/partials/ai_talent_suitability_match.html')
            self.assertContains(response, 'Live AI analysis for transferability.')
            mock_urlopen.assert_called_once()


class JobOpportunityStageSyncTests(TestCase):
    def setUp(self):
        from apps.jobs.models import JobOpportunity, JobOpportunityStage
        from apps.candidates.models import Candidate, JobApplication
        
        # 1. Create a JobOpportunity
        self.job = JobOpportunity.objects.create(
            title='مهندس DevOps',
            code='DEVOPS-01',
            status=JobOpportunity.STATUS_PUBLISHED
        )
        
        # 2. Add initial stages: SCREENING (seq 1), EXAM (seq 2)
        self.stage_screening = JobOpportunityStage.objects.create(
            job=self.job,
            name='غربالگری اولیه',
            weight=10,
            sequence=1,
            stage_type='SCREENING'
        )
        self.stage_exam = JobOpportunityStage.objects.create(
            job=self.job,
            name='آزمون کتبی فنی',
            weight=40,
            sequence=2,
            stage_type='EXAM'
        )
        
        # 3. Create Candidate & Application
        self.cand = Candidate.objects.create(
            first_name='بابک',
            last_name='بابایی',
            phone_number='09129999999',
            national_id='9999999999'
        )
        self.app = JobApplication.objects.create(
            job=self.job,
            candidate=self.cand,
            status=JobApplication.STATUS_IN_PROGRESS
        )
        # JobApplication creation automatically recalculates and sets current_stage to first stage (screening)
        # and creates ApplicationStageState records for all stages.

    def test_sync_application_stages_workflow_and_scores(self):
        from apps.jobs.models import JobOpportunityStage
        from apps.candidates.models import ApplicationStageState
        from django.utils import timezone
        
        # Verify initial states
        states = self.app.stage_states.filter(is_deleted=False)
        self.assertEqual(states.count(), 2)
        
        scr_state = states.get(stage__stage_type='SCREENING')
        self.assertEqual(scr_state.status, ApplicationStageState.STATUS_PENDING)
        
        # Complete screening stage
        scr_state.status = ApplicationStageState.STATUS_COMPLETED
        scr_state.score = 100.0
        scr_state.save()
        
        # Re-fetch app to see current_stage changed to EXAM
        self.app.recalculate_current_stage(save=True)
        self.assertEqual(self.app.current_stage, self.stage_exam)
        
        # Now, simulate a workflow/competency update:
        # Soft delete the EXAM stage and add an INTERVIEW stage instead.
        self.stage_exam.is_deleted = True
        self.stage_exam.deleted_at = timezone.now()
        self.stage_exam.save()
        
        stage_interview = JobOpportunityStage.objects.create(
            job=self.job,
            name='مصاحبه عمومی و تخصصی',
            weight=50,
            sequence=2,
            stage_type='INTERVIEW'
        )
        
        # Call the sync method on the job
        self.job.sync_application_stages()
        
        # Verify changes:
        # 1. Screen state should still exist, point to the screening stage, and retain its status/score
        states_after = self.app.stage_states.filter(is_deleted=False)
        self.assertEqual(states_after.count(), 2) # SCREENING and INTERVIEW
        
        scr_state_after = states_after.get(stage__stage_type='SCREENING')
        self.assertEqual(scr_state_after.status, ApplicationStageState.STATUS_COMPLETED)
        self.assertEqual(scr_state_after.score, 100.0)
        
        # 2. Exam state should be soft-deleted
        self.assertFalse(self.app.stage_states.filter(stage__stage_type='EXAM', is_deleted=False).exists())
        
        # 3. Interview state should be created as PENDING
        int_state_after = states_after.get(stage__stage_type='INTERVIEW')
        self.assertEqual(int_state_after.status, ApplicationStageState.STATUS_PENDING)
        self.assertEqual(int_state_after.score, 0.0)
        
        # 4. Re-fetch app to verify its current_stage is now updated to INTERVIEW
        self.app.refresh_from_db()
        self.assertEqual(self.app.current_stage, stage_interview)


class CompetencyModelViewsTests(TestCase):
    def setUp(self):
        from apps.accounts.models import UserProfile
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.user = User.objects.create_user(username='testadmin', password='password123', email='test@example.com')
        self.profile = self.user.profile
        self.profile.role = UserProfile.ROLE_ADMIN
        self.profile.save()
        self.client.login(username='testadmin', password='password123')
        
        from apps.jobs.models import CompetencyModel
        self.model = CompetencyModel.objects.create(name="مدل ارزیابی پایه", description="توضیحات مدل")

    def test_list_view_without_htmx_with_model_id(self):
        """تست اینکه درخواست غیر HTMX با model_id کل قالب را لود کند نه پارشیال را"""
        url = reverse('competency_model_list')
        response = self.client.get(url, {'model_id': self.model.id})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'jobs/competency_model_list.html')
        self.assertContains(response, "مدل‌های شایستگی سازمانی")
        self.assertEqual(response.context['selected_model'], self.model)

    def test_list_view_with_htmx_with_model_id(self):
        """تست اینکه درخواست HTMX با model_id فقط قالب پارشیال جزئیات را رندر کند"""
        url = reverse('competency_model_list')
        response = self.client.get(url, {'model_id': self.model.id}, headers={'HX-Request': 'true'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'jobs/partials/competency_model_detail.html')
        self.assertContains(response, self.model.name)
        self.assertNotContains(response, "مدل‌های شایستگی سازمانی")

    def test_item_add_without_htmx_redirects(self):
        """تست اینکه افزودن شایستگی بدون HTMX کاربر را ریدایرکت کند"""
        url = reverse('competency_model_item_manage', kwargs={'model_id': self.model.id})
        data = {
            'title': 'شایستگی تست جدید',
            'competency_type': 'SK',
            'importance': '2',
            'level': '3'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        expected_redirect = reverse('competency_model_list') + f'?model_id={self.model.id}'
        self.assertRedirects(response, expected_redirect)
        
        self.assertEqual(self.model.items.filter(is_deleted=False).count(), 1)
        item = self.model.items.filter(is_deleted=False).first()
        self.assertEqual(item.title, 'شایستگی تست جدید')
        self.assertEqual(item.competency_type, 'SK')

    def test_item_add_with_htmx_returns_partial(self):
        """تست اینکه افزودن شایستگی با HTMX مستقیما پارشیال را رندر کند"""
        url = reverse('competency_model_item_manage', kwargs={'model_id': self.model.id})
        data = {
            'title': 'شایستگی مهارتی دوم',
            'competency_type': 'AB',
            'importance': '1',
            'level': '2'
        }
        response = self.client.post(url, data, headers={'HX-Request': 'true'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'jobs/partials/competency_model_detail.html')
        self.assertContains(response, 'شایستگی مهارتی دوم')
        self.assertEqual(self.model.items.filter(is_deleted=False).count(), 1)











