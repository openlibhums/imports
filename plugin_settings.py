PLUGIN_NAME = 'Import Plugin'
DESCRIPTION = 'This plugin is a collection of import scripts.'
AUTHOR = 'Andy Byers'
VERSION = '1.0'
SHORT_NAME = 'imports'
MANAGER_URL = 'imports_index'

from utils import models


def install():
    new_plugin, created = models.Plugin.objects.get_or_create(name=SHORT_NAME, version=VERSION, enabled=True)

    if created:
        print('Plugin {0} installed.'.format(PLUGIN_NAME))
    else:
        print('Plugin {0} is already installed.'.format(PLUGIN_NAME))


def hook_registry():
    # On site load, the load function is run for each installed plugin to generate
    # a list of hooks.
    return {}
