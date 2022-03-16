from django.contrib import admin

from plugins.imports.models import (
    CSVImport,
    CSVImportCreateArticle,
    CSVImportUpdateArticle,
)


class CSVImportAdmin(admin.ModelAdmin):
    "Displays import runs using the IEU plugin"
    list_display = ('filename',)
    list_filter = ('updated_articles__journal', 'created_articles__journal')
    search_fields = ('updated_articles__title', 'created_articles__title', 'filename')

class CSVImportArticleAdmin(admin.ModelAdmin):
    list_display = ('csv_import', 'article', 'imported')
    list_filter = ('article__journal', 'csv_import__filename')
    search_fields = ('article__title', 'csv_import__filename', 'article__id')



for pair in [
    (CSVImport, CSVImportAdmin),
    (CSVImportCreateArticle, CSVImportArticleAdmin),
    (CSVImportUpdateArticle, CSVImportArticleAdmin),
]:
	admin.site.register(*pair)

