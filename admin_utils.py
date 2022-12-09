__copyright__ = "Copyright 2022 Birkbeck, University of London"
__author__ = "Martin Paul Eve, Andy Byers, Mauro Sanchez and Joseph Muller"
__license__ = "AGPL v3"
__maintainer__ = "Birkbeck, University of London"

from django.contrib import admin
from plugins.imports import models as imports_models


class CSVImportCreateArticleInline(admin.TabularInline):
    model = imports_models.CSVImportCreateArticle
    extra = 0
    raw_id_fields = ('csv_import', 'article')


class CSVImportUpdateArticleInline(admin.TabularInline):
    model = imports_models.CSVImportUpdateArticle
    extra = 0
    raw_id_fields = ('csv_import', 'article')
