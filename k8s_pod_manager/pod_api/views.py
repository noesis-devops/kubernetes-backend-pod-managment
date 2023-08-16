from django.shortcuts import render

# Create your views here.

from rest_framework.views import APIView
from rest_framework.response import Response
from kubernetes import client, config

config.load_incluster_config()

class PodManagement:

    def get_pods_in_namespace(self, namespace):
        try:
            v1 = client.CoreV1Api()
            api_response = v1.list_namespaced_pod(namespace)
            pod_list = [pod.metadata.name for pod in api_response.items]
            return pod_list
        except client.rest.ApiException as e:
            return None  # Return an appropriate error response or raise an exception

class PodListView(APIView):
    def get(self, request):
        v1 = client.CoreV1Api()
        namespaces = v1.list_namespace().items

        pod_data = []

        # Iterate through namespaces and pods
        for namespace in namespaces:
            namespace_name = namespace.metadata.name
            pods = v1.list_namespaced_pod(namespace_name).items

            pod_list = [pod.metadata.name for pod in pods]
            pod_data.append({namespace_name: pod_list})

        return Response({"pod_data": pod_data})

class PodsInNamespaceView(APIView):
    def get(self, request, namespace):
        pod_manager = PodManagement()
        pods = pod_manager.get_pods_in_namespace(namespace)

        if pods is not None:
            return Response({'pods': pods})
        else:
            return Response({'message': f'Error fetching pods in namespace {namespace}'}, status=400)

class PodCreateView(APIView):
    def post(self, request):
        # Load Kubernetes configuration
        config.load_incluster_config()


        # Parse request data
        namespace = request.data.get('namespace')
        pod_name = request.data.get('pod_name')
        container_name = request.data.get('container_name')
        image = request.data.get('image')
        
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
            return Response({'message': 'Pod created successfully', 'pod_name': resp.metadata.name, 'namespace': resp.metadata.namespace})
        except Exception as e:
            return Response({'message': f'Error creating pod: {str(e)}'}, status=400)

class PodDeleteView(APIView):
    def delete(self, request, namespace, pod_name):
        config.load_incluster_config()

        # Create Kubernetes API client
        v1 = client.CoreV1Api()
        # Delete the pod
        try:
            v1.delete_namespaced_pod(pod_name, namespace)
            return Response({'message': 'Pod deleted successfully'})
        except client.rest.ApiException as e:
            return Response({'message': f'Error deleting pod: {str(e)}'}, status=400)