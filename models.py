from django.db import models


class WordPressImport(models.Model):
    url = models.URLField(
        help_text='Base URL eg. https://janeway.systems',
        verbose_name='URL',
    )
    username = models.CharField(max_length=255)
    password = models.CharField(max_length=255)
    user = models.ForeignKey(
        'core.Account',
        help_text='News items will be '
                  'created with this user '
                  'as the owner.')
    
    def __str__(self):
        return 'Import from {url}'.format(url=self.url)

      
class ExportFile(models.Model):
    article = models.ForeignKey('submission.Article')
    file = models.ForeignKey('core.File')
    journal = models.ForeignKey('journal.Journal')

    class Meta:
        unique_together = ('article', 'file', 'journal')

    def __str__(self):
        return '{} export file for {}'.format(
            self.file,
            self.article.title,
        )

      
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
        'core.Account', blank=True, null=True,
    )

    class Meta:
        unique_together = (
            ('ojs_id', 'journal', 'account'),
        )