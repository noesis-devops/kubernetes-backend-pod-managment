from django.urls import path
from .views import PodListView, PodCreateView, PodDeleteView, PodsInNamespaceView, PodDeleteViewURL, proxy_view, update_load_balancer_ip, proxy_delete

urlpatterns = [
    path('pods/', PodListView.as_view(), name='pod-list'),
    path('pods/<str:namespace>/', PodsInNamespaceView.as_view(), name='pods-in-namespace'),
    path('create/', PodCreateView.as_view(), name='create-pod'),
    #path('delete/', PodDeleteView.as_view(), name='delete-pod'),
    path('delete/<str:namespace>/<str:port>/', PodDeleteViewURL.as_view(), name='delete-pod2'),
    path('proxy/<int:port>/wd/hub/session', proxy_view, name='proxy_view_no_subpath'),
    path('proxy/<int:port>/session/<path:subpath>', proxy_view, name='proxy_view'),
    
    path('update-load-balancer-ip/', update_load_balancer_ip, name='update-load-balancer-ip'),
    path('proxy/delete/<str:namespace>/<int:port>/', proxy_delete, name='proxy_delete'),

]