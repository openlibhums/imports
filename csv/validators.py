import re


def validate_required(field, value):
    if field.is_required and value is None:
        return "error"


def validate_string(field, value):
    print("a2")
    if not isinstance(value, str):
        return "error"


def validate_max_length(field, value):
    if field.max_length:
        if len(value) > field.max_length:
            return "error"


def validate_integer(field, value):
    if not isinstance(value, int):
        return "error"


class EmailValidator():
    user_regex = re.compile(
        r"(^[-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*\Z"  # dot-atom
        r'|^"([\001-\010\013\014\016-\037!#-\[\]-\177]'
        r'|\\[\001-\011\013\014\016-\177])*"\Z)',  # quoted-string
        re.IGNORECASE,
    )
    domain_regex = re.compile(
        # max length for domain name labels is 63 characters per RFC 1034
        r'((?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+)'
        r'(?:[A-Z0-9-]{2,63}(?<!-))\Z',
        re.IGNORECASE,
    )

    def validate_domain(self, domain):
            return True

    def __call__(self, field,  value):
        if '@' not in value:
            return "error"

        user_part, domain = value.rsplit('@', 1)
        if not self.user_regex.match(user_part):
            return "error"

        if not self.domain_regex.match(domain):
            return "error"


validate_email = EmailValidator()


def validate_datetime(field, value):
    pass # TODO
