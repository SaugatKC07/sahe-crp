from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from functools import wraps

def role_required(*allowed_roles):
    """
    Decorator to restrict view access to specific roles.
    Roles: 'student', 'trainer', 'admissions', 'admin'
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped_view(request, *args, **kwargs):
            user_role = get_user_role(request.user)
            if user_role not in allowed_roles:
                # Redirect to appropriate dashboard based on user's actual role
                return redirect('crp:dashboard')
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator

def get_user_role(user):
    """
    Helper function to determine user role based on CRP requirements.
    Supported roles: student, trainer, admissions, finance, admin
    """
    if user.is_superuser:
        return 'admin'
    if user.groups.filter(name__in=['CRP Admin', 'Administrators']).exists():
        return 'admin'
    if hasattr(user, 'finance_profile'):
        return 'finance'
    if hasattr(user, 'instructor_profile') and not (user.is_staff and not user.is_superuser):
        return 'trainer'
    if user.groups.filter(name__in=['Admissions Staff', 'Student Services Staff']).exists():
        return 'admissions'
    if user.is_staff and not user.is_superuser:
        return 'admissions'
    return 'student'
