# Generated by Django 3.2.20 on 2024-03-11 12:04

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('imports', '0009_automatedimportnotification'),
    ]

    operations = [
        migrations.CreateModel(
            name='SectionMap',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('article_type', models.CharField(blank=True, max_length=100)),
                ('section', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='submission.section')),
            ],
        ),
        migrations.CreateModel(
            name='CitationFormat',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('format', models.CharField(blank=True, max_length=255)),
                ('journal', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='journal.journal')),
            ],
        ),
    ]
