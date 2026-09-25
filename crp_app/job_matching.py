"""Student-specific job matching and recommendation scoring."""

from .models import Resume


SPECIALISATION_FIELDS = {
    'ai': {'ai'},
    'data_analytics': {'data'},
    'cybersecurity': {'cybersecurity'},
    'project_management': {'pm'},
    'information_systems': {'data', 'cybersecurity'},
}


def recommendation_score(student, job, preferences=None, skills=None):
    """Calculate a deterministic 0-100 score using the student's stated profile."""
    if skills is None:
        try:
            skills = student.resume.skills
        except Resume.DoesNotExist:
            skills = []

    student_skills = {str(skill).strip().casefold() for skill in skills if str(skill).strip()}
    job_skills = {str(skill).strip().casefold() for skill in (job.skills or []) if str(skill).strip()}
    skill_score = 65 * len(student_skills & job_skills) / len(job_skills) if job_skills else 0

    fields = set(job.fields or [])
    preferred_fields = SPECIALISATION_FIELDS.get(student.specialisation, set())
    field_score = 20 if fields & preferred_fields else 0

    keywords = []
    locations = []
    remote_only = False
    if preferences:
        keywords = [str(value).casefold() for value in preferences.job_keywords if str(value).strip()]
        locations = [str(value).casefold() for value in preferences.job_locations if str(value).strip()]
        remote_only = preferences.job_remote_only

    searchable = ' '.join([job.title, job.company, job.description, *(job.skills or [])]).casefold()
    keyword_score = 10 * sum(keyword in searchable for keyword in keywords) / len(keywords) if keywords else 0
    location_score = 5 if locations and any(
        location in job.location.casefold() for location in locations
    ) else 0
    if remote_only and not job.is_remote:
        return 0
    return min(100, round(skill_score + field_score + keyword_score + location_score))
