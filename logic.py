from wordpress_xmlrpc import Client, WordPressPost
from wordpress_xmlrpc.methods.posts import GetPosts, NewPost
from wordpress_xmlrpc.methods.users import GetUserInfo


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
