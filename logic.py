from wordpress_xmlrpc import Client
from wordpress_xmlrpc.methods.posts import GetPosts

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


def import_posts(posts_to_import, posts):
    for post in posts:
        if post.id in posts_to_import:
            pass