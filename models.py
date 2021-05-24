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

    def __str__(self):
        return '{} export file for {}'.format(
            self.file,
            self.article.title,
        )