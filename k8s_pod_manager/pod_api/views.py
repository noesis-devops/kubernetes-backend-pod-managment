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

class PodCreateView(APIView):
    def post(self, request):
        # Load Kubernetes configuration
        config.load_kube_config()

        # Parse request data
        #namespace = request.data.get('namespace')
        #pod_name = request.data.get('pod_name')
        #container_name = request.data.get('container_name')
        #image = request.data.get('image')
        namespace = 'default'
        pod_name = 'sample-pod'
        container_name = 'container-name'
        image = 'nginx:latest'
        # Create Kubernetes API client
        v1 = client.CoreV1Api()

        # Define pod manifest
        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": pod_name},
            "spec": {
                "containers": [
                    {
                        "name": container_name,
                        "image": image,
                    }
                ]
            }
        }

        # Create the pod
        try:
            resp = v1.create_namespaced_pod(namespace, pod_manifest)
            return Response({'message': 'Pod created successfully', 'pod_name': resp.metadata.name})
        except Exception as e:
            return Response({'message': f'Error creating pod: {str(e)}'}, status=400)
