from django.conf.urls import url

from plugins.imports import views

urlpatterns = [
    url(r'^$', views.index, name='imports_index'),
    url(r'^upload/$', views.import_load, name='imports_load'),
    url(r'^process/(?P<filename>[\w.-]{0,256})$', views.import_action, name='imports_action'),

    url(r'^review_forms/$', views.review_forms, name='imports_review_forms'),
]