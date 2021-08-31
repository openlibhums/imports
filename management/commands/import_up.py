import getpass
from journal import models

from django.core.management.base import BaseCommand
from plugins.imports import ojs
from plugins.imports.management.commands import import_ojs


class Command(import_ojs.Command):
    """ Imports back content from target UP Journal"""
    IMPORT_CLIENT = ojs.clients.UPJanewayClient


    help = "Imports issues and articles from the target UP journal"
