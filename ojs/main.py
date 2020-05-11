from plugins.imports.ojs.importers import (
    calculate_article_stage,
    import_article_metadata,
    import_article_metrics,
    import_copyediting,
    import_issue_metadata,
    import_publication,
    import_review_data,
    import_user_metadata,
)
from utils.logger import get_logger

logger = get_logger(__name__)


def import_articles(ojs_client, journal):
    articles = ojs_client.get_articles("published")
    for article_dict in articles:
        article = import_article_metadata(article_dict, journal, ojs_client)

        import_review_data(article_dict, article, ojs_client)
        import_copyediting(article_dict, article, ojs_client)
        import_publication(article_dict, article, ojs_client)

        stage = calculate_article_stage(article_dict, article)
        article.stage = stage
        article.save()

        logger.info("Imported article with article ID %d" % article.pk)


def import_issues(ojs_client, journal):
    for issue in ojs_client.get_issues():
        issue = import_issue_metadata(issue, ojs_client, journal)
        logger.info("Imported Issue: %s " % issue)


def import_metrics(ojs_client, journal):
    metrics_data = ojs_client.get_metrics()
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
        import_user_metadata(user, journal)
