import csv
import os

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.urlresolvers import reverse
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404

from core import files
from plugins.imports import utils, forms, logic, models
from journal import models as journal_models


@staff_member_required
def index(request):
    """
    Displays a list of import types.
    :param request: HttpRequest
    :return: HttpResponse
    """

    template = "import/index.html"
    context = {}

    return render(request, template, context)


@staff_member_required
def import_load(request):
    """
    Allows a user to upload a csv for processing into Editorial Teams.
    :param request: HttpRequest
    :return: HttpResponse or, on post, HttpRedirect
    """
    type = request.GET.get('type')

    if request.POST and request.FILES:
        file = request.FILES.get('file')
        filename, path = files.save_file_to_temp(file)
        reverse_url = '{url}?type={type}'.format(url=reverse('imports_action', kwargs={'filename': filename}),
                                                 type=type)
        return redirect(reverse_url)

    template = 'import/editorial_load.html'
    context = {
        'type': type,
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
    type = request.GET.get('type')
    path = files.get_temp_file_path_from_name(filename)

    if not os.path.exists(path):
        raise Http404()

    file = open(path, 'r')
    reader = csv.reader(file)

    if request.POST:
        if type == 'editorial':
            utils.import_editorial_team(request, reader)
        elif type == 'contacts':
            utils.import_contacts_team(request, reader)
        elif type == 'submission':
            utils.import_submission_settings(request, reader)
        elif type == 'article_metadata':
            utils.import_article_metadata(request, reader)
        else:
            raise Http404
        files.unlink_temp_file(path)
        messages.add_message(request, messages.SUCCESS, 'Import complete')
        return redirect(reverse('imports_index'))

    template = 'import/editorial_import.html'
    context = {
        'filename': filename,
        'reader': reader,
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
    header_row = "Article identifier, Article title,Section Name, Volume number, Issue number, Subtitle, Abstract, " \
                 "publication stage, date/time accepted, date/time publishded , DOI, Author Salutation, " \
                 "Author first name, Author last name, Author Institution, Author Email, Is Corporate (Y/N)".split(',')
    example_row = "1,some title,Articles,1,1,some subtitle,the abstract,Published,2018-01-01T09:00:00," \
                  "2018-01-02T09:00:00,10.1000/xyz123,Mr,Mauro,Sanchez,BirkbeckCTP,msanchez@journal.com,N".split(',')

    filepath = files.get_temp_file_path_from_name('metadata.csv')

    with open(filepath, "w") as f:
        wr = csv.writer(f)
        wr.writerow(header_row)
        wr.writerow(example_row)

        return files.serve_temp_file(filepath, 'metadata.csv')


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

    posts = logic.get_posts(import_object)

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
