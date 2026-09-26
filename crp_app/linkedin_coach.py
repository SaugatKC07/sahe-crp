from urllib.parse import urlparse


def linkedin_url_is_valid(value):
    if not value:
        return True
    parsed = urlparse(value)
    host = (parsed.hostname or '').lower()
    path_parts = [part for part in parsed.path.split('/') if part]
    return (
        parsed.scheme in ('http', 'https')
        and host in ('linkedin.com', 'www.linkedin.com')
        and len(path_parts) >= 2
        and path_parts[0].lower() == 'in'
    )


def profile_data(student, resume):
    if resume is None:
        return {'education': [], 'experience': [], 'skills': []}
    return {
        'education': list(resume.education.all()),
        'experience': list(resume.experience.all()),
        'skills': [str(skill).strip() for skill in (resume.skills or []) if str(skill).strip()],
    }


def completeness_items(student, linkedin, resume, data):
    contact = bool(
        getattr(student.user, 'email', '')
        or getattr(student, 'phone', '')
        or (resume and (resume.contact_email or resume.contact_phone or resume.contact_location))
    )
    return [
        {'item': 'Headline', 'key': 'headline', 'pts': 15, 'done': bool(linkedin.headline),
         'tip': 'Add a concise role, specialisation, or value statement.'},
        {'item': 'About section', 'key': 'about', 'pts': 20, 'done': bool(linkedin.about),
         'tip': 'Summarise your genuine experience, education, and skills.'},
        {'item': 'Education', 'key': 'education', 'pts': 15, 'done': bool(data['education']),
         'tip': 'Add education in Resume Builder.'},
        {'item': 'Skills', 'key': 'skills', 'pts': 15, 'done': bool(data['skills']),
         'tip': 'Add skills in Resume Builder.'},
        {'item': 'Experience', 'key': 'experience', 'pts': 15, 'done': bool(data['experience']),
         'tip': 'Add genuine experience in Resume Builder.'},
        {'item': 'LinkedIn URL', 'key': 'linkedin_url', 'pts': 10,
         'done': bool(resume and resume.linkedin_url),
         'tip': 'Save your public LinkedIn profile URL.'},
        {'item': 'Contact information', 'key': 'contact', 'pts': 10, 'done': contact,
         'tip': 'Keep an email, phone, or location available in your profile.'},
    ]


def build_headline(student, data):
    parts = []
    if data['education']:
        education = data['education'][0]
        parts.append(education.degree or education.institution)
    else:
        specialisation = student.get_specialisation_display()
        if specialisation:
            parts.append(f'{specialisation} student')
    if data['experience']:
        parts.append(data['experience'][0].role)
    if data['skills']:
        parts.append(' · '.join(data['skills'][:3]))
    return ' · '.join(part for part in parts if part)[:200]


def build_about(student, resume, data):
    paragraphs = []
    if resume and resume.summary:
        paragraphs.append(resume.summary.strip())
    else:
        paragraphs.append(
            f'{student.get_specialisation_display()} student building practical experience '
            'through the Career Ready Program.'
        )
    if data['experience']:
        experience = ', '.join(
            f'{entry.role} at {entry.company}' for entry in data['experience'][:3]
        )
        paragraphs.append(f'Experience includes {experience}.')
    if data['skills']:
        paragraphs.append(f'Skills include {", ".join(data["skills"])}.')
    if data['education']:
        education = data['education'][0]
        paragraphs.append(f'Education: {education.degree} at {education.institution}.')
    return '\n\n'.join(paragraphs)
