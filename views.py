import csv
import os

from django.shortcuts import render, redirect
from django.contrib import messages
from django.core.urlresolvers import reverse
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404

from core import files
from plugins.imports import utils
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

