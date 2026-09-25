"""Provider adapters used by the global job aggregation service."""

from abc import ABC, abstractmethod
from datetime import date, datetime
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .models import JobSource


class JobProviderError(Exception):
    """Raised when a job provider cannot return a valid response."""


class JobProvider(ABC):
    @abstractmethod
    def fetch_jobs(self, source: JobSource) -> list[dict]:
        """Return provider-independent job dictionaries."""


class AdzunaProvider(JobProvider):
    BASE_URL = 'https://api.adzuna.com/v1/api/jobs'
    TIMEOUT_SECONDS = 15

    def fetch_jobs(self, source):
        app_id = os.environ.get('ADZUNA_APP_ID', '').strip()
        app_key = os.environ.get('ADZUNA_APP_KEY', '').strip()
        if not app_id or not app_key:
            raise JobProviderError('ADZUNA_APP_ID and ADZUNA_APP_KEY must both be configured.')
        if len(source.country) != 2 or not source.country.isascii() or not source.country.isalpha():
            raise JobProviderError('Adzuna country must be a two-letter country code.')

        params = {
            'app_id': app_id,
            'app_key': app_key,
            'results_per_page': min(max(source.results_per_page, 1), 100),
            'content-type': 'application/json',
        }
        if source.search_query:
            params['what'] = source.search_query
        url = f'{self.BASE_URL}/{source.country.lower()}/search/1?{urlencode(params)}'
        request = Request(url, headers={'Accept': 'application/json'})
        try:
            with urlopen(request, timeout=self.TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except HTTPError as exc:
            raise JobProviderError(f'Adzuna request failed with HTTP status {exc.code}.') from exc
        except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise JobProviderError(f'Adzuna request failed: {exc}') from exc
        if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
            raise JobProviderError('Adzuna returned an unexpected response format.')
        return [self.normalize_job(item, source.country) for item in payload['results']]

    @classmethod
    def normalize_job(cls, item, country):
        if not isinstance(item, dict) or not item.get('id') or not item.get('title'):
            raise JobProviderError('Adzuna returned a job without an id or title.')
        company = item.get('company') or {}
        location = item.get('location') or {}
        category = item.get('category') or {}
        title = str(item['title']).strip()
        description = str(item.get('description') or '').strip()
        salary_min = float(item['salary_min']) if item.get('salary_min') is not None else None
        salary_max = float(item['salary_max']) if item.get('salary_max') is not None else None
        salary = cls._salary_label(salary_min, salary_max, country)
        category_text = str(category.get('label') or category.get('tag') or '')
        fields = cls._map_fields(f'{title} {category_text} {description}')
        skills = cls._extract_skills(description)
        contract_type = str(item.get('contract_type') or '').lower()
        contract_time = str(item.get('contract_time') or '').lower()
        job_type = {
            'full_time': 'full_time',
            'part_time': 'part_time',
            'contract': 'contract',
            'permanent': 'full_time',
        }.get(contract_time or contract_type, 'full_time')
        created = item.get('created')
        try:
            posted_date = datetime.fromisoformat(str(created).replace('Z', '+00:00')).date()
        except (TypeError, ValueError):
            posted_date = date.today()
        apply_url = str(item.get('redirect_url') or '')[:1000]
        parsed_apply_url = urlsplit(apply_url)
        if parsed_apply_url.scheme not in {'http', 'https'} or not parsed_apply_url.netloc:
            apply_url = ''

        return {
            'source_external_id': str(item['id']),
            'title': title[:200],
            'company': str(company.get('display_name') or 'Undisclosed')[:200],
            'location': str(location.get('display_name') or 'Not specified')[:200],
            'salary': salary[:100],
            'description': description or title,
            'apply_url': apply_url,
            'fields': fields,
            'skills': skills,
            'job_type': job_type,
            'posted_date': posted_date,
            'salary_min': round(salary_min / 1000) if salary_min is not None else None,
            'salary_max': round(salary_max / 1000) if salary_max is not None else None,
            'is_remote': 'remote' in f"{location.get('display_name', '')} {title} {description}".lower(),
            'is_active': True,
            'last_seen_at': datetime.now().astimezone(),
        }

    @staticmethod
    def _salary_label(salary_min, salary_max, country):
        if salary_min is None and salary_max is None:
            return 'Salary not listed'
        currency = 'A$' if country.lower() == 'au' else '£' if country.lower() == 'gb' else '$'
        lower = f'{currency}{salary_min:,.0f}' if salary_min is not None else ''
        upper = f'{currency}{salary_max:,.0f}' if salary_max is not None else ''
        if lower and upper:
            return f'{lower}–{upper} per year'
        return f'{lower or upper} per year'

    @staticmethod
    def _map_fields(text):
        text = text.lower()
        rules = {
            'ai': ('artificial intelligence', 'machine learning', 'data scientist', 'deep learning'),
            'data': ('data analyst', 'data analytics', 'analytics', 'business intelligence'),
            'cybersecurity': ('cyber security', 'cybersecurity', 'information security', 'security analyst'),
            'pm': ('project manager', 'project management', 'program manager'),
            'accounting': ('accountant', 'accounting', 'bookkeeper'),
            'hospitality': ('hospitality', 'chef', 'hotel', 'restaurant'),
        }
        matches = [field for field, terms in rules.items() if any(term in text for term in terms)]
        return matches or ['other']

    @staticmethod
    def _extract_skills(description):
        known_skills = (
            'Python', 'SQL', 'Machine Learning', 'Data Analysis', 'AWS', 'Azure',
            'Cybersecurity', 'Project Management', 'Communication', 'Excel',
            'Java', 'JavaScript', 'Power BI', 'Tableau', 'Linux', 'Networking',
        )
        description_lower = description.lower()
        return [skill for skill in known_skills if skill.lower() in description_lower]


PROVIDERS = {'adzuna': AdzunaProvider}


def get_provider(provider_name):
    try:
        return PROVIDERS[provider_name]()
    except KeyError as exc:
        raise JobProviderError(f'Unsupported job provider: {provider_name}') from exc
