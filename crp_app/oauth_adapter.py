"""Centralized django-allauth integration for CRP identities and profiles."""

from datetime import timedelta

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from .decorators import get_user_role
from .models import Student


class CRPAccountAdapter(DefaultAccountAdapter):
    """Send every allauth login through the existing CRP role router."""

    def get_login_redirect_url(self, request):
        return reverse('crp:dashboard')


class CRPSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Link only provider-verified email identities and provision clean students."""

    @staticmethod
    def _verified_email(sociallogin):
        verified = {
            address.email.casefold(): address.email
            for address in sociallogin.email_addresses
            if address.verified and address.email
        }
        email = (sociallogin.user.email or '').casefold()
        return verified.get(email)

    @staticmethod
    def _student_id(user):
        base = f'STU-{user.pk:06d}'
        candidate = base
        suffix = 1
        while Student.objects.filter(student_id=candidate).exists():
            suffix += 1
            candidate = f'{base}-{suffix}'
        return candidate

    @classmethod
    def _ensure_student_profile(cls, user):
        if get_user_role(user) != 'student':
            return None
        today = timezone.localdate()
        profile, _ = Student.objects.get_or_create(
            user=user,
            defaults={
                'student_id': cls._student_id(user),
                'cohort': 'Unassigned',
                'program_start_date': today,
                'program_end_date': today + timedelta(days=365),
            },
        )
        return profile

    @transaction.atomic
    def pre_social_login(self, request, sociallogin):
        if sociallogin.is_existing:
            return

        email = self._verified_email(sociallogin)
        supplied_email = (sociallogin.user.email or '').strip()
        User = get_user_model()
        matches = list(User.objects.filter(email__iexact=supplied_email)[:2]) if supplied_email else []

        if matches and not email:
            messages.error(request, 'Please sign in with your existing CRP account before linking Google.')
            raise ImmediateHttpResponse(redirect('crp:login'))
        if len(matches) > 1:
            messages.error(request, 'This email matches multiple CRP accounts. Please contact administration.')
            raise ImmediateHttpResponse(redirect('crp:login'))
        if len(matches) == 1:
            user = matches[0]
            sociallogin.connect(request, user)
            changed = []
            for field in ('first_name', 'last_name'):
                value = getattr(sociallogin.user, field, '')
                if value and not getattr(user, field):
                    setattr(user, field, value)
                    changed.append(field)
            if changed:
                user.save(update_fields=changed)
            self._ensure_student_profile(user)

    @transaction.atomic
    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        # A social signup cannot assign privileged flags or groups. New identities
        # therefore resolve to Student through the existing CRP role rules.
        user.is_staff = False
        user.is_superuser = False
        user.save(update_fields=['is_staff', 'is_superuser'])
        self._ensure_student_profile(user)
        return user
