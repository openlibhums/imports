from itertools import chain

from submission import models as submission_models

from plugins.imports.ojs.importers import (
    calculate_article_stage,
    create_workflow_log,
    import_article_metadata,
    import_article_metrics,
    import_collection_metadata,
    import_copyediting,
    import_typesetting,
    import_issue_metadata,
    import_publication,
    import_review_data,
    import_section_metadata,
    import_user_metadata,
)
from utils.logger import get_logger

logger = get_logger(__name__)


def import_article(ojs_client, journal, ojs_id):
    article_dict = ojs_client.get_article(ojs_id)
    if article_dict:
        article = import_article_metadata(article_dict, journal, ojs_client)

        import_review_data(article_dict, article, ojs_client)
        import_copyediting(article_dict, article, ojs_client)
        import_typesetting(article_dict, article, ojs_client)
        import_publication(article_dict, article, ojs_client)


def import_published_articles(ojs_client, journal):
    articles = ojs_client.get_articles("published")
    for article_dict in articles:
        article = import_article_metadata(article_dict, journal, ojs_client)

        import_review_data(article_dict, article, ojs_client)
        import_copyediting(article_dict, article, ojs_client)
        import_typesetting(article_dict, article, ojs_client)
        import_publication(article_dict, article, ojs_client)

        stage = calculate_article_stage(article_dict, article)
        article.stage = stage
        article.save()

        logger.info("Imported article with article ID %d" % article.pk)


def import_in_progress_articles(ojs_client, journal):
    """ imports all articles in review or being edited"""
    in_review = ojs_client.get_articles("in_review")
    in_editing = ojs_client.get_articles("in_editing")
    seen = set()
    for article_dict in chain(in_review, in_editing):
        article = import_article_metadata(article_dict, journal, ojs_client)

        import_review_data(article_dict, article, ojs_client)
        import_copyediting(article_dict, article, ojs_client)
        import_typesetting(article_dict, article, ojs_client)

        stage = calculate_article_stage(article_dict, article)
        article.stage = stage
        article.save()

        logger.info("Imported article with article ID %d" % article.pk)
        seen.add(article_dict["ojs_id"])


def import_unassigned_articles(ojs_client, journal):
    articles = ojs_client.get_articles("unassigned")
    for article_dict in articles:
        article = import_article_metadata(article_dict, journal, ojs_client)

        import_review_data(article_dict, article, ojs_client)

        calculate_article_stage(article_dict, article)
        article.stage = submission_models.UNASSIGNED
        article.save()

        logger.info("Imported article with article ID %d" % article.pk)


def import_in_review_articles(ojs_client, journal):
    articles = ojs_client.get_articles("in_review")
    for article_dict in articles:
        article = import_article_metadata(article_dict, journal, ojs_client)

        import_review_data(article_dict, article, ojs_client)

        calculate_article_stage(article_dict, article)
        article.stage = submission_models.STAGE_UNDER_REVIEW
        article.save()

        logger.info("Imported article with article ID %d" % article.pk)

def import_in_editing_articles(ojs_client, journal):
    articles = ojs_client.get_articles("in_editing")
    for article_dict in articles:
        article = import_article_metadata(article_dict, journal, ojs_client)

        import_review_data(article_dict, article, ojs_client)
        import_copyediting(article_dict, article, ojs_client)
        import_typesetting(article_dict, article, ojs_client)

        stage = calculate_article_stage(article_dict, article)
        if (
            stage == submission_models.STAGE_UNASSIGNED
            or stage in submission_models.REVIEW_STAGES
        ):
            # If an article is in copyediting but there is no copyedit
            # data yet, we have to override the calculation
            stage = submission_models.STAGE_EDITOR_COPYEDITING
            create_workflow_log(article, stage)
        article.stage = stage
        article.save()

        logger.info("Imported article with article ID %d" % article.pk)


def import_issues(ojs_client, journal):
    for issue_dict in ojs_client.get_issues():
        issue = import_issue_metadata(issue_dict, ojs_client, journal)
        logger.info("Imported Issue: %s " % issue)


def import_collections(ojs_client, journal):
    for collection_dict in ojs_client.get_collections():
        collection = import_collection_metadata(
            collection_dict, ojs_client, journal,
        )
        logger.info("Imported collection: %s " % collection)


def import_sections(ojs_client, journal):
    for section_dict in ojs_client.get_sections():
        section = import_section_metadata(section_dict, ojs_client, journal)
        logger.info("Imported Section: %s " % section)


def import_metrics(ojs_client, journal):
    try:
        metrics_data = ojs_client.get_metrics()
    except Exception as e:
        logger.warning("Couldn't retrieve metrics: %s" % e)
    else:
        for article_views in metrics_data["views"]:
            import_article_metrics(
                article_views["id"], journal,
                views=int(article_views["count"]),
            )
        for article_downloads in metrics_data["downloads"]:
            import_article_metrics(
                article_downloads["id"], journal,
                downloads=int(article_downloads["count"]),
            )


def import_users(ojs_client, journal):
    for user in ojs_client.get_users():
        account, created = import_user_metadata(user, journal)
        if created:
            logger.info("New Imported user: %s", account.username)
        else:
            logger.info("re-imported user: %s", account.username)
