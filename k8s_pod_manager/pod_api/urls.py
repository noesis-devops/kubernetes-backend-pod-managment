from django.urls import path
from .views import PodListView, PodCreateView, PodDeleteView, PodsInNamespaceView

urlpatterns = [
    path('pods/', PodListView.as_view(), name='pod-list'),
    path('pods/<str:namespace>/', PodsInNamespaceView.as_view(), name='pods-in-namespace'),
    path('create/', PodCreateView.as_view(), name='create-pod'),
    path('delete/', PodDeleteView.as_view(), name='delete-pod'),

]