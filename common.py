from core.workflow import log_stage_change
from core import models as core_models


def create_article_workflow_log(article):
    """ Creates the workflow log for an article given its journal workflow
    :param article: an instance of sumbission.models.Article
    """
    journal_workflow = article.journal.workflow()
    for element in journal_workflow.elements.all():
        log_stage_change(article, element)


def get_text_or_none(soup, element_name):
    if soup.find(element_name):
        return soup.find(element_name).text
    else:
        return None


def map_ojs_roles_to_janeway_role_slugs(ojs_roles):
    role_slugs = list()

    if 'Reviewer' in ojs_roles:
        role_slugs.append('reviewer')
    if 'Author' in ojs_roles:
        role_slugs.append('author')
    if 'Journal Manager' in ojs_roles:
        role_slugs.append('journal-manager')
    if 'Editor' in ojs_roles:
        role_slugs.append('editor')
    if 'Reader' in ojs_roles:
        role_slugs.append('reader')

    return role_slugs


def int_string_to_bool(string):
    """
    Expects a string of either "0" (False) or "1" (True)
    Returns a boolean.
    """
    if string == "0":
        return False
    elif string == "1":
        return True