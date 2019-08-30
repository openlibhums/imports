from wordpress_xmlrpc import Client
from wordpress_xmlrpc.methods.posts import GetPosts

from django.utils import timezone

from comms.models import NewsItem, Tag
from utils.function_cache import cache


@cache(60)
def get_posts(details):
    xmlrpc_url = '{base_url}{slash}xmlrpc.php'.format(
        base_url=details.url,
        slash='/' if not details.url.endswith('/') else '',
    )
    wp = Client(
        xmlrpc_url,
        details.username,
        details.password,
    )
    posts = wp.call(GetPosts())

    return posts


def import_posts(posts_to_import, posts, request, import_object):
    for post in posts:
        if post.id in posts_to_import:

            defaults = {
                'body': post.content,
                'posted': post.date,
                'posted_by': import_object.user,
                'start_display': timezone.now(),
            }

            new_news_item, c = NewsItem.objects.get_or_create(
                content_type=request.model_content_type,
                object_id=request.site_type.pk,
                title=post.title,
                defaults=defaults,
            )

            tags = [tag.name for tag in post.terms]
            new_news_item.set_tags(tags)

    import_object.delete()
