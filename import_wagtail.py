from cms.models import NavigationItem, Page
from comms.models import NewsItem
from django.contrib.contenttypes.models import ContentType
import json
from press.models import Press
from utils.logger import get_logger

from plugins.imports.utils import get_aware_datetime


logger = get_logger(__name__)

LARGE_INT = 32768
SITE_PREFIX = "site"


def import_from_json(press, json_data, site_prefix=" ", dry_run=False):
    wt_data = json.loads(json_data)
    for page_dict in wt_data["pages"]:
        if (
            page_dict["content"]["live"]
            and page_dict["content"].get("body")
            and not page_dict["content"]["expired"]
        ):
            match page_dict["app_label"]:
                case "cms":
                    import_page(press, page_dict, site_prefix, dry_run)
                case "blog":
                    import_news_item(press, page_dict, site_prefix, dry_run)
                case _:
                    logger.info(
                        "Ignoring page %s of type '%s'",
                        page_dict["content"]["url_path"], page_dict["app_label"]
                    )


def import_page(press, page_data, site_prefix=" ", dry_run=False):
    url = page_data["content"]["url_path"].split(site_prefix)[-1] or None
    if not url:
        return
    content_type = ContentType.objects.get_for_model(press)
    if url.endswith("/"):
        # Janeway autoappends trail slash
        url = url[:-1]

    jw_page_data = dict(
        display_name=page_data["content"]["title"],
        content=page_data["content"]["body"],
        edited=page_data,
    )
    page, c = Page.objects.update_or_create(
        name=url,
        content_type=content_type,
        object_id=press.id,
        defaults=jw_page_data,
    )

    if c:
        logger.info("Created page %s", page.name)
    else:
        logger.info("Updated page %s", page.name)

    if page_data["content"].get("show_in_menus"):
        sequence = LARGE_INT - page_data["content"]["pk"]
        import_nav_link(press, page, sequence)


def import_news_item(press, page_data, site_prefix=" ", dry_run=False):
    content_type = ContentType.objects.get_for_model(press)
    jw_page_data = dict(
        title=page_data["content"]["title"],
        body=page_data["content"]["body"],
        posted=get_aware_datetime(page_data["content"]["first_published_at"]),
        start_display=get_aware_datetime(page_data["content"]["first_published_at"]),
        end_display=get_aware_datetime(page_data["content"]["expire_at"]),
    )
    news_item, c = NewsItem.objects.update_or_create(
        # We use a reverse order PK as sequence AND as unique identifier
        sequence=LARGE_INT - page_data["content"]["pk"],
        content_type=content_type,
        object_id=press.id,
        defaults=jw_page_data,
    )

    if c:
        logger.info("Created news item %s", news_item.title)
    else:
        logger.info("Updated news item %s", news_item.title)

def import_nav_link(press, page, sequence):
    url = page.name

    # /parent/path/to/page/ -> ["", "parent", "path/to/page/"]
    # /parent/             -> ["", "parent", ""]
    top_path, *child_path = url.split("/", 1)
    top_nav,c = update_or_create_nav(
        press, top_path,
        prefixes=[SITE_PREFIX],
        parent=None,
        title=None if child_path else page.display_name,
        seq=None if child_path else sequence,
    )
    if child_path:
        # unwrap
        child_path = child_path[0]
        top_nav.has_sub_nav = True
        top_nav.save()
        child_nav, c = update_or_create_nav(
            press, child_path,
            prefixes=[SITE_PREFIX, top_path],
            parent=top_nav,
            title=page.display_name,
            seq=sequence,
        )


def update_or_create_nav(press, path, prefixes=None, parent=None, title=None, seq=None):

    if prefixes:
        path = "/".join(prefixes + [path])

    if not parent and not path.startswith("/"):
        path = f"/{path}"

    defaults = {
        "link_name": title or path, # Field is required
        "sequence": seq or 0,
    }
    if parent:
        defaults["top_level_nav"] = parent


    nav, c = NavigationItem.objects.get_or_create(
        content_type=ContentType.objects.get_for_model(press),
        object_id=press.id,
        link=path,
        defaults=defaults
    )

    # Perform update
    if title:
        nav.link_name = title
    if seq:
        nav.sequence = seq


    nav.save()
    return nav, c


