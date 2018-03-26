from django.conf.urls import url

from plugins.imports import views

urlpatterns = [
    url(r'^$', views.index, name='imports_index'),
    url(r'^editorial/$', views.editorial_load, name='imports_editorial_load'),
    url(r'^editorial/(?P<filename>[\w.-]{0,256})$', views.editorial_import, name='imports_editorial_import'),
]