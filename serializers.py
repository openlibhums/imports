from rest_framework import serializers

from plugins.imports import models


class ExportFileSerializer(serializers.ModelSerializer):

    def validate(self, data):
        """
        Check that the start is before the stop.
        """
        if data['article'].journal != data['journal']:
            raise serializers.ValidationError({"article": "Article must be a part of the current journal"})

        return data

    class Meta:
        model = models.ExportFile
        fields = ('id', 'file', 'article', 'journal')

        file = serializers.ReadOnlyField(
            read_only=True,
            source='file.label',
        )
        article = serializers.ReadOnlyField(
            read_only=True,
            source='article.title',
        )
        journal = serializers.ReadOnlyField(
            read_only=True,
            source='journal.name',
        )

