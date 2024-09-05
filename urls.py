from django.urls import include, re_path

from rest_framework import routers

from plugins.imports import views

router = routers.DefaultRouter()
router.register(r'exportfiles', views.ExportFilesViewSet, basename='exportfile')

urlpatterns = [
    re_path(r'^$', views.index, name='imports_index'),
    re_path(r'^upload/$', views.import_load, name='imports_load'),
    re_path(r'^process/(?P<filename>[\w.-]{0,256})$', views.import_action, name='imports_action'),

    re_path(r'^review_forms/$', views.review_forms, name='imports_review_forms'),
    re_path(r'^favicon/$', views.favicon, name='imports_favicon'),
    re_path(r'^images/$', views.article_images, name='imports_article_images'),
    re_path(r'^jats/$', views.import_from_jats, name='imports_jats'),
    re_path(r'^wordpress/$',
        views.wordpress_xmlrpc_import,
        name='wordpress_xmlrpc_import'),
    re_path(r'^wordpress/(?P<import_id>\d+)/$',
        views.wordpress_posts,
        name='wordpress_posts'),

    re_path(r'^example_csv/$', views.csv_example, name='imports_csv_example'),
    re_path(r'^failed_rows/(?P<tmp_file_name>[.0-9a-z-]+)$', views.serve_failed_rows, name='imports_failed_rows'),

    re_path(r'^article/(?P<article_id>\d+)/export/$',
        views.export_articles_all,
        name='import_export_article',
        ),
    re_path(r'^articles/all/$', views.export_articles_all, name='import_export_articles_all'),

    re_path(r'^api/', include(router.urls)),
]
