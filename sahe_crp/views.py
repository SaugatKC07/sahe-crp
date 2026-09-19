"""
Views for sahe_crp project.
"""
from django.views.generic import TemplateView


class HomeView(TemplateView):
    template_name = 'crp/home.html'
