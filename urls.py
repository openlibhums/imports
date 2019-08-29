from django.conf.urls import url

from plugins.imports import views

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
]
