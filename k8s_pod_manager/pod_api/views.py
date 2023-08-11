from django.shortcuts import render

# Create your views here.

from rest_framework.views import APIView
from rest_framework.response import Response
from kubernetes import client, config

config.load_kube_config()

class PodListView(APIView):
    def get(self, request):
        v1 = client.CoreV1Api()
        pods = v1.list_pod_for_all_namespaces().items
        pod_list = [pod.metadata.name for pod in pods]
        return Response({'pods': pod_list})

