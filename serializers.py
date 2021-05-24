from rest_framework import serializers

from plugins.imports import models


class ExportFileSerializer(serializers.ModelSerializer):

    class Meta:
        model = models.ExportFile
        fields = ('file', 'article',)

        file = serializers.ReadOnlyField(
            read_only=True,
            source='file.label',
        )
        article = serializers.ReadOnlyField(
            read_only=True,
            source='article.title',
        )

