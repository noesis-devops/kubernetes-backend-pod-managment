from django.urls import path
from .views import proxy_view

urlpatterns = [
   
    path('proxy/wd/hub/session', proxy_view, name='proxy_view_no_subpath'),
    path('proxy/wd/hub/session/<path:subpath>', proxy_view, name='proxy_view'),

]
