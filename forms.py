from django import forms

from plugins.imports import models


class WordpressForm(forms.ModelForm):

    class Meta:
        model = models.WordPressImport
        fields = (
            'url',
            'username',
            'password',
            'user',
        )
        
        widgets = {
            'password': forms.PasswordInput
        }
