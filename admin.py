from django.contrib import admin

from plugins.imports import models
from utils import admin_utils as utils_admin_utils
from plugins.imports import admin_utils as imports_admin_utils



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
        imports_admin_utils.CSVImportCreateArticleInline,
        imports_admin_utils.CSVImportUpdateArticleInline,
    ]


class CSVImportArticleAdmin(utils_admin_utils.ArticleFKModelAdmin):
    list_display = (
        '_article',
        '_journal',
        'imported',
        'csv_import',
    )
    list_filter = (
        'article__journal',
        'imported',
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


class NotificationAdmin(admin.ModelAdmin):
    list_display = ('pk', 'email')


class CitationFormatAdmin(admin.ModelAdmin):
    list_display = ('journal', 'format')
    raw_id_fields = ('journal',)


class SectionMapAdmin(admin.ModelAdmin):
    list_display = ('section', 'article_type')
    search_fields = ('article_type', 'section__name')
    raw_id_fields = ('section',)


for pair in [
    (models.ExportFile, ExportFileAdmin),
    (models.CSVImport, CSVImportAdmin),
    (models.CSVImportCreateArticle, CSVImportArticleAdmin),
    (models.CSVImportUpdateArticle, CSVImportArticleAdmin),
    (models.OJSFile,),
    (models.AutomatedImportNotification, NotificationAdmin),
    (models.CitationFormat, CitationFormatAdmin),
    (models.SectionMap, SectionMapAdmin),
]:
    admin.site.register(*pair)
