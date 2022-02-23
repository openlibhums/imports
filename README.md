# Imports
A plugin for importing content into Janeway.

## Installation instructions
 - Clone the project onto the plugins path of your Janeway installation ('/path/to/janeway/src/plugins')


## Import / Export / Update
This tool lets you import, export, and update article metadata in batches, especially for articles in production.

See https://janeway-imports.readthedocs.io/en/latest/import_export_update.html

## Importers with a web interface
 - Editorial team import (from CSV file)
 - Reviewer database import (from CSV file)
 - Article metadata (from CSV file) (for use with backlist content)
 - Article images (from CSV file)
 - Wordpress news items

This importers can be accessed from the Janeway journal manager under the path `/plugins/imports`


## Requirements
In addition to the base Janeway requirements this plugin needs `python-wordpress-xmlrpc` version 2.3.

You can install it using pip: `pip install python-wordpress-xmlrpc==2.3`
