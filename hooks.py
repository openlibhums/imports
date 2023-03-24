from django.urls import reverse
from django.utils.html import mark_safe

from utils.function_cache import cache


@cache(600)
def nav_hook(context):
    return mark_safe(
        '<li><a href="{url}"><i class="fa fa-list"></i> All Articles List</a></li>'.format(
            url=reverse('import_export_articles_all')
        )
    )
