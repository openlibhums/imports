from django import template

register = template.Library()


@register.filter
def human(value):
    value = value.capitalize()
    value = value.replace('_', ' ')

    return value