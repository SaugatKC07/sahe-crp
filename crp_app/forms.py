from django import forms
from django.contrib.auth.models import User
from .models import Department, Instructor, Course, Registration, Announcement, FinanceProfile, MarketingProfile, Invoice, Campaign, UploadedImage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, Submit, Div, HTML
from .linkedin_coach import linkedin_url_is_valid


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ['name', 'code', 'description', 'logo']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('name'),
            Field('code'),
            Field('description'),
            Field('logo'),
            Submit('submit', 'Save Department', css_class='btn btn-sahe')
        )


class InstructorForm(forms.ModelForm):
    class Meta:
        model = Instructor
        fields = ['employee_id', 'department', 'phone', 'status', 'specialization', 'qualification', 'profile_image', 'bio']
        widgets = {
            'bio': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('employee_id'),
            Field('department'),
            Field('phone'),
            Field('status'),
            Field('specialization'),
            Field('qualification'),
            Field('profile_image'),
            Field('bio'),
            Submit('submit', 'Save Instructor', css_class='btn btn-sahe')
        )


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ['code', 'name', 'description', 'credits', 'level', 'department', 'status', 'max_capacity', 'instructor', 'trainers', 'start_date', 'end_date', 'image']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('code'),
            Field('name'),
            Field('description'),
            Field('credits'),
            Field('level'),
            Field('department'),
            Field('status'),
            Field('max_capacity'),
            Field('instructor'),
            Field('trainers'),
            Field('start_date'),
            Field('end_date'),
            Field('image'),
            Submit('submit', 'Save Course', css_class='btn btn-sahe')
        )


class RegistrationForm(forms.ModelForm):
    class Meta:
        model = Registration
        fields = ['student', 'course', 'semester', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('student'),
            Field('course'),
            Field('semester'),
            Field('notes'),
            Submit('submit', 'Submit Registration', css_class='btn btn-sahe')
        )


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ['title', 'content', 'course', 'priority', 'published']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('title'),
            Field('content'),
            Field('course'),
            Field('priority'),
            Field('published'),
            Submit('submit', 'Save Announcement', css_class='btn btn-sahe')
        )


class LinkedInProfileForm(forms.Form):
    headline = forms.CharField(max_length=200, required=False)
    about = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 8}))
    linkedin_url = forms.URLField(required=False, max_length=200)

    def clean_linkedin_url(self):
        value = self.cleaned_data['linkedin_url'].strip()
        if value and not linkedin_url_is_valid(value):
            raise forms.ValidationError(
                'Use a LinkedIn profile URL such as https://www.linkedin.com/in/your-name/.'
            )
        return value


class FinanceProfileForm(forms.ModelForm):
    class Meta:
        model = FinanceProfile
        fields = ['employee_id', 'department', 'phone', 'status', 'specialization', 'qualification']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('employee_id'),
            Field('department'),
            Field('phone'),
            Field('status'),
            Field('specialization'),
            Field('qualification'),
            Submit('submit', 'Save Profile', css_class='btn btn-sahe')
        )


class MarketingProfileForm(forms.ModelForm):
    class Meta:
        model = MarketingProfile
        fields = ['employee_id', 'department', 'phone', 'status', 'specialization', 'qualification']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('employee_id'),
            Field('department'),
            Field('phone'),
            Field('status'),
            Field('specialization'),
            Field('qualification'),
            Submit('submit', 'Save Profile', css_class='btn btn-sahe')
        )


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['invoice_number', 'student', 'registration', 'amount', 'due_date', 'status', 'description']
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('invoice_number'),
            Field('student'),
            Field('registration'),
            Field('amount'),
            Field('due_date'),
            Field('status'),
            Field('description'),
            Submit('submit', 'Save Invoice', css_class='btn btn-sahe')
        )


class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ['name', 'description', 'start_date', 'end_date', 'budget', 'status', 'target_audience']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('name'),
            Field('description'),
            Field('start_date'),
            Field('end_date'),
            Field('budget'),
            Field('status'),
            Field('target_audience'),
            Submit('submit', 'Save Campaign', css_class='btn btn-sahe')
        )


class UploadedImageForm(forms.ModelForm):
    class Meta:
        model = UploadedImage
        fields = ['title', 'description', 'image', 'category', 'alt_text']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            Field('title'),
            Field('description'),
            Field('image'),
            Field('category'),
            Field('alt_text'),
            Submit('submit', 'Upload Image', css_class='btn btn-sahe')
        )
