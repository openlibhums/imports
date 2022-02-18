import zipfile
import os
import uuid
import csv
from itertools import count, filterfalse
from uuid import uuid4
from plugins.imports import plugin_settings

from bs4 import BeautifulSoup

from django.template.loader import render_to_string
from submission import models as submission_models

from core import files


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


def add_author_information(row, author, frozen, article):
    """
    Adds author information to article row dictionary.
    """

    row['Author salutation'] = author.author.salutation if frozen and author.author else author.salutation
    row['Author given name'] = author.first_name
    row['Author middle name'] = author.middle_name
    row['Author surname'] = author.last_name
    row['Author suffix'] = author.name_suffix
    row['Author email'] = author.author.email if frozen and author.author else author.email
    if frozen and author.author and author.author.orcid:
        row['Author ORCID'] = "https://orcid.org/" + author.author.orcid
    elif author.orcid:
        row['Author ORCID'] = "https://orcid.org/" + author.orcid
    else:
        row['Author ORCID'] = ''
    row['Author institution'] = author.institution
    row['Author department'] = author.department
    row['Author biography'] = author.biography
    if frozen:
        row['Author is primary (Y/N)'] = 'Y' if author.author and author.author == article.correspondence_author else 'N'
        row['Author is corporate (Y/N)'] = 'Y' if author.is_corporate else 'N'
    else:
        row['Author is primary (Y/N)'] = 'Y' if author == article.correspondence_author else 'N'
        row['Author is corporate (Y/N)'] = 'N'

    return row


def export_using_import_format(articles):
    """
    Exports data for an article using the schema specified for the 
    Import / Export / Update tool.
    """

    export_headers = plugin_settings.UPDATE_CSV_HEADERS

    body_rows = []

    for article in articles:
        row = {}

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

        row['Janeway ID'] = article.pk
        row['Article title'] = article.title
        row['Article abstract'] = article.abstract
        row['Keywords'] = ", ".join(
            [keyword.word for keyword in article.keywords.all()]
        )
        row['Rights'] = article.rights
        row['Licence'] = article.license.short_name
        row['Language'] = article.get_language_display()
        row['Peer reviewed (Y/N)'] = 'Y' if article.peer_reviewed else 'N'
        row['DOI'] = article.get_doi() if article.get_doi() else ''
        row['DOI (URL form)'] = "https://doi.org/{}".format(article.get_doi()) if article.get_doi() else ''
        row['Date accepted'] = article.date_accepted.isoformat() if article.date_accepted else ''
        row['Date published'] = article.date_published.isoformat() if article.date_published else ''
        row['First page'] = str(article.first_page) if article.first_page else ''
        row['Last page'] = str(article.last_page) if article.last_page else ''
        row['Page numbers (custom)'] = article.page_numbers if article.page_numbers else ''
        row['Competing interests'] = article.competing_interests if article.competing_interests else ''
        row['Article section'] = article.section.name
        row['Stage'] = article.stage
        row['File import identifier'] = article.pk
        row['Journal code'] = article.journal.code
        row['Journal title override'] = article.publication_title or ''
        row['ISSN override'] = article.ISSN_override
        row['Volume number'] = issue.volume if issue and issue.volume else ''
        row['Issue number'] = issue.issue if issue and issue.issue else ''
        row['Issue title'] = issue.issue_title if issue and issue.issue_title else ''
        row['Issue pub date'] = issue.date.isoformat() if issue else ''


        author_dict = {}
        for author in author_list:
            if frozen:
                order = author.order
            else:
                order_obj = submission_models.ArticleAuthorOrder.objects.get(
                    article=article,
                    author=author
                )
                if order_obj:
                    order = order_obj.order
                else:
                    order = next(filterfalse(
                        set(author_dict.keys()).__contains__,
                        count(1)
                    ))
            author_dict[order] = author

        for order in sorted(list(author_dict.keys())):
            author = author_dict[order]
            row = add_author_information(row, author, frozen, article)
            body_rows.append(row)
            row = {}

    csv_name = '{0}.csv'.format(uuid.uuid4())
    filepath = files.get_temp_file_path_from_name(
        csv_name,
    )
    with open(filepath, "w", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=export_headers)
        wr.writeheader()
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
