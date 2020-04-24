from django.test import TestCase

from plugins.imports.csv import fields


class TestCSVModel():
    pass


class TestCSVFields(TestCase):

    def test_valid_string_field(self):
        field = fields.StringField(max_length=255)
        field.value = "This is my string"
        self.assertEqual(field.validate(), None,
                         msg="%s not a valid StringField value" % field.value)

    def test_invalid_string(self):
        field = fields.StringField(max_length=255)
        field.value = object()
        self.assertNotEqual(field.validate(), None,
                            msg="%s should not validate as a StringField value"
                            "" % field.value)

    def test_invalid_string_too_long(self):
        field = fields.StringField(max_length=1)
        field.value = "12"
        self.assertNotEqual(field.validate(), None,
                            msg="%s should not validate as a StringField value"
                            "" % field.value)

    def test_valid_integer_field(self):
        field = fields.IntegerField()
        field.value = 1
        self.assertEqual(field.validate(), None,
                         msg="%s not a valid IntegerField value" % field.value)

    def test_invalid_integer(self):
        field = fields.IntegerField()
        field.value = object()
        self.assertNotEqual(field.validate(), None,
                            msg="%s should not validate as a StringField value"
                            "" % field.value)

    def test_valid_email(self):
        field = fields.EmailField()
        field.value = "email@dummy.org"
        self.assertEqual(field.validate(), None,
                         msg="%s not a valid EmailField value" % field.value)

    def test_invalid_email(self):
        field = fields.IntegerField()
        field.value = "invalidemail"
        self.assertNotEqual(field.validate(), None,
                            msg="%s should not validate as an EmailField value"
                            "" % field.value)
