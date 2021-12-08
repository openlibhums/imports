import zipfile
import os
import uuid
import csv
from uuid import uuid4

from bs4 import BeautifulSoup

from django.template.loader import render_to_string

from core import files

UPDATE_HEADER_ROW = "Article title,Article filename,Article abstract,Article section,Keywords,License,Language,Author Salutation,Author surname," \
                    "Author given name,Author email,Author institution,Author is primary (Y/N),Author ORCID,Article ID," \
                    "DOI,DOI (URL form),Article sequence,Journal Code,Journal title,ISSN,Delivery formats,Typesetting template," \
                    "Volume number,Issue number,Issue name,Issue pub date,Stage"

CSV_HEADER_ROW = "Article identifier, Article title, Section Name, Volume number, Issue number, Subtitle, Abstract," \
                 "publication stage, keywords, date/time accepted, date/time publishded , DOI, Author Salutation," \
                 "Author first name,Author Middle Name, Author last name, Author Institution, Biography," \
                 "Author Email, Is Corporate (Y/N), "


def html_table_to_csv(html):
    filepath = files.get_temp_file_path_from_name(
        '{0}.csv'.format(uuid.uuid4())
    )
    soup = BeautifulSoup(str(html), 'lxml')
    with open(filepath, "w", encoding="utf-8") as f:
        wr = csv.writer(f)
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = [cell.string for cell in row.findChildren(['th', 'td'])]
                wr.writerow(cells)
            wr.writerow([])

    f.close()
    return filepath


def export_csv(request, article, article_files):
    elements = [
        'general.html',
        'authors.html',
        'files.html',
        'dates.html',
        'funding.html',
    ]

    context = {
        'article': article,
        'journal': request.journal,
        'files': article_files,
    }

    html = ''
    for element in elements:
        html = html + render_to_string(
            'import/elements/{element}'.format(element=element),
            context,
        )
    csv_file_path = html_table_to_csv(html)

    zip_file_name = 'export_{}_{}_csv.zip'.format(article.journal.code, article.pk)
    zip_path = os.path.join(files.TEMP_DIR, zip_file_name)
    zip_file = zipfile.ZipFile(zip_path, mode='w')

    zip_file.write(
        csv_file_path,
        'article_data.csv'
    )

    for file in article_files:
        zip_file.write(
            file.self_article_path(),
            file.original_filename,
        )

    zip_file.close()

    return files.serve_temp_file(zip_path, zip_file_name)


def export_html(request, article, article_files):
    html_file_path = files.create_temp_file(
        render_to_string(
            'import/export.html',
            context={
                'article': article,
                'journal': request.journal,
                'files': article_files,
            }
        ),
        '{code}-{pk}.html'.format(
            code=article.journal.code,
            pk=article.pk,
        )
    )

    zip_file_name = 'export_{}_{}_html.zip'.format(article.journal.code, article.pk)
    zip_path = os.path.join(files.TEMP_DIR, zip_file_name)
    zip_file = zipfile.ZipFile(zip_path, mode='w')
    zip_file.write(
        html_file_path,
        'article_data.html'
    )

    for file in article_files:
        zip_file.write(
            file.self_article_path(),
            file.original_filename,
        )

    zip_file.close()

    return files.serve_temp_file(zip_path, zip_file_name)


def add_first_author(article_initial_details, author_list, frozen, article):
    """
    Extends article_initial_details with the first author in author_list.
    """
    for i, author in enumerate(author_list):

        if frozen:
            correspondence_author = 'Y' if author.author and author.author == article.correspondence_author else 'N'
        else:
            correspondence_author = 'Y' if author == article.correspondence_author else 'N'

        orcid = ''
        if frozen and author.author:
            orcid = author.author.orcid
        elif author.orcid:
            orcid = author.orcid

        author_details = [
            author.author.salutation if frozen and author.author else author.salutation,
            author.last_name,
            author.first_name,
            author.author.email if frozen and author.author else author.email,
            author.institution,
            correspondence_author,
            "https://orcid.org/{}".format(orcid) if orcid else '',
        ]
        article_initial_details.extend(author_details)
        author_list = author_list.exclude(pk=author.pk)
        break

    return article_initial_details, author_list


def add_author_information(article_first_row, author_list, frozen, article):
    article_rows = []
    try:
        for i, author in enumerate(author_list):
            if frozen:
                correspondence_author = 'Y' if author.author and author.author == article.correspondence_author else 'N'
            else:
                correspondence_author = 'Y' if author == article.correspondence_author else 'N'

            orcid = ''
            if frozen and author.author:
                orcid = author.author.orcid
            elif author.orcid:
                orcid = author.orcid

            author_list = [
                author.author.salutation if frozen and author.author else author.salutation,
                author.last_name,
                author.first_name,
                author.author.email if frozen and author.author else author.email,
                author.institution,
                correspondence_author,
                "https://orcid.org/{}".format(orcid) if orcid else '',
            ]
            blank_article_row = [
                '', '', '', '', '', '', '',
            ]
            blank_article_row.extend(author_list)
            article_rows.append(blank_article_row)

        return article_rows

    except IndexError:
        return article_first_row


def export_using_import_format(articles):
    header_row = UPDATE_HEADER_ROW  # Ideally import and export should use the same thing but - meh.
    body_rows = []

    for article in articles:
        keyword_string = ",".join([keyword.word for keyword in article.keywords.all()])

        if article.is_accepted():
            author_list = article.frozen_authors()
            frozen = True
        else:
            author_list = article.authors.all()
            frozen = False

        if article.issue:
            issue = article.issue
        elif article.projected_issue:
            issue = article.projected_issue
        else:
            issue = None

        article_initial_details = [
            article.title,
            ','.join(['{}/{}'.format(article.pk, ex_file.file.original_filename) for ex_file in article.export_files]),
            article.abstract,
            article.section.name,
            keyword_string,
            article.license.short_name,
            article.get_language_display(),
        ]
        article_initial_details, author_list = add_first_author(
            article_initial_details,
            author_list,
            frozen,
            article,
        )
        additional_details = [
            article.pk,
            article.get_doi() if article.get_doi() else '',
            "https://doi.org/{}".format(article.get_doi()) if article.get_doi() else '',
            article.page_numbers,
            article.journal.code,
            article.journal.name,
            article.journal.issn,
            'Field not exportable',
            'Field not exportable',
            issue.volume if issue and issue.volume else '',
            issue.issue if issue and issue.issue else '',
            issue.issue_title if issue and issue.issue_title else '',
            issue.date if issue else '',
            article.stage,
        ]
        article_initial_details.extend(additional_details)
        author_rows = add_author_information(
            article_initial_details,
            author_list,
            frozen,
            article,
        )

        body_rows.append(article_initial_details)
        for row in author_rows:
            body_rows.append(row)

    csv_name = '{0}.csv'.format(uuid.uuid4())
    filepath = files.get_temp_file_path_from_name(
        csv_name,
    )
    with open(filepath, "w", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(header_row.split(","))
        for row in body_rows:
            wr.writerow(row)

    return filepath, csv_name


def zip_export_files(journal, articles, csv_path):
    zip_file_name = 'export_{}_csv.zip'.format(journal.code)
    zip_path = os.path.join(files.TEMP_DIR, zip_file_name)
    zip_file = zipfile.ZipFile(zip_path, mode='w')

    zip_file.write(
        csv_path,
        'article_data.csv'
    )
    for article in articles:
        for export_file in article.export_files:
            zip_file.write(
                export_file.file.self_article_path(),
                '{}/{}'.format(article.pk, export_file.file.original_filename),
            )

    zip_file.close()
    return files.serve_temp_file(zip_path, zip_file_name)
