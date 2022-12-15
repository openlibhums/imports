Article Images Import
=====================

The article images import tool allows you to supply an article identifier and a URL for an image. Janeway will download the image and set it as the articles large image file (also known as the hero image).

.. warning:: You MUST ensure you have a license/permission to download and use the image. We recommend Unsplash, where Images are licensed similar to CC0. The URL **MUST** be directly to the image, not the landing page. On Unsplash you can get this by right-clicking on the "Download free" button and selecting "Copy link address".

1. Download the :download:`article image import template <_static/article_images_import_template.csv>`.
2. Fill in the details, you can add on article per line.
3. On the Imports Plugin main page select **Article Images** and click **Start Import**.
4. Select your CSV and **Upload it**.
5. Click **Import** to complete the process.

.. tip:: Download the :download:`article image import sample <_static/article_images_import_sample.csv>` CSV to see example data.

Metadata Field Reference
------------------------

===================== ========================================
Field                 Notes
===================== ========================================
Identifier Type       Should be either id, doi or pub-id
Identifier            The corresponding ID, DOI or Pub-ID
URL                   A URL leading directly to an image file.
===================== ========================================