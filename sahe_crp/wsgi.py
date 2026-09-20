"""
WSGI config for sahe_crp project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ['DJANGO_SETTINGS_MODULE'] = 'sahe_crp.settings'

application = get_wsgi_application()
