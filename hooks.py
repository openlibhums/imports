from django.core.urlresolvers import reverse
from django.template.loader import render_to_string

from utils.function_cache import cache


@cache(600)
def nav_hook(context):
    return '<li><a href="{url}"><i class="fa fa-list"></i> All Articles List</a></li>'.format(
        url=reverse('import_export_articles_all')
    )
