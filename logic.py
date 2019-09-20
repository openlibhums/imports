import os
from uuid import uuid4
from io import open as iopen

import requests
from wordpress_xmlrpc import Client
from wordpress_xmlrpc.methods.posts import GetPosts
from bs4 import BeautifulSoup

from django.utils import timezone
from django.conf import settings

from comms.models import NewsItem
from utils.function_cache import cache


@cache(120)
def get_posts(details, increment, offset):
    xmlrpc_url = '{base_url}{slash}xmlrpc.php'.format(
        base_url=details.url,
        slash='/' if not details.url.endswith('/') else '',
    )
    wp = Client(
        xmlrpc_url,
        details.username,
        details.password,
    )
    posts = wp.call(GetPosts({'number': increment, 'offset': offset}))

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

            if c:
                rewrite_image_paths(new_news_item)

    import_object.delete()
    

def rewrite_image_paths(news_item):
    soup = BeautifulSoup(news_item.body, 'html.parser')
    images = soup.find_all('img')

    print(images)

    for image in images:
        img_src = image['src'].split('?')[0]
        path = download_and_store_image(img_src)
        image['src'] = path

    news_item.body = soup.prettify()
    news_item.save()


def download_and_store_image(image_source):
    image = requests.get(image_source)
    image.raw.decode_content = True
    name = os.path.basename(image_source)

    fileurl = save_media_file(
        name,
        image.content,
    )

    return fileurl


def save_media_file(original_filename, source_file):
    filename = str(uuid4()) + str(os.path.splitext(original_filename)[1])
    filepath = '{media_root}/{filename}'.format(
        media_root=settings.MEDIA_ROOT,
        filename=filename,
    )
    fileurl = '{media_url}{filename}'.format(
        media_url=settings.MEDIA_URL,
        filename=filename,
    )
    with iopen(filepath, 'wb') as file:
        file.write(source_file)

    return fileurl
