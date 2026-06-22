from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory, BaseInlineFormSet
from .models import JobOpportunity, JobOpportunityStage, WorkflowTemplate, WorkflowStageTemplate

class JobOpportunityForm(forms.ModelForm):
    start_date = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control date-picker', 'placeholder': '۱۴۰۲/۰۱/۰۱'}))
    end_date = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control date-picker', 'placeholder': '۱۴۰۲/۱۲/۲۹'}))
    code = forms.CharField(
        required=True,
        label="کد و عنوان پست سازمانی",
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_code'})
    )

    class Meta:
        model = JobOpportunity
        fields = [
            'request_number', 'title', 'code', 'department', 'unit', 'job_category',
            'headcount', 'recruitment_type', 'assigned_recruiter',
            'workflow', 'status', 'start_date', 'end_date', 'description', 'requirements', 'notes'
        ]
        widgets = {
            'request_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: REQ-1402-001'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: کارشناس ارشد برنامه‌نویسی Python'}),
            'department': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: مهندسی نرم‌افزار'}),
            'unit': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: بخش توسعه فرانت‌اند'}),
            'job_category': forms.Select(attrs={'class': 'form-select'}),
            'headcount': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'recruitment_type': forms.Select(attrs={'class': 'form-select'}),
            'assigned_recruiter': forms.Select(attrs={'class': 'form-select'}),
            'workflow': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'شرح وظایف و مسئولیت‌های شغلی'}),
            'requirements': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'سوابق کار، مهارت‌های تخصصی و مدارک تحصیلی مورد نیاز'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'یادداشت‌های اداری و داخلی جذب'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth.models import User
        from apps.accounts.models import UserProfile
        from apps.jobs.models import CentralCompetency
        
        self.fields['assigned_recruiter'].queryset = User.objects.exclude(
            profile__role=UserProfile.ROLE_CANDIDATE
        ).order_by('first_name', 'username')

        # Pre-populate code choices with the currently set post code
        if self.instance and self.instance.pk and self.instance.code:
            comps = CentralCompetency.objects.filter(post_code=self.instance.code, is_deleted=False)
            title = comps.first().post_title if comps.exists() else 'بدون عنوان'
            count = comps.count() if comps.exists() else 0
            self.fields['code'].widget.choices = [
                (self.instance.code, f"{self.instance.code} - {title} ({count} شایستگی)")
            ]
        else:
            self.fields['code'].widget.choices = [('', '-- انتخاب پست از بانک شایستگی --')]

        if self.instance and self.instance.pk:
            import jdatetime
            if self.instance.start_date:
                jd = jdatetime.date.fromgregorian(date=self.instance.start_date)
                self.initial['start_date'] = jd.strftime('%Y/%m/%d')
            if self.instance.end_date:
                jd = jdatetime.date.fromgregorian(date=self.instance.end_date)
                self.initial['end_date'] = jd.strftime('%Y/%m/%d')

    def clean_code(self):
        code = self.cleaned_data.get('code')
        from apps.jobs.models import CentralCompetency
        if not CentralCompetency.objects.filter(post_code=code, is_deleted=False).exists():
            raise ValidationError("پست سازمانی انتخاب شده در بانک شایستگی‌ها وجود ندارد.")
        return code

    def clean_start_date(self):
        val = self.cleaned_data.get('start_date')
        if not val:
            return None
        try:
            import jdatetime
            parts = [int(p) for p in val.split('/')]
            jd = jdatetime.date(parts[0], parts[1], parts[2])
            return jd.togregorian()
        except Exception:
            raise ValidationError("تاریخ وارد شده معتبر نیست. فرمت صحیح: سال/ماه/روز (مثال: ۱۴۰۲/۰۱/۰۱)")

    def clean_end_date(self):
        val = self.cleaned_data.get('end_date')
        if not val:
            return None
        try:
            import jdatetime
            parts = [int(p) for p in val.split('/')]
            jd = jdatetime.date(parts[0], parts[1], parts[2])
            return jd.togregorian()
        except Exception:
            raise ValidationError("تاریخ وارد شده معتبر نیست. فرمت صحیح: سال/ماه/روز (مثال: ۱۴۰۲/۰۱/۰۱)")


class BaseJobOpportunityStageFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        
        # Don't validate if there are already other form errors
        if any(self.errors):
            return

        total_weight = 0
        active_stages = 0
        
        for form in self.forms:
            # Skip forms that are marked for deletion
            if self.can_delete and self._should_delete_form(form):
                continue
            
            # Check if form has data and is not empty
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                name = form.cleaned_data.get('name')
                weight = form.cleaned_data.get('weight') or 0
                if name:
                    total_weight += weight
                    active_stages += 1

        # در صورتی که قالب فرآیند کاری انتخاب شده باشد و در ردیف‌ها تغییری داده نشده باشد،
        # ممکن است کاربر بخواهد مراحل پیش‌فرض اتوماتیک کپی شوند. در این حالت اعتبار سنجی 0 خطا نمی‌دهد.
        # اما اگر کاربر ردیفی ثبت کرده باشد، مجموع باید حتما ۱۰۰ باشد.
        if active_stages > 0 and total_weight != 100:
            raise ValidationError(f"مجموع وزن مراحل ارزیابی باید دقیقاً ۱۰۰٪ باشد. در حال حاضر مجموع: {total_weight}٪")


class JobOpportunityStageForm(forms.ModelForm):
    class Meta:
        model = JobOpportunityStage
        fields = ['name', 'stage_type', 'weight', 'sequence']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control stage-name', 'placeholder': 'مثال: آزمون کتبی'}),
            'stage_type': forms.Select(attrs={'class': 'form-select stage-type'}),
            'weight': forms.NumberInput(attrs={'class': 'form-control stage-weight', 'min': 0, 'max': 100, 'placeholder': 'درصد'}),
            'sequence': forms.NumberInput(attrs={'class': 'form-control stage-sequence', 'min': 1, 'placeholder': 'ترتیب'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['stage_type'].required = False
        if not self.instance.pk and not self.initial.get('stage_type'):
            self.initial['stage_type'] = 'OTHER'


JobOpportunityFormSet = inlineformset_factory(
    JobOpportunity,
    JobOpportunityStage,
    formset=BaseJobOpportunityStageFormSet,
    form=JobOpportunityStageForm,
    extra=1,
    can_delete=True
)


class WorkflowTemplateForm(forms.ModelForm):
    class Meta:
        model = WorkflowTemplate
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: فرآیند جذب کارشناس فنی'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'توضیح در مورد الگوی فرآیند استخدامی'}),
        }


class BaseWorkflowStageTemplateFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        
        if any(self.errors):
            return

        total_weight = 0
        active_stages = 0
        
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue
            
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                name = form.cleaned_data.get('name')
                weight = form.cleaned_data.get('default_weight') or 0
                if name:
                    total_weight += weight
                    active_stages += 1

        if active_stages == 0:
            raise ValidationError("حداقل باید یک مرحله پیش‌فرض برای الگو تعریف کنید.")
            
        if total_weight != 100:
            raise ValidationError(f"مجموع وزن مراحل پیش‌فرض الگو باید دقیقاً ۱۰۰٪ باشد. در حال حاضر مجموع: {total_weight}٪")


class WorkflowStageTemplateForm(forms.ModelForm):
    class Meta:
        model = WorkflowStageTemplate
        fields = ['name', 'stage_type', 'default_weight', 'sequence']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control stage-name', 'placeholder': 'مثال: مصاحبه فنی'}),
            'stage_type': forms.Select(attrs={'class': 'form-select stage-type'}),
            'default_weight': forms.NumberInput(attrs={'class': 'form-control stage-weight', 'min': 0, 'max': 100, 'placeholder': 'درصد'}),
            'sequence': forms.NumberInput(attrs={'class': 'form-control stage-sequence', 'min': 1, 'placeholder': 'ترتیب'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['stage_type'].required = False
        if not self.instance.pk and not self.initial.get('stage_type'):
            self.initial['stage_type'] = 'OTHER'


WorkflowStageTemplateFormSet = inlineformset_factory(
    WorkflowTemplate,
    WorkflowStageTemplate,
    formset=BaseWorkflowStageTemplateFormSet,
    form=WorkflowStageTemplateForm,
    extra=1,
    can_delete=True
)
