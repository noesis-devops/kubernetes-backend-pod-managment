from django.shortcuts import render

# Create your views here.

from rest_framework.views import APIView
from rest_framework.response import Response
from kubernetes import client, config
from jinja2 import Template
from pathlib import Path
import yaml
import time

config.load_incluster_config()

def wait_for_deployment_ready(apps_api, namespace, deployment_name, timeout_seconds=80):
    start_time = time.time()

    while True:
        deployment = apps_api.read_namespaced_deployment(deployment_name, namespace)
        print("deployment.status.ready_replicas")
        print(deployment.status.ready_replicas)
        print("deployment.spec.replicas")
        print(deployment.spec.replicas)
        if deployment.status.ready_replicas == deployment.spec.replicas:
            print(f"Deployment {deployment_name} is ready.")
            return True

        if time.time() - start_time > timeout_seconds:
            print(f"Timeout reached while waiting for deployment {deployment_name} to be ready.")
            return False

        time.sleep(5)  # Wait for 5 seconds before checking again

    return False  # In case of unexpected exit from the loop

class PodManagement:
    def get_pods_in_namespace(self, namespace):
        try:
            core_api = client.CoreV1Api()
            api_response = core_api.list_namespaced_pod(namespace)
            pod_list = [pod.metadata.name for pod in api_response.items]
            return pod_list
        except client.rest.ApiException as e:
            return None  # Return an appropriate error response or raise an exception

class PodListView(APIView):
    def get(self, request):
        core_api = client.CoreV1Api()
        namespaces = core_api.list_namespace().items

        pod_data = []

        # Iterate through namespaces and pods
        for namespace in namespaces:
            namespace_name = namespace.metadata.name
            pods = core_api.list_namespaced_pod(namespace_name).items

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
        config.load_incluster_config()

        # Parse request data
        namespace = request.data.get('namespace')
        port_range = request.data.get('port-range')
        
        start_port, end_port = map(int, port_range.split("-"))
        custom_variables = {
            'port': port_range,
            'selenium_hub_image': request.data.get('selenium-hub-image'),
            'selenium_node_chrome_image': request.data.get('selenium-node-chrome-image'),
            'se_node_session_timeout': request.data.get('se_node_session_timeout')
        }
        
        core_api = client.CoreV1Api()
        apps_api = client.AppsV1Api()
        
        resp = {namespace: {"deployments": [], "services": []}}
        
        succeeds = False
        
        for port in range(start_port, end_port):
            custom_variables["port"] = port
            template_path = Path(__file__).with_name('selenium_hub_service_template.yaml')
            rendered_selenium_hub_service_template = self.substitute_tokens_in_yaml(template_path, custom_variables)
            print(rendered_selenium_hub_service_template)
            try:
                service_api_response = core_api.create_namespaced_service(namespace=namespace, body=yaml.safe_load(rendered_selenium_hub_service_template))
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
        service_api_response = core_api.create_namespaced_service(namespace=namespace, body=yaml.safe_load(rendered_node_chrome_service_template))
        print(service_api_response)
        resp[namespace]["services"].append(service_api_response.metadata.name)
        succeeds = True
        
        try:
            template_path = Path(__file__).with_name('selenium_hub_deployment_template.yaml')
            rendered_selenium_hub_deployment_template = self.substitute_tokens_in_yaml(template_path, custom_variables)
            print(rendered_selenium_hub_deployment_template)
            api_response = apps_api.create_namespaced_deployment(namespace, yaml.safe_load(rendered_selenium_hub_deployment_template))
            resp[namespace]["deployments"].append(api_response.metadata.name)
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
            api_response = apps_api.create_namespaced_deployment(namespace, yaml.safe_load(rendered_node_chrome_deployment_template))
            print(api_response)
            resp[namespace]["deployments"].append(api_response.metadata.name)
            succeeds = True
        except client.exceptions.ApiException as e:
            succeeds = False
            if e.status == 409 and e.reason == "AlreadyExists":
                print("Deployment already exists.")
            else:
                print("An error occurred:", e)
                
        # delete everything if something fails    
        if succeeds == False:
            for deployment in resp[namespace]["deployments"]:
                    resp = apps_api.delete_namespaced_deployment(deployment, namespace)
                    print(f"'{deployment}' deleted successfully.")
            for service in resp[namespace]["services"]:
                resp = core_api.delete_namespaced_service(service, namespace)
                print(f"'{service}' deleted successfully.")
            return Response({'deleted': resp})
        
            selenium_hub_deployment_ready = wait_for_deployment_ready(apps_api, namespace, f'selenium-hub-{custom_variables["port"]}', timeout_seconds=120)
            node_chrome_deployment_ready = wait_for_deployment_ready(apps_api, namespace, f'chrome-{custom_variables["port"]}', timeout_seconds=120)
            
        if selenium_hub_deployment_ready and node_chrome_deployment_ready:
            return Response({'objects_created': resp, "port": custom_variables["port"]})
        else:
            return Response({'message': 'Deployments did not become ready within the timeout.'}, status=500)
        

class PodDeleteView(APIView):
    def delete(self, request):
        config.load_incluster_config()

        # Create Kubernetes API client
        core_api = client.CoreV1Api()
        apps_api = client.AppsV1Api()
        # Delete deployments and services
        try:
            for namespace in request.data:
                for deployment in request.data[namespace]["deployments"]:
                    resp = apps_api.delete_namespaced_deployment(deployment, namespace)
                    print(resp)
                for service in request.data[namespace]["services"]:
                    resp = core_api.delete_namespaced_service(service, namespace)
                    print(resp)
            return Response({'Deleted': request.data})
        except client.rest.ApiException as e:
            return Response({'message': f'Error deleting: {str(e)}'}, status=400)