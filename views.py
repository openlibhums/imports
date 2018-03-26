import csv
import os

from django.shortcuts import render, redirect
from django.contrib import messages
from django.core.urlresolvers import reverse
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404

from core import files
from plugins.imports import utils


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
def editorial_load(request):
    """
    Allows a user to upload a csv for processing into Editorial Teams.
    :param request: HttpRequest
    :return: HttpResponse or, on post, HttpRedirect
    """
    if request.POST and request.FILES:
        file = request.FILES.get('file')
        filename, path = files.save_file_to_temp(file)
        return redirect(reverse('imports_editorial_import', kwargs={'filename': filename}))

    template = 'import/editorial_load.html'
    context = {}

    return render(request, template, context)


@staff_member_required
def editorial_import(request, filename):
    """
    Processes and displays the editorial import data
    :param request: HttpRequest
    :param filename: the name of a temp file
    :return: HttpResponse
    """
    path = files.get_temp_file_path_from_name(filename)

    if not os.path.exists(path):
        raise Http404()

    file = open(path, 'r')
    reader = csv.reader(file)

    if request.POST:
        utils.import_editorial_team(request, reader)

    template = 'import/editorial_import.html'
    context = {
        'filename': filename,
        'reader': reader,
    }

    return render(request, template, context)



