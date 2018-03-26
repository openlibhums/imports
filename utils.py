from core import models as core_models


def import_editorial_team(request, reader):
    row_list = [row for row in reader]
    row_list.remove(row_list[0])

    for row in row_list:
        group, c = core_models.EditorialGroup.objects.get_or_create(
            name=row[7],
            journal=request.journal,
            defaults={'sequence': request.journal.next_group_order()})
        country = core_models.Country.objects.get(code=row[6])
        user, c = core_models.Account.objects.get_or_create(
            username=row[3],
            email=row[3],
            defaults={
                'first_name': row[0],
                'middle_name': row[1],
                'last_name': row[2],
                'department': row[4],
                'institution': row[5],
                'country': country,
            }
        )

        core_models.EditorialGroupMember.objects.get_or_create(
            group=group,
            user=user,
            sequence=group.next_member_sequence()
        )
