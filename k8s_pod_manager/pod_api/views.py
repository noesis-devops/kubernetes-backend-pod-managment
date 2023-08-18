from django.shortcuts import render

# Create your views here.

from rest_framework.views import APIView
from rest_framework.response import Response
from kubernetes import client, config
from jinja2 import Template
from pathlib import Path
import yaml
config.load_kube_config()

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
    def substitute_tokens_in_yaml(self, yaml_path, variables):
        with open(yaml_path, 'r') as template_file:
            template_content = template_file.read()

        template = Template(template_content)
        rendered_yaml = template.render(**variables)
        return rendered_yaml
    def post(self, request):
        # Load Kubernetes configuration
        config.load_kube_config()


        # Parse request data
        namespace = request.data.get('namespace')
        port_range = request.data.get('port-range')

        # Create Kubernetes API client
        #v1 = client.CoreV1Api()

        # Define pod manifest
        #pod_manifest = {
        #    "apiVersion": "v1",
        #    "kind": "Pod",
        #    "metadata": {"name": pod_name},
        #    "spec": {
        #        "containers": [
        #            {
        #                "name": container_name,
        #                "image": image,
        #            }
        #        ]
        #    }
        #}
        
        start_port, end_port = map(int, port_range.split("-"))
        custom_variables = {
            'port': port_range,
            'selenium_hub_image': request.data.get('selenium-hub-image'),
            'selenium_node_chrome_image': request.data.get('selenium-node-chrome-image')
        }
        
        api_instance = client.AppsV1Api()
        service_api_instance = client.CoreV1Api()
        
        resp = {namespace: {"deployments": [], "services": []}}
        
        succeeds = False
        
        for port in range(start_port, end_port):
            custom_variables["port"] = port
            template_path = Path(__file__).with_name('selenium_hub_service_template.yaml')
            rendered_selenium_hub_service_template = self.substitute_tokens_in_yaml(template_path, custom_variables)
            print(rendered_selenium_hub_service_template)
            try:
                service_api_response = service_api_instance.create_namespaced_service(namespace=namespace, body=yaml.safe_load(rendered_selenium_hub_service_template))
                print(service_api_response)
                resp[namespace]["services"].append(service_api_response.metadata.name)
                succeeds = True
                break  # If service creation succeeds, exit the loop
            except client.exceptions.ApiException as e:
                succeeds = False
                if e.status == 409 and e.reason == "AlreadyExists":
                    print(f"Port {port} already allocated.")
                else:
                    print("An error occurred:", e)
                               

        template_path = Path(__file__).with_name('node_chrome_service_template.yaml')
        rendered_node_chrome_service_template = self.substitute_tokens_in_yaml(template_path, custom_variables)
        print(rendered_node_chrome_service_template)
        service_api_response = service_api_instance.create_namespaced_service(namespace=namespace, body=yaml.safe_load(rendered_node_chrome_service_template))
        print(service_api_response)
        resp[namespace]["services"].append(service_api_response.metadata.name)
        succeeds = True
        
        try:
            template_path = Path(__file__).with_name('selenium_hub_deployment_template.yaml')
            rendered_selenium_hub_deployment_template = self.substitute_tokens_in_yaml(template_path, custom_variables)
            print(rendered_selenium_hub_deployment_template)
            api_response = api_instance.create_namespaced_deployment(namespace, yaml.safe_load(rendered_selenium_hub_deployment_template))
            print("api_response rendered_selenium_hub_deployment_template")
            print(api_response)
            resp[namespace]["deployments"].append(service_api_response.metadata.name)
            succeeds = True
        except client.exceptions.ApiException as e:
            succeeds = False
            if e.status == 409 and e.reason == "AlreadyExists":
                print("Deployment already exists.")
            else:
                print("An error occurred:", e)
        
        try:
            template_path = Path(__file__).with_name('node_chrome_deployment_template.yaml')
            rendered_node_chrome_deployment_template = self.substitute_tokens_in_yaml(template_path, custom_variables)
            print(rendered_node_chrome_deployment_template)
            api_response = api_instance.create_namespaced_deployment(namespace, yaml.safe_load(rendered_node_chrome_deployment_template))
            print(api_response)
            resp[namespace]["deployments"].append(service_api_response.metadata.name)
            succeeds = True
        except client.exceptions.ApiException as e:
            succeeds = False
            if e.status == 409 and e.reason == "AlreadyExists":
                print("Deployment already exists.")
            else:
                print("An error occurred:", e)
                
        # delete everything if something fails    
        if succeeds == False:
            service_api_instance.delete_namespaced_service(service_name, namespace)
            print(f"Service '{service_name}' deleted successfully.")
            
        return Response({'objects_created': resp, "port": custom_variables["port"]})
        
    
        

class PodDeleteView(APIView):
    def delete(self, request):
        config.load_kube_config()

        # Create Kubernetes API client
        core_api = client.CoreV1Api()
        apps_api = client.AppsV1Api()
        # Delete deployments and services
        try:
            for namespace in request.data:
                for deployment in request.data[namespace]["deployments"]:
                    resp = apps_api.delete_namespaced_deployment(deployment_name, namespace)
                    print(resp)
                for service in request.data[namespace]["services"]:
                    resp = core_api.delete_namespaced_service(service_name, namespace)
                    print(resp)
            return Response({'Deleted': request.data})
        except client.rest.ApiException as e:
            return Response({'message': f'Error deleting: {str(e)}'}, status=400)