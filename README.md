# Imports
A plugin for importing content into Janeway.

# Installation instructions
 - Clone the project onto the plugins path of your janeway installation ('/path/to/janeway/src/plugins')


## Importers with a web interface
 - Editorial team import (from CSV file)
 - Reviewer database import (from CSV file)
 - Article metadata (from CSV file)
 - Article images (from CSV file)
 - Wordpress news items

This importers can be accesed from the janeway journal manager under the path `/plugins/imports`


# Requirements
In addition to the base Janeway requirements this plugin needs `python-wordpress-xmlrpc` version 2.3.

You can install it using pip: `pip install python-wordpress-xmlrpc==2.3`

