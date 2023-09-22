from django.shortcuts import render

# Create your views here.

from rest_framework.views import APIView
from rest_framework.response import Response
from kubernetes import client, config
from jinja2 import Template
from pathlib import Path
import yaml, time, re

config.load_incluster_config()

def wait_for_deployment_ready(apps_api, namespace, deployment_name, timeout_seconds=80):
    start_time = time.time()

    while True:
        deployment = apps_api.read_namespaced_deployment(deployment_name, namespace)
        if deployment.status.ready_replicas == deployment.spec.replicas:
            print(f"Deployment {deployment_name} is ready.")
            return True

        if time.time() - start_time > timeout_seconds:
            print(f"Timeout reached while waiting for deployment {deployment_name} to be ready.")
            return False

        time.sleep(3)  # Wait for 5 seconds before checking again

    return False  # In case of unexpected exit from the loop

# delete everything if something fails    
def delete_deployment_and_service(resp):
    for deployment in resp[namespace]["deployments"]:
            resp = apps_api.delete_namespaced_deployment(deployment, namespace)
            print(f"'{deployment}' deleted successfully.")
    for service in resp[namespace]["services"]:
        resp = core_api.delete_namespaced_service(service, namespace)
        print(f"'{service}' deleted successfully.")
    return Response({'deleted': resp})

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
    def set_custom_variables(self, request):
        # Parse request data
        namespace = request.data.get('namespace')
        if namespace is None:
            namespace = 'ntx'
        port_range = request.data.get('port-range')
        if port_range is None:
            return Response({'message': 'Missing port-range in request'}, status=400)
        port_range_parts = port_range.split("-")
        if len(port_range_parts) != 2:
            return Response({'message': 'Invalid port-range format'}, status=400)
        try:
            start_port, end_port = sorted(map(int, port_range_parts))
        except ValueError:
            return Response({'message': 'Invalid port-range values'}, status=400)
        if start_port >= end_port:
            return Response({'message': 'Invalid port-range values: start_port must be less than end_port'}, status=400)

        default_selenium_hub_image = 'selenium/hub:4.1.2'
        default_selenium_node_image = 'selenium/node-chrome:4.1.2'
        default_se_node_session_timeout = 300  # Default timeout in seconds
        default_selenium_node_video_image = 'video:latest'
        
        custom_variables = {
            'port': port_range,
            'selenium_hub_image': request.data.get('selenium-hub-image', default_selenium_hub_image),
            'selenium_node_image': request.data.get('selenium-node-image', default_selenium_node_image),
            'selenium_node_video_image': request.data.get('selenium-node-video-image', default_selenium_node_video_image),
            'se_node_session_timeout': request.data.get('se_node_session_timeout', default_se_node_session_timeout)
        }
        
        return namespace, start_port, end_port, custom_variables
    def post(self, request):
        # Load Kubernetes configuration
        config.load_incluster_config()
        namespace, start_port, end_port, custom_variables = self.set_custom_variables(request)
        core_api = client.CoreV1Api()
        apps_api = client.AppsV1Api()
        
        resp = {namespace: {"deployments": [], "services": []}}
        
        succeeds = False
        
        api_response = None
        
        for port in range(start_port, end_port):
            custom_variables["port"] = port
            template_path = Path(__file__).with_name('selenium_hub_service_template.yaml')
            rendered_selenium_hub_service_template = self.substitute_tokens_in_yaml(template_path, custom_variables)
            try:
                api_response = core_api.create_namespaced_service(namespace=namespace, body=yaml.safe_load(rendered_selenium_hub_service_template))
                resp[namespace]["services"].append(api_response.metadata.name)
                print(f"Service {api_response.metadata.name} created successfully.")
                succeeds = True
                break  # If service creation succeeds, exit the loop
            except client.exceptions.ApiException as e:
                succeeds = False
                if e.status == 422 and "port is already allocated" in e.body:
                    print({'message': e.body})
                else:
                    print(f"An error occurred creating service {api_response.metadata.name}:", e)
                               

        template_path = Path(__file__).with_name('node_service_template.yaml')
        rendered_node_service_template = self.substitute_tokens_in_yaml(template_path, custom_variables)
        try:
            api_response = core_api.create_namespaced_service(namespace=namespace, body=yaml.safe_load(rendered_node_service_template))
            resp[namespace]["services"].append(api_response.metadata.name)
            print(f"Service {api_response.metadata.name} created successfully.")
            succeeds = True
        except client.exceptions.ApiException as e:
                succeeds = False
                if e.status == 422 and "port is already allocated" in e.body:
                    print({'message': e.body})
                else:
                    print(f"An error occurred creating service {api_response.metadata.name}:", e)
        
        try:
            template_path = Path(__file__).with_name('selenium_hub_deployment_template.yaml')
            rendered_selenium_hub_deployment_template = self.substitute_tokens_in_yaml(template_path, custom_variables)
            api_response = apps_api.create_namespaced_deployment(namespace, yaml.safe_load(rendered_selenium_hub_deployment_template))
            resp[namespace]["deployments"].append(api_response.metadata.name)
            print(f"Deployment {api_response.metadata.name} created successfully.")
            succeeds = True
        except client.exceptions.ApiException as e:
            succeeds = False
            if e.status == 409 and e.reason == "AlreadyExists":
                print(f"message: {e.message}")
            else:
                print(f"An error occurred creating deployment {api_response.metadata.name}:", e)
        
        try:
            template_path = Path(__file__).with_name('node_deployment_template.yaml')
            rendered_node_deployment_template = self.substitute_tokens_in_yaml(template_path, custom_variables)
            api_response = apps_api.create_namespaced_deployment(namespace, yaml.safe_load(rendered_node_deployment_template))
            resp[namespace]["deployments"].append(api_response.metadata.name)
            print(f"Deployment {api_response.metadata.name} created successfully.")
            succeeds = True
        except client.exceptions.ApiException as e:
            succeeds = False
            if e.status == 409 and e.reason == "AlreadyExists":
                print(f"Deployment {api_response.metadata.name} already exists.")
            else:
                print(f"An error occurred creating deployment {api_response.metadata.name}:", e)
        
        if succeeds == False:
            delete_deployment_and_service(resp)
            return Response({'message': f'Deployments or services cannot be created: {resp}'}, status=500)
        
        for deployment in resp[namespace]["deployments"]:
            ready = wait_for_deployment_ready(apps_api, namespace, deployment, timeout_seconds=80)
            if ready:
                continue
            else:
                delete_deployment_and_service(resp)
                return Response({'message': f'Deployment {deployment} did not become ready within the timeout.'}, status=500)
            
        return Response({'objects_created': resp, "port": custom_variables["port"]})

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

class PodDeleteViewURL(APIView):
    def delete(self, request, namespace, port):
        config.load_incluster_config()

        # Create Kubernetes API client
        core_api = client.CoreV1Api()
        apps_api = client.AppsV1Api()
        
        pod_data = {"deployments": [], "services": []}
        
        # Define a regular expression pattern to match valid port values
        port_pattern = re.compile(r'^\d{1,5}$')
        
        # Validate the port input
        if not port_pattern.match(port):
            return Response({'message': 'Invalid port value'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Delete matching deployments
            deployments = apps_api.list_namespaced_deployment(namespace)
            for deployment in deployments.items:
                if f"-{port}" in deployment.metadata.name:
                    resp = apps_api.delete_namespaced_deployment(deployment.metadata.name, namespace)
                    pod_data["deployments"].append(deployment.metadata.name)
                    print(resp)

            # Delete matching services
            services = core_api.list_namespaced_service(namespace)
            for service in services.items:
                if f"-{port}" in service.metadata.name:
                    resp = core_api.delete_namespaced_service(service.metadata.name, namespace)
                    pod_data["services"].append(service.metadata.name)
                    print(resp)

            return Response({'Deleted': pod_data})
        except client.rest.ApiException as e:
            return Response({'message': f'Error deleting: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)