from django import forms

from plugins.imports import models
from journal import models as journal_models
from submission import models as submission_models


class ArticleExportFilterForm(forms.Form):
    """
    Filters the article export list by workflow stage and/or issue.
    Issues are limited to the current journal when one is supplied.
    """
    stage = forms.ChoiceField(
        required=False,
        widget=forms.Select(attrs={'onchange': 'this.form.submit()'}),
    )
    issue = forms.ModelChoiceField(
        required=False,
        queryset=journal_models.Issue.objects.none(),
        empty_label='- Filter by Issue -',
        widget=forms.Select(attrs={'onchange': 'this.form.submit()'}),
    )

    def __init__(self, *args, **kwargs):
        journal = kwargs.pop('journal', None)
        super().__init__(*args, **kwargs)

        stage_choices = [('', '- Filter by Stage -')]
        if journal:
            stage_choices += [
                (element.stage, element.element_name.capitalize())
                for element in journal.workflow().elements.all()
            ]
            self.fields['issue'].queryset = journal_models.Issue.objects.filter(
                journal=journal,
            )
        else:
            self.fields['issue'].queryset = journal_models.Issue.objects.all()

        stage_choices += [
            (submission_models.STAGE_PUBLISHED, 'Published'),
            (submission_models.STAGE_REJECTED, 'Rejected'),
        ]
        self.fields['stage'].choices = stage_choices


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
