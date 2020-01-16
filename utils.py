import os
import re
import requests
import uuid

from django.conf import settings
from django.db import transaction
from django.utils.dateparse import parse_datetime, parse_date
from django.template.defaultfilters import linebreaksbr

from core import models as core_models, files
from core import logic as core_logic
from journal import models as journal_models
from utils import setting_handler
from submission import models as submission_models


CSV_HEADER_ROW = "Article identifier, Article title,Section Name, Volume number, Issue number, Subtitle, Abstract, " \
                 "publication stage, date/time accepted, date/time publishded , DOI, Author Salutation, " \
                 "Author first name,Author Middle Name, Author last name, Author Institution, Author Email, Is Corporate (Y/N)"

CSV_MAURO= "1,some title,Articles,1,1,some subtitle,the abstract,Published,2018-01-01T09:00:00," \
                  "2018-01-02T09:00:00,10.1000/xyz123,Mr,Mauro,Manuel,Sanchez Lopez,BirkbeckCTP,msanchez@journal.com,N"
CSV_MARTIN = "1,,,,,,,,,,Prof,Martin,Paul,Eve,BirkbeckCTP,meve@journal.com,N"
CSV_ANDY = "1,some title,1,1,some subtitle,the abstract,Published,2018-01-01T09:00:00,2018-01-02T09:00:00,10.1000/xyz123,Mr,Andy,James Robert,Byers,BirkbeckCTP,abyers@journal.com,N"

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
    if not created and reset_pwd:
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


@transaction.atomic
def import_article_metadata(request, reader):
    next(reader)  # skip headers
    articles = {}
    issue_type = journal_models.IssueType.objects.get(
        code="issue",
        journal=request.journal,
    )
    for line in reader:
        article_id, title, section, vol_num, issue_num, subtitle, abstract, \
            stage, date_accepted, date_published, doi, *author_fields = line

        if title:
            issue, created = journal_models.Issue.objects.get_or_create(
                journal=request.journal,
                volume=vol_num or 0,
                issue=issue_num or 0,
            )
            if created:
                issue.issue_type = issue_type
                issue.save()
            article, created = submission_models.Article.objects.get_or_create(
                journal=request.journal,
                title=title,
            )
            if created:
                article.subtitle = subtitle
                article.abstract = abstract
                article.date_accepted = (parse_datetime(date_accepted)
                        or parse_date(date_accepted))
                article.date_published = (parse_datetime(date_published)
                        or parse_date(date_published))
                article.stage = stage
                article.doi = doi
                sec_obj, created = submission_models.Section.objects.language(
                    'en').get_or_create(journal=request.journal, name=section)
                article.section = sec_obj
                article.save()
                issue.articles.add(article)
                issue.save()
            articles[article_id] = article

        # author import
        *author_fields, is_corporate = author_fields
        article = articles[article_id]
        if is_corporate in "Yy":
            import_corporate_author(author_fields, article)
        else:
            import_author(author_fields, article)

def import_author(author_fields, article):
        salutation, first_name, middle_name, last_name, institution, email = author_fields
        if not email:
            email = "{}{}".format(uuid.uuid4(), settings.DUMMY_EMAIL_DOMAIN)
        author, created = core_models.Account.objects.get_or_create(email=email)
        if created:
            author.salutation = salutation
            author.first_name = first_name
            author.middle_name = middle_name
            author.last_name = last_name
            author.institution = institution
            author.save()

        article.authors.add(author)
        article.save()
        author.snapshot_self(article)


def import_corporate_author(author_fields, article):
        *_, institution, _email = author_fields
        submission_models.FrozenAuthor.objects.get_or_create(
            article=article,
            is_corporate=True,
            institution=institution,
        )


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
