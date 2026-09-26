import re

from .job_matching import extract_job_requirements, normalize_requirement


_NUMBER_PATTERN = re.compile(r'(?<!\w)(?:\d+(?:\.\d+)?%?|\$[\d,]+(?:\.\d+)?[kKmM]?)(?!\w)')


def _resume_text(resume, experience, education):
    values = [resume.headline, resume.summary, *(resume.skills or [])]
    for entry in experience:
        values.extend([entry.role, entry.company, *(entry.bullets or [])])
    for entry in education:
        values.extend([entry.degree, entry.institution, entry.details])
    return ' '.join(str(value) for value in values if value).casefold()


def _recommendation(label, value):
    return {'label': label, 'value': max(0, min(100, int(value)))}


def _score_note(label, value, recommendations):
    prefixes = {
        'Keywords': ('Add relevant', 'matches', 'is required', 'No reliable'),
        'Structure': ('Add a professional', 'Add contact', 'Add skills', 'Add relevant experience', 'Add your education'),
        'Impact': ('Add measurable', 'Add achievement'),
        'Clarity': ('Keep your summary', 'Shorten excessively'),
    }
    for recommendation in recommendations:
        if recommendation.startswith(prefixes[label]):
            return recommendation
    return 'Deterministic checks passed.' if value >= 70 else 'Review this section.'


def analyze_resume(resume, job=None):
    experience = list(resume.experience.all())
    education = list(resume.education.all())
    text = _resume_text(resume, experience, education)
    recommendations = []

    if job is not None:
        requirements = extract_job_requirements(job)
        matched = [
            requirement for requirement in requirements
            if normalize_requirement(requirement) in normalize_requirement(text)
        ]
        missing = [requirement for requirement in requirements if requirement not in matched]
        keywords_score = round(len(matched) * 100 / len(requirements)) if requirements else 0
        if requirements:
            recommendations.extend(
                f'{requirement} matches the selected job requirement.' for requirement in matched
            )
            recommendations.extend(
                f'{requirement} is required by this role but is not evidenced in your resume. '
                'Add it only if you genuinely have that experience.'
                for requirement in missing
            )
        else:
            recommendations.append('No reliable structured requirements were available for this job.')
    else:
        requirements, matched, missing = [], [], []
        keywords_score = min(100, len([skill for skill in resume.skills if str(skill).strip()]) * 10)
        if not resume.skills:
            recommendations.append('Add relevant skills you genuinely possess.')

    structure_parts = [
        bool(resume.headline),
        bool(resume.summary),
        bool(resume.contact_email or resume.contact_phone or resume.contact_location),
        bool(resume.skills),
        bool(experience),
        bool(education),
    ]
    structure_score = round(sum(structure_parts) * 100 / len(structure_parts))
    if not resume.headline:
        recommendations.append('Add a professional headline.')
    if not resume.summary:
        recommendations.append('Add a professional summary.')
    if not (resume.contact_email or resume.contact_phone or resume.contact_location):
        recommendations.append('Add contact information.')
    if not resume.skills:
        recommendations.append('Add skills to your resume.')
    if not experience:
        recommendations.append('Add relevant experience or project evidence.')
    if not education:
        recommendations.append('Add your education.')

    all_bullets = [str(bullet).strip() for entry in experience for bullet in (entry.bullets or []) if str(bullet).strip()]
    quantified_bullets = [bullet for bullet in all_bullets if _NUMBER_PATTERN.search(bullet)]
    impact_score = round(len(quantified_bullets) * 100 / len(all_bullets)) if all_bullets else 0
    if all_bullets and not quantified_bullets:
        recommendations.append('Add measurable results to your experience descriptions.')
    elif not all_bullets and experience:
        recommendations.append('Add achievement bullets to your experience descriptions.')

    summary_length = len((resume.summary or '').strip())
    useful_summary = 40 <= summary_length <= 500
    nonempty_bullets = sum(bool((bullet or '').strip()) for entry in experience for bullet in (entry.bullets or []))
    long_bullets = sum(len(str(bullet)) > 240 for entry in experience for bullet in (entry.bullets or []))
    clarity_checks = [
        useful_summary,
        bool(experience) and nonempty_bullets == len(all_bullets) if all_bullets else not experience,
        long_bullets == 0,
    ]
    clarity_score = round(sum(clarity_checks) * 100 / len(clarity_checks))
    if resume.summary and not useful_summary:
        recommendations.append('Keep your summary focused and between 40 and 500 characters.')
    if long_bullets:
        recommendations.append('Shorten excessively long experience descriptions.')

    scores = [
        _recommendation('Keywords', keywords_score),
        _recommendation('Structure', structure_score),
        _recommendation('Impact', impact_score),
        _recommendation('Clarity', clarity_score),
    ]
    overall_score = round(sum(item['value'] for item in scores) / len(scores))
    for item in scores:
        item['note'] = _score_note(item['label'], item['value'], recommendations)
    return {
        'overall_score': overall_score,
        'completeness_score': structure_score,
        'scores': scores,
        'recommendations': recommendations,
        'requirements': requirements,
        'matched_requirements': matched,
        'missing_requirements': missing,
        'keyword_coverage': keywords_score if requirements else None,
    }
