from django.urls import path
from .views import PodListView

urlpatterns = [
    path('pods/', PodListView.as_view(), name='pod-list'),
]