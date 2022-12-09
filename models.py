from django.db import models
from django.utils import timezone


class WordPressImport(models.Model):
    url = models.URLField(
        help_text='Base URL eg. https://janeway.systems',
        verbose_name='URL',
    )
    username = models.CharField(max_length=255)
    password = models.CharField(max_length=255)
    user = models.ForeignKey(
        'core.Account',
        on_delete=models.CASCADE,
        help_text='News items will be '
                  'created with this user '
                  'as the owner.',
    )

    def __str__(self):
        return 'Import from {url}'.format(url=self.url)


class ExportFile(models.Model):
    article = models.ForeignKey(
        'submission.Article',
        on_delete=models.CASCADE,
    )
    file = models.ForeignKey(
        'core.File',
        on_delete=models.CASCADE,
    )
    journal = models.ForeignKey(
        'journal.Journal',
        on_delete=models.CASCADE,
    )

    class Meta:
        unique_together = ('article', 'file', 'journal')

    def __str__(self):
        return '{} export file for {}'.format(
            self.file,
            self.article.title,
        )


class CSVImport(models.Model):
    filename = models.CharField(max_length=999)
    created_articles = models.ManyToManyField(
        to="submission.Article", blank=True,
        through="imports.CSVImportUpdateArticle",
        related_name="csv_import_creation",
    )
    updated_articles = models.ManyToManyField(
        to="submission.Article", blank=True,
        through="imports.CSVImportCreateArticle",
        related_name="csv_import_updates",
    )

    def timestamp(self):
        if self.csvimportcreatearticle_set:
            return self.csvimportcreatearticle_set.first().imported
        elif self.csvimportupdatearticle_set:
            return self.csvimportupdatearticle_set.first().imported

    def __str__(self):
        return f'{self.filename}'


class CSVImportCreateArticle(models.Model):
    csv_import = models.ForeignKey(
        "imports.CSVImport",
        null=True,
        on_delete=models.SET_NULL,
    )
    article = models.ForeignKey(
        "submission.Article",
        on_delete=models.CASCADE,
    )
    imported = models.DateTimeField(default=timezone.now)
    file_id = models.CharField(max_length=999, blank=True, null=True)


class CSVImportUpdateArticle(CSVImportCreateArticle):
    pass


class OJS3Section(models.Model):
    """Stores an ojs 3 section ID and maps it to the section in Janeway"""
    ojs_id = models.IntegerField()
    journal = models.ForeignKey('journal.Journal', on_delete=models.CASCADE)
    section = models.ForeignKey(
        'submission.Section', blank=True, null=True,
        on_delete=models.CASCADE,
    )

    class Meta:
        unique_together = (
            ('ojs_id', 'journal'),
            ('ojs_id', 'section'),
        )


class OJSAccount(models.Model):
    ojs_id = models.IntegerField()
    journal = models.ForeignKey('journal.Journal', on_delete=models.CASCADE)
    account = models.ForeignKey(
        'core.Account',
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        unique_together = (
            ('ojs_id', 'journal', 'account'),
        )
