PLUGIN_NAME = 'Import Plugin'
DESCRIPTION = 'This plugin is a collection of import scripts.'
AUTHOR = 'Birkbeck Centre for Technology and Publishing'
VERSION = '1.9'
SHORT_NAME = 'imports'
MANAGER_URL = 'imports_index'
JANEWAY_VERSION = "1.5.1"

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
    return {
        'journal_admin_nav_block': {'module': 'plugins.imports.hooks', 'function': 'nav_hook'}
    }


UPDATE_CSV_HEADERS = [
    'Janeway ID',
    'Article title',
    'Article abstract',
    'Keywords',
    'Rights',
    'Licence',
    'Language',
    'Peer reviewed (Y/N)',
    'Author salutation',
    'Author given name',
    'Author middle name',
    'Author surname',
    'Author suffix',
    'Author email',
    'Author ORCID',
    'Author institution',
    'Author department',
    'Author biography',
    'Author is primary (Y/N)',
    'Author is corporate (Y/N)',
    'DOI',
    'DOI (URL form)',
    'Date accepted',
    'Date published',
    'Article number',
    'First page',
    'Last page',
    'Page numbers (custom)',
    'Competing interests',
    'Article section',
    'Stage',
    'File import identifier',
    'Journal code',
    'Journal title override',
    'ISSN override',
    'Volume number',
    'Issue number',
    'Issue title',
    'Issue pub date',
    'PDF URI',
]

