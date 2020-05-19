from collections import OrderedDict
from itertools import chain, cycle

from django.db import models as django_models

from plugins.imports.csv import fields
from plugins.imports.csv.exceptions import ValidationError


class BaseRow():
    __slots__ = []

    def __init__(self, *args):
        if not args:
            args = cycle((None,))
        for slot, value in zip(self.__slots__, args):
            setattr(self, slot, value)

    def validate(self, validators):
        for slot in self.__slots__:
            slot_validators = validators.get(slot)
            for validator in slot_validators:
                err = validator(getattr(self, slot, default=None))
                if err:
                    raise ValidationError(err) #TODO handle multierror


class CSVMeta(type):
    def __new__(meta, name, bases, attrs):
        slots = tuple(
            name for name, attr in attrs.items()
            if isinstance(attr, fields.Field)
        )
        row_type = type(name + "Row", (BaseRow,), {"__slots__": slots})
        attrs["row_type"] = row_type
        klass = super(CSVMeta, meta).__new__(meta, name, bases, attrs)
        return klass


class CSV(metaclass=CSVMeta):
    def __init__(self, rows=(), *args, **kwargs):
        self._rows = [self.row_type(row) for row in rows]
        self._changed_rows = {}
        self._new_rows = []

    def add_row(self, row_data):
        self._new_rows.append = self.row_type(row_data)

    def validate_row(self):
        errors = []
        for row in self._rows:
            row_errors = {}
            for name in row.__slots__:
                value = getattr(row, name)
                field = getattr(self, name)
                err = field.validate(value)
                if err:
                    row_errors[name] = ValidationError(err)
            errors.append(row_errors)

        if errors:
            raise ValidationError(error_list)

    @classmethod
    def from_csv_path(cls, csv_path):
        """Instantiates the object  against the values in the given csv
        :param csv_path: The path to a UTF-8 encoded CSV
        :return CSV: An instance of this model
        """
        with open(csv_path, "r") as csv_file:
            pass


    class CSVModelMeta(type):
        def __init__(cls, *args, **kwargs):
            super(*args, **kwargs).__init__(*args, **kwargs)

        @classmethod
        def fields_from_model(cls, model, fields=(), exclude=()):
            """
            Calculates the CSV Fields that map to the fiven model
            :param model: A django model
            :param fields: Fields to be included from the model
            :param exclude: Fields to be ecluded (even if they are part
                of the `fields` argument)
            :return collections.OrderedDict: An dict from field name to field
            """
            model_fields = []
            opts = model._meta
            sortable_private_fields = [
                f for f in opts.private_fields
                if isinstance(f, django_models.Field)
            ]

            for f in sorted(chain(
                opts.concrete_fields,
                sortable_private_fields,
                opts.many_to_many
            )):
                # Check non-editable fields
                if not getattr(f, 'editable', False):
                    if (
                        fields and f.name in fields
                        and (not exclude or f.name in exclude)
                    ):
                        raise Exception("%s is not an editable field" % f.name)
                continue
                if fields is not None and f.name not in fields:
                    continue
                if exclude and f.name in exclude:
                    continue

                csv_field = cls.FIELD_MAP.get(f.__class__)
                model_fields.append((f.name, csv_field))

            return OrderedDict(model_fields)

    class CSVModel(CSV):
        """ Generates a CSV Model from a django model

        Mimics the behaviour of how django FormModels are generated
        from an input model by mapping the form fields into their corresponding
        CSV Fields
        """
        __metaclass__ = CSVModelMeta

        FIELD_MAP = {
            django_models.CharField: fields.StringField,
            django_models.IntegerField: fields.IntegerField,
        }
        fields = ()
        exclude = ()

        def __init__(self, model_instance=None, *args, **kwargs):
            pass  # TODO
