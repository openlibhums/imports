from django.conf.urls import url, include

from rest_framework import routers

from plugins.imports import views

router = routers.DefaultRouter()
router.register(r'exportfiles', views.ExportFilesViewSet, base_name='exportfile')

urlpatterns = [
    url(r'^$', views.index, name='imports_index'),
    url(r'^upload/$', views.import_load, name='imports_load'),
    url(r'^process/(?P<filename>[\w.-]{0,256})$', views.import_action, name='imports_action'),

    url(r'^review_forms/$', views.review_forms, name='imports_review_forms'),
    url(r'^favicon/$', views.favicon, name='imports_favicon'),
    url(r'^images/$', views.article_images, name='imports_article_images'),
    url(r'^wordpress/$',
        views.wordpress_xmlrpc_import,
        name='wordpress_xmlrpc_import'),
    url(r'^wordpress/(?P<import_id>\d+)/$',
        views.wordpress_posts,
        name='wordpress_posts'),

    url(r'^example_csv/$', views.csv_example, name='imports_csv_example'),
    url(r'^failed_rows/(?P<tmp_file_name>[.0-9a-z-]+)$', views.serve_failed_rows, name='imports_failed_rows'),

    url(r'^articles/(?P<article_id>\d+)/format/(?P<format>csv|html)/$',
        views.export_article,
        name='import_export_article',
        ),
    url(r'^articles/all/$', views.export_articles_all, name='import_export_articles_all'),

    url(r'^api/', include(router.urls)),
]
