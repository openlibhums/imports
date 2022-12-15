JATS Import
===========

The JATS import tool allows you to upload a single article as a JATS XML file or a zip (.zip) file containing one or more JATS files and their corresponding figure files.

.. note:: Janeway, by default, supports JATS 1.2.

If you want to import a single JATS file with no figures:

1. On the Imports Plugin main page select **JATS Import** and click **Start Import**.
2. Select your JATS file.
3. Click **Upload and Import**.

If you want to import multiple JATS files or a single JATS file with its figures you first need to prepare a zip (.zip) file.

The top level directory can be called anything you like. Inside that directory you should add you JATS XML files. Image files can be added and should match the xlink:href of the figure or graphic.

- articles (top level directory)
    - article_1234.xml
    - article_1234_fig_1.jpg
    - article_9876.xml
    - article_9876_fig_1.jpg
    - article_9876_fig_2.jpg

If the href of the images includes a directory name you should include that directory:

- articles/ (top level directory)
    - article_1234.xml
    - article_9876.xml
    - figures/
        - article_1234_fig_1.jpg
        - article_9876_fig_1.jpg
        - article_9876_fig_2.jpg

Once you have prepared you zip file you can follow the instructions above and select the zip file in place of the JATS file.

.. tip:: Download the :download:`JATS import sample <_static/jats_import_sample.zip>` CSV to see an example zip file.
