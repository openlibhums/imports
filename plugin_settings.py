PLUGIN_NAME = 'Import Plugin'
DESCRIPTION = 'This plugin is a collection of import scripts.'
AUTHOR = 'Birkbeck Centre for Technology and Publishing'
VERSION = '1.5'
SHORT_NAME = 'imports'
MANAGER_URL = 'imports_index'
JANEWAY_VERSION = "1.3.9"

from utils import models


def install():
    new_plugin, created = models.Plugin.objects.get_or_create(
        name=SHORT_NAME,
        defaults={'version': VERSION},
    )

    if created:
        print('Plugin {0} installed.'.format(PLUGIN_NAME))
    else:
        print('Plugin {0} is already installed.'.format(PLUGIN_NAME))


def hook_registry():
    # On site load, the load function is run for each
    # installed plugin to generate
    # a list of hooks.
    return {}


UPDATE_CSV_HEADERS = [
    'Article title',
    'Article filename',
    'Article section',
    'Keywords',
    'License',
    'Language',
    'Author Salutation',
    'Author surname',
    'Author given name',
    'Author email',
    'Author institution',
    'Author is primary (Y/N)',
    'Author ORCID',
    'Article ID',
    'DOI',
    'DOI (URL form)',
    'Article sequence',
    'Journal Code',
    'Journal title',
    'ISSN',
    'Delivery formats',
    'Typesetting template',
    'Volume number',
    'Issue number',
    'Issue name',
    'Issue pub date',
    'Date Accepted',
    'Date Published',
    'Stage',
]
