"""
ASGI config for sahe_crp project.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sahe_crp.settings')

application = get_asgi_application()
