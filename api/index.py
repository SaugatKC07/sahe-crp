import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sahe_crp.settings')

from sahe_crp.wsgi import application

app = application
