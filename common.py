import re

from core.workflow import log_stage_change
from utils.logger import get_logger

logger = get_logger(__name__)

def create_article_workflow_log(article):
    """ Creates the workflow log for an article given its journal workflow
    :param article: an instance of sumbission.models.Article
    """
    journal_workflow = article.journal.workflow()
    for element in journal_workflow.elements.all():
        log_stage_change(article, element)


def get_filename_from_headers(response):
    logger.debug("Parsing filename from headers")
    try:
        header = response.headers['content-disposition']
        return re.findall("filename=(.+)", header)[0].strip('"')
    except KeyError:
        logger.debug("No content-disposition header")
    except IndexError:
        logger.debug("No Filename provided in headers")
    return None
