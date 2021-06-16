import csv
import os
import re
import requests
from urllib.parse import urlparse, unquote
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.template.defaultfilters import linebreaksbr
from django.utils.dateparse import parse_datetime, parse_date

from core import models as core_models, files
from core import logic as core_logic
from identifiers import models as id_models
from journal import models as journal_models
from production.logic import handle_zipped_galley_images, save_galley
from submission import models as submission_models
from utils import setting_handler
from utils.logger import get_logger
from utils.logic import get_current_request

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
            sec_obj, created = submission_models.Section.objects.language(
                'en').get_or_create(journal=journal, name=section)
            article.section = sec_obj
            split_keywords = keywords.split("|")
            for kw in split_keywords:
                new_key = submission_models.Keyword.objects.create(word = kw)
                article.keywords.add(new_key)
            article.save()
            issue.articles.add(article)
            issue.save()
            id_models.Identifier.objects.create(
                id_type='doi', identifier=doi, article=article)

        # author import
        *author_fields, is_corporate = author_fields
        if is_corporate in "Yy":
            import_corporate_author(author_fields, article)
        else:
            import_author(author_fields, article)


        #files import
        for uri in (pdf, html, xml):
            if uri:
                import_galley_from_uri(article, uri, figures)

        return article


def import_author(author_fields, article):
        salutation, first_name, middle_name, last_name, institution, bio, email = author_fields
        if not email:
            email = "{}{}".format(uuid.uuid4(), settings.DUMMY_EMAIL_DOMAIN)
        author, created = core_models.Account.objects.get_or_create(email=email)
        if created:
            author.salutation = salutation
            author.first_name = first_name
            author.middle_name = middle_name
            author.last_name = last_name
            author.institution = institution
            author.biography = bio or None
            author.save()

        article.authors.add(author)
        article.save()
        author.snapshot_self(article)


def import_corporate_author(author_fields, article):
        *_, institution,_bio, _email = author_fields
        submission_models.FrozenAuthor.objects.get_or_create(
            article=article,
            is_corporate=True,
            institution=institution,
        )


def import_galley_from_uri(article, uri, figures_uri=None):
    parsed = urlparse(uri)
    print(parsed)
    django_file = None
    if parsed.scheme == "file":
        if parsed.netloc:
            raise ValueError("Netlocs are not supported %s" % parsed.netloc)
        path = unquote(parsed.path)
        blob = read_local_file(path)
        django_file = ContentFile(blob)
        django_file.name = os.path.basename(path)
    elif parsed.scheme == 'https':
        contents = read_remote_file(uri)
        django_file = ContentFile(contents)
        django_file.name = os.path.basename(uri)
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


def read_remote_file(url):
    request = requests.get(url)
    return request.content


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
