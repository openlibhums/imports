from django import forms
from core.validators FileTypeValidator


class CSVField(forms.FielField):
    """ An extension of FileField to validate csv extension and mimetype"""
    default_validators = [
        FileTypeValidator(extensions={".csv"}, mimetypes="text/csv"),
    ]


class CSVImportForm(forms.FiForm):
     csv_file = forms.CSVField()
