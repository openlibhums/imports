from django import template

register = template.Library()


@register.filter
def identify(row):
    if row.get('Janeway ID'):
        return 'Update'
    if not row.get('Article title') and row.get('Author surname'):
        return 'Author'

    return 'New Article'

