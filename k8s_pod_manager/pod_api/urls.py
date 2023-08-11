from django.urls import path
from .views import PodListView, PodCreateView

urlpatterns = [
    path('pods/', PodListView.as_view(), name='pod-list'),
    path('create-pod/', PodCreateView.as_view(), name='create-pod'),
    path('delete-pod/<str:namespace>/<str:pod_name>/', PodDeleteView.as_view(), name='delete-pod'),
]