from collections import OrderedDict
from itertools import chain

try:
    from django.db import models as django_models
except ImportError:
    django_models = False

from plugins.imports.csv import fields

class CSVTableMeta(type):
    def __new__(meta, name, bases, attrs):
        current_fields = []
        for name, attr in attrs.items():
            if isinstance(attr, fields.Field):
                current_fields.append((attr, name))
                attrs.pop(name)
        attrs["_fields"] = OrderedDict(current_fields)
        klass = super().__new__(meta, name, bases, attrs)
        return klass

class BaseCSVTable():
    __metaclass__ = CSVTableMeta
    def __init__(self, *args, **kwargs):
        if not data:
            data = {}
        for name, attr in self._fields.items():
            setattr(self, name, kwargs.get(name))

    def validate(self):
        errors = []
        for name, attr in self._fields.items():
            err = attr.validate(getattr(self, name))
            if err:
                errors.append(err)

        if errors:
            raise Exception("ERROR")  # TODO ValidationError


class Example(BaseCSVTable):
    some_field = fields.StringField(max_length=255)

class CSVTable(BaseCSVTable):
    def from_csv(cls, path, csv_parser=None):
        pass
        # TODO


if django_models:
    class CSVTableModelMeta(type):

        def __init__(cls, *args, **kwargs):
            super(*args, **kwargs).__init__(*args, **kwargs)
            for

        @staticmethod
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


    class CSVTableModel(BaseCSVTable):
        """ Generates a CSV Model from a django model

        Mimics the behaviour of how django FormModels are generated
        from an input model by mapping the form fields into their corresponding
        CSV Fields
        """
        __metaclass__ = CSVTableModelMeta

        FIELD_MAP = {
            django_models.CharField: fields.StringField,
            django_models.IntegerField: fields.IntegerField,
        }
        fields = ()
        exclude = ()

        def __init__(self, model_instance=None, *args, **kwargs):
            pass  # TODO

