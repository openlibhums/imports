from core.workflow import log_stage_change

def create_article_workflow_log(article):
    """ Creates the workflow log for an article given its journal workflow
    :param article: an instance of sumbission.models.Article
    """
    journal_workflow = article.journal.workflow()
    for element in journal_workflow.elements.all():
        log_stage_change(article, element)


