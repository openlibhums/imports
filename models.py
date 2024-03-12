from django.db import models
from django.utils import timezone

from utils import notify_helpers


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
        if self.created_articles.count() and self.csvimportcreatearticle_set.first():
            return self.csvimportcreatearticle_set.first().imported
        elif self.updated_articles.count() and self.csvimportupdatearticle_set.first():
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
    ojs_id = models.IntegerField(
        null=True,
        blank=True,
    )
    ojs_ref = models.CharField(max_length=10, blank=True, null=True)
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


class OJSFile(models.Model):
    ojs_id = models.IntegerField()
    journal = models.ForeignKey('journal.Journal', on_delete=models.CASCADE)
    file = models.ForeignKey(
        'core.File',
        on_delete=models.CASCADE,
    )


class AutomatedImportNotification(models.Model):
    email = models.EmailField(
        help_text='Email address of user to receive notification '
                  'of automatic import logs.',
    )

    def send_notification(self, articles, errors, request):
        log_dict = {
            'level': 'Info',
            'action_type': 'Contact Production Staff',
            'types': 'Email',
            'target': None
        }
        message = f"""
        <p>The following ZIP files were being imported:<p>
        <p>{ articles }</p>>
        <p>The following errors were detected during import:
        <p>{ errors }</p>
        <p>
        Regards
        <br />
        Janeway
        </p>
        """
        notify_helpers.send_email_with_body_from_user(
            request,
            'Janeway Article Import Notification',
            self.email,
            message,
            log_dict=log_dict,
        )


class CitationFormat(models.Model):
    journal = models.OneToOneField(
        'journal.Journal',
        on_delete=models.CASCADE,
    )
    format = models.CharField(
        max_length=255,
        blank=True,
    )

    def __str__(self):
        return f"{self.journal.name}: {self.format}"


class SectionMap(models.Model):
    section = models.ForeignKey(
        'submission.Section',
        on_delete=models.CASCADE,
    )
    article_type = models.CharField(
        max_length=100,
        blank=True,
    )

    def __str__(self):
        return f"{self.article_type} mapped to {self.section.name}"
