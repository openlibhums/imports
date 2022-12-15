Article Review Import
=====================

The article review import tool allows you to create peer reviews by uploading a CSV (Comma Seperated Value) file.

.. warning:: This tool only allows the import of reviews as files, as such you may need an administrator to load the files onto the server for you.

To import peer reviews accounts:

1. Download the :download:`article review import template <_static/peer_review_import_template.csv>`.
2. Enter your peer review details, one per row.
3. On the Imports Plugin main page select **Reviewer Import** and click **Start Import**.
4. Select your CSV and, if you want you reviewers to receive a password reset notification check that option.
5. Click **Import** to complete the process.

Metadata Field Reference
------------------------

===================== ==========================================================
Field                 Notes
===================== ==========================================================
Identifier Type       Should be either id, doi or pub-id
Identifier            The corresponding ID, DOI or Pub-ID
Review recommendation Either: accept, minor_revisions, major_revisions or reject
Review filename       Path to a file on disk eg: /home/username/files/review.pdf
Date Fields           All date fields should be in ISO format YYYY-MM-DD
Visibility            Either: open, blind or double-blind
===================== ==========================================================

.. tip:: Download the :download:`article review import sample <_static/peer_review_import_sample.csv>` CSV to see example data.