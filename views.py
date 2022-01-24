import csv
import os
import shutil

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.urlresolvers import reverse
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import translation

from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes

from api import permissions as api_permissions
from core import files, models as core_models
from plugins.imports import utils, forms, logic, models, export, serializers
from journal import models as journal_models
from submission import models as submission_models
from security import decorators


@staff_member_required
def index(request):
    """
    Displays a list of import types.
    :param request: HttpRequest
    :return: HttpResponse
    """

    template = "import/index.html"
    context = {
        'article_metadata_headers': utils.CSV_HEADER_ROW,
        'mauro': utils.CSV_MAURO,
        'martin': utils.CSV_MARTIN,
        'andy': utils.CSV_ANDY,
    }

    return render(request, template, context)


@staff_member_required
def import_load(request):
    """
    Allows a user to upload a csv for processing into Editorial Teams.
    :param request: HttpRequest
    :return: HttpResponse or, on post, HttpRedirect
    """
    request_type = request.GET.get('type')

    if request.POST and request.FILES:
        file = request.FILES.get('file')
        filename, path = files.save_file_to_temp(file)
        reverse_url = '{url}?type={request_type}'.format(
            url=reverse(
                'imports_action',
                kwargs={'filename': filename}),
            request_type=request_type,
        )
        return redirect(reverse_url)

    template = 'import/editorial_load.html'
    context = {
        'type': request_type,
    }

    return render(request, template, context)


@staff_member_required
def import_action(request, filename):
    """
    Processes and displays the editorial import data
    :param request: HttpRequest
    :param filename: the name of a temp file
    :return: HttpResponse
    """
    request_type = request.GET.get('type')
    path = files.get_temp_file_path_from_name(filename)
    errors = error_file = None

    if not os.path.exists(path):
        raise Http404()

    if request_type == 'update':
        path, folder_path, errors = utils.prep_update_file(path)

        if errors:
            # If we have any errors delete the temp folder and redirect back.
            messages.add_message(
                request,
                messages.ERROR,
                ', '.join(errors)
            )
            shutil.rmtree(folder_path)
            return redirect(
                reverse(
                    'import_export_articles_all'
                )
            )
    file = open(path, 'r', encoding="utf-8-sig")
    if request_type == 'update':
        reader = csv.DictReader(file)
    else:
        reader = csv.reader(file)

    if request.POST:
        if request_type == 'editorial':
            utils.import_editorial_team(request, reader)
        if request_type == 'reviewers':
            utils.import_reviewers(request, reader)
        elif request_type == 'contacts':
            utils.import_contacts_team(request, reader)
        elif request_type == 'submission':
            utils.import_submission_settings(request, reader)
        elif request_type == 'article_metadata':
            with translation.override(settings.LANGUAGE_CODE):
                _, errors, error_file = utils.import_article_metadata(
                    request, reader)
        elif request_type == 'update':

            # Verify a few things to help user spot problems
            errors = []
            actions = []

            with open(path, 'r', encoding='utf-8-sig') as verify_headers_file:
                errors, actions = utils.verify_headers(
                    csv.DictReader(verify_headers_file),
                    errors,
                    actions,
                )

            with open(path, 'r', encoding='utf-8-sig') as verify_stages_file:
                errors, actions = utils.verify_stages(
                    csv.DictReader(verify_stages_file),
                    request.journal,
                    errors,
                    actions,
                )

            if not errors:
                errors, actions = utils.update_article_metadata(
                    request,
                    reader,
                    folder_path,
                )

        else:
            raise Http404
        if not errors:
            files.unlink_temp_file(path)
            messages.add_message(request, messages.SUCCESS, 'Import complete')
            return redirect(reverse('imports_index'))

    template = 'import/editorial_import.html'
    context = {
        'filename': filename,
        'reader': reader,
        'errors': errors,
        'error_file': error_file,
        'type': request_type,
    }

    return render(request, template, context)


@staff_member_required
def review_forms(request):
    """
    Allows staff to select a group of journals to have a default form generated for them.
    :param request: HttpRequest
    :return: HttpResponse or HttpRedirect
    """
    journals = journal_models.Journal.objects.all()

    if request.POST:
        utils.generate_review_forms(request)
        return redirect(reverse('imports_index'))

    template = 'import/review_forms.html'
    context = {'journals': journals}

    return render(request, template, context)


@staff_member_required
def favicon(request):
    """
    Lets a staff member bulk load a favicon onto multiple journals.
    :param request: HttpRequest
    :return: HttpResponse or HttpRedirect
    """
    journals = journal_models.Journal.objects.all()

    if request.POST and request.FILES:
        utils.load_favicons(request)
        messages.add_message(request, messages.SUCCESS, 'Favicons loaded')
        return redirect(reverse('imports_index'))

    template = 'import/favicon.html'
    context = {'journals': journals}

    return render(request, template, context)


@staff_member_required
def article_images(request):
    """
    Lets staff upload a file to set an article's large image file.
    :param request: HttpRequest
    :return: HttpResponse or HttpRedirect
    """

    filename = request.GET.get('filename')
    reader = None

    if filename:
        path = files.get_temp_file_path_from_name(filename)
        file = open(path, 'r')
        reader = csv.reader(file)

    if request.POST and request.FILES.get('file'):
        file = request.FILES.get('file')
        filename, path = files.save_file_to_temp(file)
        reverse_url = '{url}?filename={filename}'.format(url=reverse('imports_article_images'),
                                                        filename=filename)
        return redirect(reverse_url)

    if request.POST and 'import' in request.POST:
        errors = utils.load_article_images(request, reader)

        if not errors:
            messages.add_message(request, messages.SUCCESS, 'Article images loaded.')
        else:
            for error in errors:
                messages.add_message(request, messages.WARNING, error)

        return redirect(reverse('import_index'))

    template = 'import/article_images.html'
    context = {
        'filename': filename,
        'reader': reader,
    }

    return render(request, template, context)


@staff_member_required
def csv_example(request):
    """
    Serves up an example metadata csv
    :param request: HttpRequest
    :return: CSV File
    """
    filepath = files.get_temp_file_path_from_name('metadata.csv')

    with open(filepath, "w") as f:
        wr = csv.writer(f, quoting=csv.QUOTE_ALL)
        wr.writerow(utils.CSV_HEADER_ROW.split(","))
        wr.writerow(utils.CSV_MAURO.split(","))

        return files.serve_temp_file(filepath, 'metadata.csv')


@staff_member_required
def serve_failed_rows(request, tmp_file_name):
    if not tmp_file_name.startswith(utils.TMP_PREFIX):
        raise Http404
    filepath = files.get_temp_file_path_from_name(tmp_file_name)
    if not os.path.exists(filepath):
        raise Http404
    return files.serve_temp_file(filepath, 'failed_rows.csv')


@staff_member_required
def wordpress_xmlrpc_import(request):
    """
    Pulls in posts from a Wordpress site over XMLRPC
    :param request: HttpRequest
    :return: HttpResponse
    """
    form = forms.WordpressForm()

    if request.POST:
        form = forms.WordpressForm(request.POST)

        if form.is_valid():
            new_import = form.save()
            return redirect(
                reverse(
                    'wordpress_posts',
                    kwargs={'import_id': new_import.pk},
                )
            )

    template = 'import/wordpress_xmlrpc_import.html'
    context = {
        'form': form,
    }

    return render(request, template, context)


@staff_member_required
def wordpress_posts(request, import_id):
    import_object = get_object_or_404(
        models.WordPressImport,
        pk=import_id,
    )
    posts = list()
    offset = 0
    increment = 20

    while True:
        new_posts = logic.get_posts(import_object, increment, offset)
        posts.extend(new_posts)
        if len(new_posts) == 0:
            break

        offset = offset + increment
        print(offset, posts)

    if request.POST:
        ids_to_import = request.POST.getlist('post')
        logic.import_posts(ids_to_import, posts, request, import_object)
        messages.add_message(
            request,
            messages.SUCCESS,
            'Import complete, deleting details.'
        )

        return redirect(
            reverse(
                'wordpress_xmlrpc_import'
            )
        )

    template = 'import/wordpress_posts.html'
    context = {
        'posts': posts,
    }

    return render(request, template, context)


@decorators.has_journal
@decorators.editor_user_required
def export_article(request, article_id, format='csv'):
    """
    A view that exports either a CSV or HTML representation of an article.
    :param request: HttpRequest object
    :param article_id: Article object PK
    :param format: string, csv or html
    :return: HttpResponse or Http404
    """
    article = get_object_or_404(
        submission_models.Article,
        pk=article_id,
        journal=request.journal,
    )
    files = core_models.File.objects.filter(
        article_id=article.pk,
    )

    if request.GET.get('action') == 'output_html':
        context = {
            'article': article,
            'journal': request.journal,
            'files': files,
        }

        return render(
            request,
            'import/export.html',
            context,
        )

    if format == 'csv':
        return export.export_csv(request, article, files)
    elif format == 'html':
        return export.export_html(request, article, files)

    raise Http404


@decorators.has_journal
@decorators.editor_user_required
def export_articles_all(request):
    """
    A view that displays all articles in a journal and allows export.
    """
    element = request.GET.get('element')

    articles = submission_models.Article.objects.filter(
        journal=request.journal,
    ).select_related(
        'correspondence_author',
    )

    if element in ['Published', 'Rejected']:
        articles = articles.filter(stage=element)
    elif element:
        workflow_element = core_models.WorkflowElement.objects.get(
            journal=request.journal,
            stage=element,
        )
        articles = articles.filter(stage__in=workflow_element.stages)

    workflow_type, proofing_assignments = utils.get_proofing_assignments_for_journal(
        request.journal,
    )

    for article in articles:
        article.export_files = article.exportfile_set.all()
        article.export_file_pks = [ef.file.pk for ef in article.exportfile_set.all()]

        article.proofing_files = utils.proofing_files(workflow_type, proofing_assignments, article)

    if request.POST:
        if 'export_all' in request.POST:
            csv_path, csv_name = export.export_using_import_format(articles)
            return export.zip_export_files(request.journal, articles, csv_path)

    template = 'import/articles_all.html'
    context = {
        'articles_in_stage': articles,
        'stages': submission_models.STAGE_CHOICES,
        'selected_element': element,
    }

    return render(request, template, context)


@permission_classes((api_permissions.IsEditor, ))
class ExportFilesViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.ExportFileSerializer
    http_method_names = ['get', 'post', 'delete']

    def get_queryset(self):
        if self.request.journal:
            queryset = models.ExportFile.objects.filter(
                article__journal=self.request.journal,
            )
        else:
            queryset = models.ExportFile.objects.all()

        return queryset

