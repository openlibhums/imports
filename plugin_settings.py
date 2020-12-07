PLUGIN_NAME = 'Import Plugin'
DESCRIPTION = 'This plugin is a collection of import scripts.'
AUTHOR = 'Birkbeck Centre for Technology and Publishing'
VERSION = '1.3'
SHORT_NAME = 'imports'
MANAGER_URL = 'imports_index'
JANEWAY_VERSION = "1.3.8"

from utils import models


def install():
    new_plugin, created = models.Plugin.objects.get_or_create(
        name=SHORT_NAME,
        enabled=True,
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
