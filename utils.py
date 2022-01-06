import cgi
import csv
import os
import re
import requests
from urllib.parse import urlparse, unquote
import uuid
from zipfile import ZipFile
from string import whitespace
from dateutil import parser as dateparser
import shutil
import glob

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.template.defaultfilters import linebreaksbr
from django.utils.dateparse import parse_datetime, parse_date
from django.utils.timezone import is_aware, make_aware

from core import models as core_models, files, logic as core_logic, workflow
from identifiers import models as id_models
from journal import models as journal_models
from production.logic import handle_zipped_galley_images, save_galley
from submission import models as submission_models
from utils import setting_handler
from utils.logger import get_logger
from utils.logic import get_current_request
from plugins.imports.templatetags import row_identifier
from plugins.imports.plugin_settings import UPDATE_CSV_HEADERS

logger = get_logger(__name__)


TMP_PREFIX = "janeway-imports"

CSV_HEADER_ROW = "Article identifier, Article title,Section Name, Volume number, Issue number, Subtitle, Abstract, " \
                 "publication stage, keywords, date/time accepted, date/time publishded , DOI, Author Salutation, " \
                 "Author first name,Author Middle Name, Author last name, Author Institution, Biography, Author Email, Is Corporate (Y/N), " \
                 "PDF URI,XML URI, HTML URI, Figures URI (zip)"

CSV_MAURO= "1,some title,Articles,1,1,some subtitle,the abstract,Published,'keyword1|keyword2|keyword3',2018-01-01T09:00:00," \
                  "2018-01-02T09:00:00,10.1000/xyz123,Mr,Mauro,Manuel,Sanchez Lopez,BirkbeckCTP,Mauro's bio,msanchez@journal.com,N," \
    "file:///path/to/file/file.pdf, file:///path/to/file/file.xml,file:///path/to/file/file.html,file:///path/to/images.zip"
CSV_MARTIN = "1,,,,,,,,,,,Prof,Martin,Paul,Eve,BirkbeckCTP,Martin's Bio, meve@journal.com,N,,,,"
CSV_ANDY = "1,some title,Articles,1,1,some subtitle,the abstract,Published,key1|key2|key3,2018-01-01T09:00:00,2018-01-02T09:00:00,10.1000/xyz123,Mr,Andy,James Robert,Byers,BirkbeckCTP,Andy's Bio,abyers@journal.com,N,,,,"


class DummyRequest():
    """ Used as to mimic request interface for `save_galley`"""
    def __init__(self, user):
        self.user = user



def import_editorial_team(request, reader):
    row_list = [row for row in reader]
    row_list.remove(row_list[0])

    for row in row_list:
        group, c = core_models.EditorialGroup.objects.get_or_create(
            name=row[8],
            journal=request.journal,
            defaults={'sequence': request.journal.next_group_order()})
        user, _ = import_user(request, row)

        core_models.EditorialGroupMember.objects.get_or_create(
            group=group,
            user=user,
            sequence=group.next_member_sequence()
        )


def import_reviewers(request, reader):
    row_list = [row for row in reader]
    row_list.remove(row_list[0])

    for row in row_list:
        user, _ = import_user(request, row, reset_pwd=True)
        if not user.is_reviewer(request):
            user.add_account_role('reviewer', request.journal)


def import_user(request, row, reset_pwd=False):
    try:
        country = core_models.Country.objects.get(code=row[7])
    except core_models.Country.DoesNotExist:
        country = None
    user, created = core_models.Account.objects.get_or_create(
        username=row[4],
        email=row[4],
        defaults={
            'salutation': row[0],
            'first_name': row[1],
            'middle_name': row[2],
            'last_name': row[3],
            'department': row[5],
            'institution': row[6],
            'country': country,
        }
    )
    if created and reset_pwd:
        core_logic.start_reset_process(request, user)

    return user, created


def import_contacts_team(request, reader):
    row_list = [row for row in reader]
    row_list.remove(row_list[0])

    for row in row_list:
        core_models.Contacts.objects.get_or_create(
            content_type=request.model_content_type,
            object_id = request.journal.id,
            name=row[0],
            email=row[1],
            role=row[2],
            sequence=request.journal.next_contact_order()
        )


def import_submission_settings(request, reader):
    row_list = [row for row in reader]
    row_list.remove(row_list[0])

    for row in row_list:
        journal = journal_models.Journal.objects.get(code=row[0])
        setting_handler.save_setting('general', 'copyright_notice', journal, linebreaksbr(row[1]))
        setting_handler.save_setting('general', 'submission_checklist', journal, linebreaksbr(row[2]))
        setting_handler.save_setting('general', 'publication_fees', journal, linebreaksbr(row[3]))
        setting_handler.save_setting('general', 'reviewer_guidelines', journal, linebreaksbr(row[4]))


def prepare_reader_rows(reader):
    article_groups = []

    for i, row in enumerate(reader):
        row_type = row_identifier.identify(row)

        clean_row = {}
        for k, v in row.items():
            clean_row[k] = v.strip(whitespace) if isinstance(v, str) else None

        if row_type in ['Update', 'New Article']:
            article_groups.append(
                {
                    'type': row_type,
                    'primary_row': clean_row,
                    'author_rows': [],
                    'primary_row_number': i,
                    'article_id': row.get(
                        'Article ID') if row_type == 'Update' else ''
                }
            )
        elif row_type == 'Author':
            last_article_group = article_groups[-1]
            last_article_group['author_rows'].append(clean_row)

    return article_groups


def prep_update(row):

    try:
        journal = journal_models.Journal.objects.get(code=row.get('Journal Code'))
        issue_type = journal_models.IssueType.objects.get(
            code="issue",
            journal=journal,
        )
        parsed_issue_date = get_aware_datetime(row.get('Issue pub date'))
        issue, created = journal_models.Issue.objects.get_or_create(
            journal=journal,
            volume=row.get('Volume number') or 0,
            issue=row.get('Issue number') or 0,
            defaults={
                'issue_title': row.get('Issue name'),
                'issue_type': issue_type,
                'date': parsed_issue_date,
            }
        )

        if not created:
            issue.date = parsed_issue_date
            issue.issue_title = row.get('Issue name')
            issue.save()

    except journal_models.Journal.DoesNotExist:
        journal, issue_type, issue = None, None, None

    article_id = row.get('Article ID')
    article = None
    if article_id:
        try:
            article = submission_models.Article.objects.get(pk=article_id)
        except submission_models.Article.DoesNotExist:
            pass

    return journal, article, issue_type, issue


def update_article_metadata(request, reader, folder_path):
    """
    Takes a dictreader and creates or updates article records.
    """
    errors = []
    actions = []

    prepared_reader_rows = prepare_reader_rows(reader)

    for prepared_row in prepared_reader_rows:
        journal, article, issue_type, issue = prep_update(prepared_row.get('primary_row'))

        if not journal:
            errors.append(
                {
                    'row': prepared_row.get('primary_row_number'),
                    'error': 'No journal found.',
                }
            )
            continue  # Loop should end here, we cannot import without a journal object.

        if article and article.journal != journal:
            errors.append(
                {
                    'row': prepared_row.get('primary_row_number'),
                    'error': 'article.journal ({}) and journal ({}) do not match.'.format(
                        article.journal,
                        journal
                    ),
                }
            )
            continue  # Loop breaks here if article.journal and journal aren't the same.

        if article:
            try:
                article = update_article(article, issue, prepared_row, folder_path)
                actions.append(
                    'Article {} updated.'.format(article.title)
                )
            except Exception as e:
                errors.append(
                    {
                        'article': prepared_row.get('primary_row').get('Article title'),
                        'error': e,
                    }
                )
        else:
            try:
                article = submission_models.Article.objects.create(
                    journal=journal,
                    title=prepared_row.get('primary_row').get('Article title'),
                    article_agreement='Imported article'
                )
                update_article(article, issue, prepared_row, folder_path)
                article.owner = request.user
                article.save()

                current_workflow_stages = set(journal.workflow_set.all().values_list(
                    "elements__stage", flat=True))
                current_workflow_stages.add('Published')

                proposed_stage = prepared_row.get('primary_row').get('Stage')
                if proposed_stage in current_workflow_stages:
                    article.stage = proposed_stage
                else:
                    article.stage = submission_models.STAGE_UNASSIGNED

                article.save()
                actions.append(
                    'Article {} created.'.format(article.title)
                )


            except Exception as e:
                errors.append(
                    {
                        'article': prepared_row.get('primary_row').get('Article title'),
                        'error': e,
                    }
                )

    return errors, actions


def update_article(article, issue, prepared_row, folder_path):
    row = prepared_row.get('primary_row')

    article.title = row.get('Article title')
    article.abstract = row.get('Article abstract')
    section_obj, created = submission_models.Section.objects.get_or_create(
        journal=article.journal,
        name=row.get('Article section'),
    )
    article.section = section_obj
    license_obj, created = submission_models.Licence.objects.get_or_create(
        short_name=row.get('License'),
        journal=article.journal,
        defaults={
            'name': row.get('License'),
        }
    )
    article.license = license_obj
    article.language = row.get('Language')

    keywords = []
    if row.get('Keywords'):
        keywords += row.get('Keywords').split(",")
    update_keywords(keywords, article)

    if row.get('Date accepted'):
        article.date_accepted = get_aware_datetime(
            row.get('Date accepted')
        )
    else:
        article.date_accepted = None

    if row.get('Date published'):
        article.date_published = get_aware_datetime(
            row.get('Date published')
        )
    else:
        article.date_published = None

    article.primary_issue = issue
    article.save()
    issue.articles.add(article)
    issue.save()

    if row.get('DOI'):
        id_models.Identifier.objects.get_or_create(
            id_type='doi',
            identifier=row.get('DOI'),
            article=article,
        )

    # import author from the primary row and then secondary rows
    updated_authors = []
    author_order = 0
    updated_authors.append(handle_author_import(row, article, author_order))

    for author_row in prepared_row.get('author_rows'):
        author_order += 1
        updated_authors.append(handle_author_import(author_row, article, author_order))

    # remove authors as needed in case of update
    for previous_author in article.authors.all():
        if previous_author not in updated_authors:
            article.authors.remove(previous_author)
            previous_frozen_author = previous_author.frozen_author(article)
            if previous_frozen_author:
                previous_frozen_author.delete()

    # Turning off file imports to prep for overhaul
    # handle_file_import(row, article, folder_path)

    if row.get('Stage') == 'typesetting_plugin':
        workflow_element = core_models.WorkflowElement.objects.get(
            journal=article.journal,
            stage=row.get('Stage'),
        )
        core_models.WorkflowLog.objects.get_or_create(
            article=article,
            element=workflow_element,
        )

    return article


def update_keywords(keywords, article):
    new_keywords = [w.strip(whitespace) for w in keywords if w]

    current_keywords = [str(kw) for kw in article.keywords.all()]
    if (len(current_keywords) > 0) and (current_keywords != new_keywords):
        article.keywords.clear()

    for kw in new_keywords:
        try:
            keyword, c = submission_models.Keyword.objects.get_or_create(
                word=kw
            )
        except submission_models.Keyword.MultipleObjectsReturned:
            keyword = submission_models.Keyword.objects.filter(
                word=kw
            ).first()

        article.keywords.add(keyword)

    article.save()


def handle_author_import(row, article, author_order):
    author_fields = [
        row.get('Author Salutation'),
        row.get('Author given name'),
        row.get('Author middle name'),
        row.get('Author surname'),
        row.get('Author institution'),
        row.get('Author department'),
        row.get('Author biography'),
        row.get('Author email'),
        row.get('Author ORCID'),
        row.get('Author is corporate (Y/N)'),
        author_order,
    ]

    if row.get('Author is corporate (Y/N)') == 'Y':
        import_corporate_author(author_fields, article)
    else:
        author = import_author(author_fields, article)
        author.save()
        if row.get('Author is primary (Y/N)') == 'Y':
            article.correspondence_author = author
            article.save()

        return author


def handle_file_import(row, article, folder_path):
    # Will no longer work as written--needs updating
    partial_file_paths = row.get('Article filename').split(',')
    for partial_file_path in partial_file_paths:
        full_path = os.path.join(folder_path, partial_file_path)

        try:
            file_name = partial_file_path.split('/')[1]
        except IndexError:
            file_name = partial_file_path

        if os.path.isfile(full_path):
            file = files.copy_local_file_to_article(
                file_to_handle=full_path,
                file_name=file_name,
                article=article,
                owner=article.correspondence_author if article.correspondence_author else None,
                label='Imported File',
                description='A file imported into Janeway',
            )
            file.privacy = 'typesetters'

            if file.mime_type in files.EDITABLE_FORMAT:
                article.manuscript_files.add(file)
            else:
                article.data_figure_files.add(file)


def verify_headers(reader):
    header_set = set(reader.fieldnames)
    expected_headers = set(UPDATE_CSV_HEADERS)

    return header_set == expected_headers


def import_article_metadata(request, reader):
    headers = next(reader)  # skip headers
    errors = {}
    uuid_filename = '{0}-{1}.csv'.format(TMP_PREFIX, uuid.uuid4())
    path = files.get_temp_file_path_from_name(uuid_filename)
    error_file = open(path, "w")
    error_writer = csv.writer(error_file)
    error_writer.writerow(headers)
    logger.info("Writing CSV import errors to %s", path)

    articles = {}
    issue_type = journal_models.IssueType.objects.get(
        code="issue",
        journal=request.journal,
    )
    # we skipped line 1 (headers) so we start at 2
    for i, line in enumerate(reader, start=2):
        line_id = line[0]
        article = articles.get(line_id)
        try:
            article = import_article_row(
                line, request.journal, issue_type, article)
        except Exception as e:
            errors[i] = e
            if settings.DEBUG:
                logger.exception(e)
            error_writer.writerow(line)
        articles[line_id] = article
    error_file.close()
    return articles, errors, uuid_filename


@transaction.atomic
def import_article_row(row, journal, issue_type, article=None):
        *a_row, pdf, xml, html, figures = row
        article_id, title, section, vol_num, issue_num, subtitle, abstract, \
            stage, keywords, date_accepted, date_published, doi, *author_fields = a_row
        issue, created = journal_models.Issue.objects.get_or_create(
            journal=journal,
            volume=vol_num or 0,
            issue=issue_num or 0,
        )
        if created:
            issue.issue_type = issue_type
            issue.save()

        if not article:
            if not title:
                # New article row found with no author
                raise ValueError("Row refers to an unknown article")
            article = submission_models.Article.objects.create(
                journal=journal,
                title=title,
            )
            article.subtitle = subtitle
            article.abstract = abstract
            article.date_accepted = (parse_datetime(date_accepted)
                    or parse_date(date_accepted))
            article.date_published = (parse_datetime(date_published)
                    or parse_date(date_published))
            article.stage = stage
            sec_obj, created = submission_models.Section.objects.get_or_create(journal=journal, name=section)
            article.section = sec_obj
            split_keywords = keywords.split("|")
            for kw in split_keywords:
                if kw.strip():
                    new_kw, _ = submission_models.Keyword.objects.get_or_create(
                        word=kw)
                    article.keywords.add(new_kw)
            article.save()
            issue.articles.add(article)
            issue.save()
            id_models.Identifier.objects.create(
                id_type='doi', identifier=doi, article=article)

        # author import
        *author_fields, is_corporate = author_fields
        if is_corporate and is_corporate in "Yy":
            import_corporate_author(author_fields, article)
        else:
            import_author(author_fields, article)


        #files import
        for uri in (pdf, html, xml):
            if uri:
                import_galley_from_uri(article, uri, figures)

        return article


def import_author(author_fields, article):
    salutation, first_name, middle_name, last_name, \
        institution, department, bio, email, orcid, \
        is_corporate, author_order = author_fields
    if not email:
        email = "{}{}".format(uuid.uuid4(), settings.DUMMY_EMAIL_DOMAIN)
        author_fields[-4] = email

    author, created = core_models.Account.objects.get_or_create(email=email)
    if created:
        author.salutation = salutation
        author.first_name = first_name
        author.middle_name = middle_name
        author.last_name = last_name
        author.institution = institution
        author.department = department
        author.biography = bio or None
        author.orcid = orcid_from_url(orcid)
        author.save()

    article.authors.add(author)
    article.save()
    author.snapshot_self(article)

    update_frozen_author(author, author_fields, article)

    return author

def update_frozen_author(author, author_fields, article):

    """
    Updates frozen author records from import data, not author object fields.
    """
    salutation, first_name, middle_name, last_name, \
        institution, department, biography, email, orcid, \
        is_corporate, author_order = author_fields
    frozen_author = author.frozen_author(article)
    frozen_author.first_name = first_name
    frozen_author.middle_name = middle_name
    frozen_author.last_name = last_name
    frozen_author.institution = institution
    frozen_author.department = department
    frozen_author.frozen_biography = biography
    frozen_author.frozen_orcid = orcid_from_url(orcid)
    frozen_author.order = author_order
    frozen_author.save()


def import_corporate_author(author_fields, article):
    *_, institution, _department, _bio, _email, _orcid, \
        _is_corporate, author_order = author_fields
    submission_models.FrozenAuthor.objects.get_or_create(
        article=article,
        is_corporate=True,
        institution=institution,
        order=author_order,
    )


def import_galley_from_uri(article, uri, figures_uri=None):
    parsed = urlparse(uri)
    django_file = None
    if parsed.scheme == "file":
        if parsed.netloc:
            raise ValueError("Netlocs are not supported %s" % parsed.netloc)
        path = unquote(parsed.path)
        blob = read_local_file(path)
        django_file = ContentFile(blob)
        django_file.name = os.path.basename(path)
    elif parsed.scheme in {"http", "https"}:
        response = requests.get(uri)
        response.raise_for_status()
        filename = get_filename_from_headers(response)
        if not filename:
            filename = uri.split("/")[-1]
        if not filename:
            filename = uuid.uuid4()
        django_file = ContentFile(response.content)
        django_file.name = filename
    else:
        raise NotImplementedError("Scheme not supported: %s" % parsed.scheme)


    if django_file:
        request = get_current_request()
        if request and request.user.is_authenticated():
            owner = request.user
        else:
            owner = core_models.Account.objects.filter(
                is_superuser=True).first()
            request = DummyRequest(user=owner)
        galley = save_galley(article, request, django_file, True)
        if figures_uri and galley.label in {"XML", "HTML"}:
            figures_path = unquote(urlparse(figures_uri).path)
            handle_zipped_galley_images(figures_path, galley, request)


def read_local_file(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()


def generate_review_forms(request):
    from review import models as review_models

    journal_pks = request.POST.getlist('journals')
    journals = [journal_models.Journal.objects.get(pk=pk) for pk in journal_pks]

    for journal in journals:

        default_review_form = review_models.ReviewForm.objects.create(
            journal=journal,
            name='Default Form',
            slug='default-form',
            intro='Please complete the form below.',
            thanks='Thank you for completing the review.'
        )

        main_element = review_models.ReviewFormElement.objects.create(
            name='Review',
            kind='textarea',
            required=True,
            order=1,
            width='large-12 columns',
            help_text='Please add as much detail as you can.'
        )

        default_review_form.elements.add(main_element)


def load_favicons(request):
    journal_pks = request.POST.getlist('journals')
    journals = [journal_models.Journal.objects.get(pk=pk) for pk in journal_pks]

    for journal in journals:
        journal.favicon = request.FILES.get('favicon')
        journal.save()


def load_article_images(request, reader):
    row_list = [row for row in reader]
    row_list.remove(row_list[0])

    for row in row_list:
        article = submission_models.Article.get_article(request.journal, row[0], row[1])

        image = requests.get(row[2], stream=True)
        if image.status_code == 200:

            content_disposition = image.headers['content-disposition']
            filename = re.findall("filename=\"(.+)\"", content_disposition)[0]

            name, extension = os.path.splitext(filename)
            uuid_filename = '{0}{1}'.format(uuid.uuid4(), extension)

            filepath = os.path.join(settings.BASE_DIR, 'files', 'articles', str(article.pk), uuid_filename)

            with open(filepath, 'wb') as f:
                for chunk in image:
                    f.write(chunk)

            new_file = core_models.File.objects.create(
                article_id=article.pk,
                mime_type=files.file_path_mime(filepath),
                original_filename=filename,
                uuid_filename=uuid_filename,
                label='Large Image File',
                privacy='public',
            )
            article.large_image_file = new_file
            article.save()


def orcid_from_url(orcid_url):
    try:
        return orcid_url.split("orcid.org/")[-1]
    except (AttributeError, ValueError, TypeError, IndexError):
        raise ValueError("%s is not a valid orcid URL" % orcid_url)


def prep_update_file(path):
    errors = []

    folder_name = str(uuid.uuid4())
    temp_folder_path = os.path.join(settings.BASE_DIR, 'files', 'temp', folder_name)
    os.mkdir(temp_folder_path)

    if path.endswith('.csv'):
        csv_filename = path.split('/')[-1]
        destination_csv_path = os.path.join(temp_folder_path, csv_filename)
        csv_path = shutil.copyfile(path, destination_csv_path)

    elif path.endswith('.zip'):

        with ZipFile(path, 'r') as zipObj:
            # Extract all the contents of zip file in different directory
            zipObj.extractall(temp_folder_path)

        destination_csv_wildcard = os.path.join(temp_folder_path, '*.csv')

        csv_path = sorted(
            glob.glob(destination_csv_wildcard)
        )[0] if glob.glob(destination_csv_wildcard) else None

    else:
        csv_path = None

    if not os.path.isfile(csv_path):
        errors.append('No metadata csv found.')

    return csv_path, temp_folder_path, errors


def get_proofing_assignments_for_journal(journal):
    try:
        proofing_workflow_element = core_models.WorkflowElement.objects.get(
            journal=journal,
            stage=submission_models.STAGE_PROOFING,
        )

        if journal.element_in_workflow(proofing_workflow_element.element_name):
            from proofing import models as proofing_models
            return 'proofing', proofing_models.ProofingTask.objects.filter(
                round__assignment__article__journal=journal,
            )
    except core_models.WorkflowElement.DoesNotExist:
        pass

    try:
        from plugins.typesetting import plugin_settings, models as typesetting_models
        typesetting_workflow_element = core_models.WorkflowElement.objects.get(
            journal=journal,
            stage=plugin_settings.STAGE,
        )
        if journal.element_in_workflow(typesetting_workflow_element.element_name):
            return 'typesetting', typesetting_models.GalleyProofing.objects.filter(
                round__article__journal=journal,
            )
    except ImportError:
        pass

    return None, []


def proofing_files(workflow_type, proofing_assignments, article):
    article_assignments = proofing_assignments.filter(round__article=article)
    if workflow_type == 'proofing':
        proofreader_file_queries = [proof.proofed_files.all() for proof in article_assignments]
    else:
        proofreader_file_queries = [proof.annotated_files.all() for proof in article_assignments]

    files = []
    for proofed_file_query in proofreader_file_queries:
        for file in proofed_file_query:
            files.append(file)

    return set(files)


def get_filename_from_headers(response):
    try:
        header = response.headers["Content-Disposition"]
        _, params = cgi.parse_header(header)
        return params["filename"]
    except Exception as e:
        logger.info(
            "No filename available in headers: %s" % response.headers
        )
    return None


def get_aware_datetime(unparsed_string, use_noon_if_no_time = True):

    if use_noon_if_no_time and re.fullmatch(
        '[0-9]{4}-[0-9]{2}-[0-9]{2}',
        unparsed_string
    ):
        unparsed_string += ' 12:00'

    try:
        parsed_datetime = dateparser.parse(unparsed_string)
    except ValueError:
        raise

    if is_aware(parsed_datetime):
        return parsed_datetime
    else:
        return make_aware(parsed_datetime)
