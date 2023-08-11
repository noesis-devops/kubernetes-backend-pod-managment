from django.urls import path
from .views import PodListView

urlpatterns = [
    path('pods/', PodUtils.as_view(), name='pod-list'),
    path('create-pod/', PodCreateView.as_view(), name='create-pod'),
]