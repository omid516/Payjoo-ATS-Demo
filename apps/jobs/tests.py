from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.urls import reverse
from datetime import date, datetime
import jdatetime

from apps.jobs.models import WorkflowTemplate, WorkflowStageTemplate, JobOpportunity, JobOpportunityStage
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

    def test_workflow_template_creation(self):
        """تست ایجاد موفقیت‌آمیز قالب فرآیند کاری و مراحل پیش‌فرض آن"""
        self.assertEqual(self.workflow.stages.count(), 2)
        self.assertEqual(self.stage1.default_weight, 40)
        self.assertEqual(self.stage2.default_weight, 60)

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


