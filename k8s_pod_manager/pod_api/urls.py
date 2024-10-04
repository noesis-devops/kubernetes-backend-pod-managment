from django.urls import path
from .views import proxy_view, proxy_delete, health_check

urlpatterns = [
   
    path('proxy/wd/hub/session', proxy_view, name='proxy_view_no_subpath'),
    path('proxy/wd/hub/session/<path:subpath>', proxy_view, name='proxy_view'),

    path('proxy/delete/<str:namespace>/<int:port>/', proxy_delete, name='proxy_delete'),

    path('health-check/', health_check, name='health_check'),
]
