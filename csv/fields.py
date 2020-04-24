from itertools import chain

from plugins.imports.csv import validators


class Field():
    default_validators = []

    def __init__(self, verbose_name=None, required=False, choices=None,
                 help_text="", validators=()):
        self.verbose_name = verbose_name
        self.required = required
        self.choices = choices or []
        self.help_text = help_text
        self._load_validators(validators)

        self.value = None

    def _load_validators(self, validators=()):
        self._validators = list(chain(self.default_validators, validators))

    @property
    def validators(self):
        return self._validators

    def validate(self):
        err = None
        for validator in self.validators:
            err = validator(self, self.value)
            if err:
                break
        return err

    def clean(self):
        raise NotImplementedError()


class StringField(Field):
    default_validators = [
        validators.validate_string,
        validators.validate_max_length,
    ]

    def __init__(self, max_length=None, **kwargs):
        super().__init__(**kwargs)
        self.max_length = max_length


class IntegerField(Field):
    default_validators = [validators.validate_integer]


class EmailField(StringField):
    email_validators = []

    def _load_validators(self, *args, **kwargs):
        super()._load_validators()
        self._validators.append(validators.validate_email)


class DateTimeField(StringField):
    def _load_validators(self, *wargs, **kwargs):
        super()._load_validators()
        self._validators.append(validators.validate_datetime)

