from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError


def validate_rubric_structure(rubric):
    """Validate the shared rubric contract before publishing."""
    criteria = list(rubric.criteria.all())
    if not criteria:
        raise ValidationError('Add at least one criterion before publishing.')
    total_weight = sum((Decimal(c.weight_percentage) for c in criteria), Decimal('0'))
    if total_weight != Decimal('100'):
        raise ValidationError('Criterion weightings must total exactly 100%.')
    for criterion in criteria:
        if not criterion.name.strip() or criterion.max_marks <= 0:
            raise ValidationError('Each criterion needs a name and positive maximum marks.')
        levels = list(criterion.performance_levels.all())
        if not levels:
            raise ValidationError(f'Add at least one performance level for “{criterion.name}”.')
        previous_max = None
        for level in levels:
            if not level.name.strip() or not level.description.strip():
                raise ValidationError(f'Every performance level for “{criterion.name}” needs a label and descriptor.')
            if level.max_marks < level.min_marks:
                raise ValidationError(f'Performance level “{level.name}” has an invalid mark range.')
            if previous_max is not None and level.min_marks <= previous_max:
                raise ValidationError(f'Performance levels for “{criterion.name}” must be ordered and non-overlapping.')
            previous_max = level.max_marks
    return True


def parse_decimal(value, field_name):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(f'Enter a valid {field_name}.')
    if result < 0:
        raise ValidationError(f'{field_name.capitalize()} cannot be negative.')
    return result
