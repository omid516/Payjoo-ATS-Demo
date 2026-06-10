from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory, BaseInlineFormSet
from .models import (
    Candidate, CandidateEducation, CandidateExperience, JobApplication,
    CandidateLanguage, CandidateSkill, CandidateCertificate
)
from apps.jobs.models import JobOpportunity
import jdatetime

class CandidateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True

    class Meta:
        model = Candidate
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'national_id', 'personnel_number', 'resume']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'نام'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'نام خانوادگی'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'example@domain.com'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: 09123456789'}),
            'national_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: 0012345678'}),
            'personnel_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: 991234 (اختیاری)'}),
            'resume': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def clean_national_id(self):
        national_id = self.cleaned_data.get('national_id')
        if not national_id.isdigit() or len(national_id) != 10:
            raise ValidationError("کد ملی باید دقیقاً ۱۰ رقم عددی باشد.")
        
        # Check uniqueness (excluding self)
        qs = Candidate.objects.filter(national_id=national_id)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("این کد ملی قبلاً در سیستم ثبت شده است.")
            
        return national_id

    def clean_personnel_number(self):
        val = self.cleaned_data.get('personnel_number')
        if val:
            val = val.strip()
            qs = Candidate.all_objects.filter(personnel_number=val)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            national_id = self.cleaned_data.get('national_id')
            if national_id:
                qs = qs.exclude(national_id=national_id)
            if qs.exists():
                raise ValidationError("این شماره پرسنلی قبلاً در سیستم ثبت شده است.")
        return val or None


class CandidateEducationForm(forms.ModelForm):
    class Meta:
        model = CandidateEducation
        fields = ['degree', 'major', 'university', 'gpa', 'graduation_year']
        widgets = {
            'degree': forms.Select(attrs={'class': 'form-select'}),
            'major': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: مهندسی کامپیوتر'}),
            'university': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: دانشگاه صنعتی شریف'}),
            'gpa': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '20', 'placeholder': 'مثال: 18.50'}),
            'graduation_year': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'مثال: 1400'}),
        }


CandidateEducationFormSet = inlineformset_factory(
    Candidate,
    CandidateEducation,
    form=CandidateEducationForm,
    extra=1,
    can_delete=True
)


class CandidateExperienceForm(forms.ModelForm):
    start_date = forms.CharField(label="تاریخ شروع", widget=forms.TextInput(attrs={'class': 'form-control date-picker', 'placeholder': '۱۴۰۰/۰۱/۰۱'}))
    end_date = forms.CharField(label="تاریخ پایان", required=False, widget=forms.TextInput(attrs={'class': 'form-control date-picker', 'placeholder': '۱۴۰۲/۱۲/۲۹'}))
    
    class Meta:
        model = CandidateExperience
        fields = ['company', 'job_title', 'start_date', 'end_date', 'description']
        widgets = {
            'company': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'نام شرکت / سازمان'}),
            'job_title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: توسعه‌دهنده پایتون'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'شرح وظایف و دستاوردها'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.start_date:
                jd = jdatetime.date.fromgregorian(date=self.instance.start_date)
                self.initial['start_date'] = jd.strftime('%Y/%m/%d')
            if self.instance.end_date:
                jd = jdatetime.date.fromgregorian(date=self.instance.end_date)
                self.initial['end_date'] = jd.strftime('%Y/%m/%d')

    def clean_start_date(self):
        val = self.cleaned_data.get('start_date')
        if not val:
            return None
        try:
            parts = [int(p) for p in val.split('/')]
            jd = jdatetime.date(parts[0], parts[1], parts[2])
            return jd.togregorian()
        except Exception:
            raise ValidationError("فرمت صحیح: سال/ماه/روز")

    def clean_end_date(self):
        val = self.cleaned_data.get('end_date')
        if not val:
            return None
        try:
            parts = [int(p) for p in val.split('/')]
            jd = jdatetime.date(parts[0], parts[1], parts[2])
            return jd.togregorian()
        except Exception:
            raise ValidationError("فرمت صحیح: سال/ماه/روز")


CandidateExperienceFormSet = inlineformset_factory(
    Candidate,
    CandidateExperience,
    form=CandidateExperienceForm,
    extra=1,
    can_delete=True
)


class JobApplicationForm(forms.ModelForm):
    class Meta:
        model = JobApplication
        fields = ['job']
        widgets = {
            'job': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # فقط فرصت‌های شغلی فعال و غیر مختومه نمایش داده شوند
        self.fields['job'].queryset = JobOpportunity.objects.filter(is_deleted=False).exclude(
            status__in=[JobOpportunity.STATUS_CLOSED, JobOpportunity.STATUS_CANCELLED]
        )


class CandidateSignUpForm(forms.ModelForm):
    password = forms.CharField(
        label="کلمه عبور", 
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'حداقل ۸ کاراکتر'})
    )
    password_confirm = forms.CharField(
        label="تکرار کلمه عبور", 
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'تکرار کلمه عبور'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True

    class Meta:
        model = Candidate
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'national_id', 'personnel_number', 'resume']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'نام'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'نام خانوادگی'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'example@domain.com'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: 09123456789'}),
            'national_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'کد ملی ۱۰ رقمی'}),
            'personnel_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'کد پرسنلی (اختیاری برای کارکنان داخلی)'}),
            'resume': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def clean_national_id(self):
        national_id = self.cleaned_data.get('national_id')
        if not national_id.isdigit() or len(national_id) != 10:
            raise ValidationError("کد ملی باید دقیقاً ۱۰ رقم عددی باشد.")
        
        # بررسی یکتایی در صورتی که کاربر متصل داشته باشد
        if Candidate.all_objects.filter(national_id=national_id, user__isnull=False).exists():
            raise ValidationError("این کد ملی قبلاً ثبت‌نام کرده است. لطفاً وارد شوید.")
        
        from django.contrib.auth.models import User
        if User.objects.filter(username=national_id).exists():
            raise ValidationError("یک حساب کاربری با این کد ملی قبلاً ایجاد شده است.")
            
        return national_id

    def clean_personnel_number(self):
        val = self.cleaned_data.get('personnel_number')
        if val:
            val = val.strip()
            qs = Candidate.all_objects.filter(personnel_number=val)
            national_id = self.cleaned_data.get('national_id')
            if national_id:
                qs = qs.exclude(national_id=national_id)
            if qs.exists():
                raise ValidationError("این شماره پرسنلی قبلاً در سیستم ثبت شده است.")
        return val or None

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        if password and password_confirm and password != password_confirm:
            self.add_error('password_confirm', "کلمه عبور و تکرار آن مطابقت ندارند.")
            
        if password and len(password) < 8:
            self.add_error('password', "کلمه عبور باید حداقل ۸ کاراکتر باشد.")
            
        return cleaned_data


class CandidateLanguageForm(forms.ModelForm):
    class Meta:
        model = CandidateLanguage
        fields = ['name', 'proficiency']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: انگلیسی'}),
            'proficiency': forms.Select(attrs={'class': 'form-select'}),
        }


CandidateLanguageFormSet = inlineformset_factory(
    Candidate,
    CandidateLanguage,
    form=CandidateLanguageForm,
    extra=1,
    can_delete=True
)


class CandidateSkillForm(forms.ModelForm):
    class Meta:
        model = CandidateSkill
        fields = ['name', 'level']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: Python'}),
            'level': forms.Select(attrs={'class': 'form-select'}),
        }


CandidateSkillFormSet = inlineformset_factory(
    Candidate,
    CandidateSkill,
    form=CandidateSkillForm,
    extra=1,
    can_delete=True
)


class CandidateCertificateForm(forms.ModelForm):
    issue_date = forms.CharField(label="تاریخ اخذ", widget=forms.TextInput(attrs={'class': 'form-control date-picker', 'placeholder': '۱۴۰۰/۰۱/۰۱'}))
    expiration_date = forms.CharField(label="تاریخ انقضا", required=False, widget=forms.TextInput(attrs={'class': 'form-control date-picker', 'placeholder': '۱۴۰۲/۱۲/۲۹'}))

    class Meta:
        model = CandidateCertificate
        fields = ['name', 'issuer', 'issue_date', 'expiration_date']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'عنوان مدرک / دوره'}),
            'issuer': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'موسسه صادرکننده'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.issue_date:
                jd = jdatetime.date.fromgregorian(date=self.instance.issue_date)
                self.initial['issue_date'] = jd.strftime('%Y/%m/%d')
            if self.instance.expiration_date:
                jd = jdatetime.date.fromgregorian(date=self.instance.expiration_date)
                self.initial['expiration_date'] = jd.strftime('%Y/%m/%d')

    def clean_issue_date(self):
        val = self.cleaned_data.get('issue_date')
        if not val:
            return None
        try:
            parts = [int(p) for p in val.split('/')]
            jd = jdatetime.date(parts[0], parts[1], parts[2])
            return jd.togregorian()
        except Exception:
            raise ValidationError("فرمت صحیح: سال/ماه/روز")

    def clean_expiration_date(self):
        val = self.cleaned_data.get('expiration_date')
        if not val:
            return None
        try:
            parts = [int(p) for p in val.split('/')]
            jd = jdatetime.date(parts[0], parts[1], parts[2])
            return jd.togregorian()
        except Exception:
            raise ValidationError("فرمت صحیح: سال/ماه/روز")


CandidateCertificateFormSet = inlineformset_factory(
    Candidate,
    CandidateCertificate,
    form=CandidateCertificateForm,
    extra=1,
    can_delete=True
)


