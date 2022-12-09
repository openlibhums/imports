from django.contrib import admin

from plugins.imports import models
from plugins.imports import admin_utils


class ExportFileAdmin(admin.ModelAdmin):
    list_display = (
        'article',
        'file',
        'journal',
    )
    list_filter = (
        'journal',
    )
    raw_id_fields = (
        'article',
        'file',
    )
    search_fields = (
        'article__pk',
        'article__title',
        'file__original_filename',
    )


class CSVImportAdmin(admin.ModelAdmin):
    "Displays import runs using the IEU plugin"
    list_display = (
        'filename',
        'timestamp',
    )
    list_filter = (
        'updated_articles__journal',
        'created_articles__journal',
    )
    search_fields = (
        'updated_articles__pk',
        'updated_articles__title',
        'created_articles__pk',
        'created_articles__title',
        'filename',
    )

    inlines = [
        admin_utils.CSVImportCreateArticleInline,
        admin_utils.CSVImportUpdateArticleInline,
    ]


class CSVImportArticleAdmin(admin.ModelAdmin):
    list_display = (
        'article',
        'journal',
        'imported',
        'csv_import',
    )
    list_filter = (
        'article__journal',
        'imported',
        'csv_import',
    )
    search_fields = (
        'article__pk',
        'article__title',
        'csv_import__filename',
    )
    raw_id_fields = (
        'article',
        'csv_import',
    )
    date_hierarchy = ('imported')

    def journal(self, obj):
        return obj.article.journal.code if obj else ''


for pair in [
    (models.ExportFile, ExportFileAdmin),
    (models.CSVImport, CSVImportAdmin),
    (models.CSVImportCreateArticle, CSVImportArticleAdmin),
    (models.CSVImportUpdateArticle, CSVImportArticleAdmin),
]:
    admin.site.register(*pair)
