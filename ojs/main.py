from plugins.imports.ojs.importers import (
    calculate_article_stage,
    import_article_metadata,
    import_copyediting,
    import_publication,
    import_review_data,
)
from utils.logger import get_logger

logger = get_logger(__name__)


def import_articles(ojs_client, journal):
    review_articles = ojs_client.get_articles("published")
    for article_dict in review_articles:
        article = import_article_metadata(article_dict, journal, ojs_client)

        import_review_data(article_dict, article, ojs_client)
        import_copyediting(article_dict, article, ojs_client)
        import_publication(article_dict, article, ojs_client)

        stage = calculate_article_stage(article_dict, article)
        article.stage = stage
        article.save()

        logger.info("Imported article with article ID %d" % article.pk)
