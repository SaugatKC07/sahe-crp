"""Student-specific job matching and deterministic requirement extraction."""

import re

from .models import Resume


SPECIALISATION_FIELDS = {
    'ai': {'ai'},
    'data_analytics': {'data'},
    'cybersecurity': {'cybersecurity'},
    'project_management': {'pm'},
    'information_systems': {'data', 'cybersecurity'},
}


RELIABLE_REQUIREMENT_PHRASES = {
    'Software Development': 'software development',
    'Machine Learning': 'machine learning',
    'Deep Learning': 'deep learning',
    'Data Analysis': 'data analysis',
    'Data Analytics': 'data analytics',
    'Data Science': 'data science',
    'Project Management': 'project management',
    'Product Management': 'product management',
    'Software Engineering': 'software engineering',
    'Web Development': 'web development',
    'Cloud Computing': 'cloud computing',
    'Cybersecurity': 'cybersecurity',
    'Information Security': 'information security',
    'Artificial Intelligence': 'artificial intelligence',
    'Natural Language Processing': 'natural language processing',
    'REST APIs': 'rest apis',
    'REST API': 'rest api',
    'Azure DevOps': 'azure devops',
    'Amazon Web Services': 'amazon web services',
    'Google Cloud': 'google cloud',
    'Continuous Integration': 'continuous integration',
    'Continuous Delivery': 'continuous delivery',
    'Version Control': 'version control',
    'Problem Solving': 'problem solving',
    'Communication': 'communication',
    'Teamwork': 'teamwork',
    'Leadership': 'leadership',
    'Time Management': 'time management',
    'Python': 'python',
    'Java': 'java',
    'JavaScript': 'javascript',
    'TypeScript': 'typescript',
    'C#': 'c#',
    'C++': 'c++',
    'SQL': 'sql',
    'NoSQL': 'nosql',
    'HTML': 'html',
    'CSS': 'css',
    'React': 'react',
    'Angular': 'angular',
    'Vue': 'vue',
    'Django': 'django',
    'Flask': 'flask',
    'FastAPI': 'fastapi',
    'Node.js': 'node.js',
    'Node': 'node',
    'Git': 'git',
    'GitHub': 'github',
    'GitLab': 'gitlab',
    'Docker': 'docker',
    'Kubernetes': 'kubernetes',
    'Terraform': 'terraform',
    'Linux': 'linux',
    'AWS': 'aws',
    'Azure': 'azure',
    'GCP': 'gcp',
    'Spark': 'spark',
    'Hadoop': 'hadoop',
    'Tableau': 'tableau',
    'Power BI': 'power bi',
    'Excel': 'excel',
    'PostgreSQL': 'postgresql',
    'MySQL': 'mysql',
    'MongoDB': 'mongodb',
    'Redis': 'redis',
}


def normalize_requirement(value):
    """Normalize a requirement for case-insensitive comparison."""
    return re.sub(r'[^a-z0-9]+', '', str(value).casefold())


def extract_job_requirements(job):
    """Return structured skills or reliable phrases evidenced in job text."""
    structured = [
        str(skill).strip() for skill in (job.skills or [])
        if str(skill).strip()
    ]
    if structured:
        return structured

    job_text = f'{job.title or ""} {job.description or ""}'
    lowered_text = job_text.casefold()
    requirements = []
    seen = set()
    for label, phrase in sorted(
        RELIABLE_REQUIREMENT_PHRASES.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    ):
        pattern = r'(?<![a-z0-9])' + re.escape(phrase) + r'(?![a-z0-9])'
        if re.search(pattern, lowered_text) and normalize_requirement(label) not in seen:
            requirements.append(label)
            seen.add(normalize_requirement(label))

    return requirements


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
