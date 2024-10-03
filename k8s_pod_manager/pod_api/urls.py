from django.urls import path
from .views import proxy_view, proxy_delete, update_load_balancer_ip, health_check

urlpatterns = [
   
    path('proxy/<int:port>/wd/hub/session', proxy_view, name='proxy_view_no_subpath'),
    path('proxy/<int:port>/wd/hub/session/<path:subpath>', proxy_view, name='proxy_view'),

    path('proxy/delete/<str:namespace>/<int:port>/', proxy_delete, name='proxy_delete'),

    path('health-check/', health_check, name='health_check'),
]
