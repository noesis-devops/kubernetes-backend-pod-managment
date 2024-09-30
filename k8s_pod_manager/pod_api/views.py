from django.shortcuts import render

# Create your views here.

from rest_framework.views import APIView
from rest_framework.response import Response
from kubernetes import client, config
from kubernetes.stream import stream
from jinja2 import Template
from pathlib import Path
import yaml, time, re, os, subprocess, tarfile, base64, requests, logging
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from tempfile import TemporaryFile
from kubernetes.client.rest import ApiException
from os import path
from django.core.cache import cache

logger = logging.getLogger(__name__)

def load_kubernetes_config():
    try:
        config.load_incluster_config()
        print("Running inside the cluster, using in-cluster configuration")
    except:
        config.load_kube_config()
        print("Running outside the cluster, using kubeconfig")

def update_load_balancer_ip(request):
    if request.method == "POST":
        data = request.POST
        new_ip = data.get('ip')
        if new_ip:
            cache.set('load_balancer_ip', new_ip)
            return JsonResponse({'message': 'IP updated successfully', 'new_ip': new_ip})
        else:
            return JsonResponse({'error': 'No IP provided'}, status=400)
        

def wait_for_deployment_ready(apps_api, namespace, deployment_name, timeout_seconds=60):
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
def delete_objects(apps_api, core_api, resp, namespace):
    for deployment in resp[namespace]["deployments"]:
        apps_api.delete_namespaced_deployment(deployment, namespace)
        print(f"'{deployment}' deleted successfully.")
    for service in resp[namespace]["services"]:
        core_api.delete_namespaced_service(service, namespace)
        print(f"'{service}' deleted successfully.")
    for config_map in resp[namespace]["config_maps"]:
        core_api.delete_namespaced_config_map(config_map, namespace)
        print(f"'{config_map}' deleted successfully.")
    return Response({'deleted': resp})

def get_pods_by_app_label(match_label, namespace):
    try:
        api_instance = client.CoreV1Api()
        # List pods in the specified namespace
        pod_list = api_instance.list_namespaced_pod(namespace=namespace)
        # Filter pods by the "app" label (assuming your deployment uses this label)
        filtered_pods = [pod for pod in pod_list.items if pod.metadata.labels.get("app") == match_label]
        if filtered_pods:
            for pod in filtered_pods:
                print(f"Pod Name: {pod.metadata.name}")
        else:
            print(f"No pods found for deployment: {match_label}")
    except Exception as e:
        print(f"Error: {e}")
    return filtered_pods

@csrf_exempt
def proxy_view(request, port, subpath=''):
    namespace = 'testingon'
    service_name = f'selenium-hub-{port}-service'
    
    base_url = f'http://{service_name}.{namespace}.svc.cluster.local:{port}/wd/hub/session'
    logger.info(f"Base URL: {base_url}")
    
    if subpath.startswith('/'):
        subpath = subpath[1:]
        
    selenium_grid_url = f'{base_url}/{subpath}' if subpath else base_url

    try:
        excluded_headers = ['host', 'content-length', 'transfer-encoding', 'connection']
        headers = {key: value for key, value in request.headers.items() if key.lower() not in excluded_headers}
        data = request.body if request.method in ['POST', 'PUT', 'PATCH'] else None

        logger.info(f"Proxying {request.method} request to {selenium_grid_url}")
        logger.debug(f"Request headers: {headers}")
        logger.debug(f"Request params: {request.GET}")
        if data:
            logger.debug(f"Request body: {data.decode('utf-8')}")

        response = requests.request(
            method=request.method,
            url=selenium_grid_url,
            headers=headers,
            data=data,
            params=request.GET
        )

        logger.info(f"Received response with status code {response.status_code} from {selenium_grid_url}")
        logger.debug(f"Response headers: {response.headers}")
        logger.debug(f"Response body: {response.text}")

        return HttpResponse(
            content=response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type')
        )

    except requests.RequestException as e:
        logger.exception(f"ClientError while proxying request to {selenium_grid_url}: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
def proxy_delete(request, namespace, port):
    v1 = client.CoreV1Api()
    service_name = f'ntx-api-kubernetes-ntx-pod-management-service' 
    namespace = 'testingon'
    service = v1.read_namespaced_service(name=service_name, namespace=namespace)
    logger.info(f"Fetched service '{service_name}' in namespace '{namespace}'.")

    if not service.spec.ports:
        logger.error(f"No ports found for service '{service_name}'.")
        return JsonResponse({'error': 'Service has no ports configured.'}, status=500)
    
    service_port = service.spec.ports[0].port
    logger.info(f"Retrieved port {service_port} for service '{service_name}'.")

    base_url = f'http://{service_name}.{namespace}.svc.cluster.local:{service_port}/api/delete/{namespace}/{port}/'
    
    try:
        excluded_headers = ['host', 'content-length', 'transfer-encoding', 'connection']
        headers = {key: value for key, value in request.headers.items() if key.lower() not in excluded_headers}
        
        data = request.body if request.method in ['POST', 'PUT', 'PATCH', 'DELETE'] else None

        logger.info(f"Proxying {request.method} request to {base_url}")
        logger.debug(f"Request headers: {headers}")
        logger.debug(f"Request params: {request.GET}")
        if data:
            try:
                logger.debug(f"Request body: {data.decode('utf-8')}")
            except UnicodeDecodeError:
                logger.debug("Request body contains non-UTF-8 bytes.")


        response = requests.delete(
            url=base_url,
            headers=headers,
            params=request.GET,
            data=data,
            timeout=30
        )

        logger.info(f"Received response with status code {response.status_code} from {base_url}")
        logger.debug(f"Response headers: {response.headers}")
        logger.debug(f"Response body: {response.text}")

        return HttpResponse(
            content=response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type', 'application/json')
        )

    except requests.Timeout:
        logger.error(f"Request to {base_url} timed out.")
        return JsonResponse({'error': 'Request timed out.'}, status=504)

    except requests.ConnectionError as e:
        logger.exception(f"Connection error while proxying DELETE to {base_url}: {str(e)}")
        return JsonResponse({'error': 'Connection error.'}, status=502)

    except requests.RequestException as e:
        logger.exception(f"RequestException while proxying DELETE to {base_url}: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def exec_cmd(api_instance, name, container_name, namespace, command):
    exec_command = ["/bin/sh", "-c", command]
    resp = stream(api_instance.connect_get_namespaced_pod_exec,
                name,
                namespace,
                command=exec_command,
                container=container_name,
                stderr=True, stdin=False,
                stdout=True, tty=False,
                _preload_content=False)
    return resp

def check_logs_message(pod_name, container_name, namespace, message):
    # Create a Kubernetes API client
    core_api = client.CoreV1Api()
    # Stream container logs
    stream = core_api.read_namespaced_pod_log(
        name=pod_name,
        namespace=namespace,
        container=container_name,
        follow=True,  # This allows you to stream logs in real-time
        _preload_content=False,
    )
    found = False
    while True:
        line = stream.readline()
        if line:
            print(line)
            if message in line:
                found = True
                break  # Stop the loop when the desired message is found

    stream.close()
    
    return found

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
        record_video = request.data.get('record_video')
        if namespace is None:
            record_video = False
        create_timeout = request.data.get('create_timeout')
        if create_timeout is None:
            create_timeout = 60
            
       # default_selenium_hub_image = 'selenium/hub:4.1.2'
       # default_selenium_node_image = 'selenium/node-chrome:4.1.2'
       # default_se_node_session_timeout = 300  # Default timeout in seconds
       # default_selenium_node_video_image = 'ghcr.io/noesis-devops/kubernetes-backend-pod-managment/selenium/video:1.0.1'

        default_selenium_hub_image = 'europe-west1-docker.pkg.dev/automation-prd-p-846221/nosartifactory/docker-hub-virtual/selenium/hub:4.11.0'
        default_selenium_node_image = 'europe-west1-docker.pkg.dev/automation-prd-p-846221/nosartifactory/docker-hub-virtual/selenium/node-chrome:4.11.0'
        default_se_node_session_timeout = 300  # Default timeout in seconds
        default_selenium_node_video_image = 'europe-west1-docker.pkg.dev/automation-prd-p-846221/nosartifactory/docker-ntx-api-k8s-local/noesis-devops/kubernetes-backend-pod-managment/selenium-video:1.0.1'
        default_http_proxy = ''
        default_https_proxy = ''
        default_no_proxy = ''
        
        custom_variables = {
            'port': port_range,
            'selenium_hub_image': default_selenium_hub_image,
            'selenium_node_image': default_selenium_node_image,
            'selenium_node_video_image': default_selenium_node_video_image,
            #'selenium_hub_image': request.data.get('selenium-hub-image', default_selenium_hub_image),
            #'selenium_node_image': request.data.get('selenium-node-image', default_selenium_node_image),
            #'selenium_node_video_image': request.data.get('selenium-node-video-image', default_selenium_node_video_image),
            'se_node_session_timeout': request.data.get('se_node_session_timeout', default_se_node_session_timeout),
            'http_proxy': request.data.get('http_proxy', default_http_proxy),
            'https_proxy': request.data.get('https_proxy', default_https_proxy),
            'no_proxy': request.data.get('no_proxy', default_no_proxy),
        }
        
        return namespace, start_port, end_port, record_video, create_timeout, custom_variables
    def post(self, request):
        # Load Kubernetes configuration
        load_kubernetes_config()
        namespace, start_port, end_port, record_video, create_timeout, custom_variables = self.set_custom_variables(request)
        core_api = client.CoreV1Api()
        apps_api = client.AppsV1Api()
        
        resp = {namespace: {"deployments": [], "services": [], "config_maps": []}}
        
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
                               
        if record_video:
            template_path = Path(__file__).with_name('video-cm.yaml')
            rendered_video_config_map_template = self.substitute_tokens_in_yaml(template_path, custom_variables)
            try:
                api_response = core_api.create_namespaced_config_map(namespace=namespace, body=yaml.safe_load(rendered_video_config_map_template))
                #resp[namespace]["services"].append(api_response.metadata.name)
                print(f"Config Map video-cm-{custom_variables['port']} created successfully.")
                succeeds = True
            except client.exceptions.ApiException as e:
                succeeds = False
                print(f"An error occurred creating config map {api_response.metadata.name}:", e)

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
        template_path = Path(__file__).with_name('selenium_hub_service_pub_sub_template.yaml')
        rendered_selenium_hub_service_pub_sub_template = self.substitute_tokens_in_yaml(template_path, custom_variables)
        try:
            api_response = core_api.create_namespaced_service(namespace=namespace, body=yaml.safe_load(rendered_selenium_hub_service_pub_sub_template))
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

            ready = wait_for_deployment_ready(apps_api, namespace, api_response.metadata.name, timeout_seconds=create_timeout)
            if not ready:
                succeeds = False
            else:
                succeeds = True
        except client.exceptions.ApiException as e:
            succeeds = False
            if e.status == 409 and e.reason == "AlreadyExists":
                print(f"message: {e.message}")
            else:
                print(f"An error occurred creating deployment {api_response.metadata.name}:", e)
        
        
        try:
            if record_video:
                template_path = Path(__file__).with_name('node_video_deployment_template.yaml')
            else:
                template_path = Path(__file__).with_name('node_deployment_template.yaml')
            rendered_node_deployment_template = self.substitute_tokens_in_yaml(template_path, custom_variables)
            api_response = apps_api.create_namespaced_deployment(namespace, yaml.safe_load(rendered_node_deployment_template))
            resp[namespace]["deployments"].append(api_response.metadata.name)
            print(f"Deployment {api_response.metadata.name} created successfully.")

            ready = wait_for_deployment_ready(apps_api, namespace, api_response.metadata.name, timeout_seconds=create_timeout)
            if not ready:
                succeeds = False
            else:
                succeeds = True
        except client.exceptions.ApiException as e:
            succeeds = False
            if e.status == 409 and e.reason == "AlreadyExists":
                print(f"Deployment {api_response.metadata.name} already exists.")
            else:
                print(f"An error occurred creating deployment {api_response.metadata.name}:", e)
        
        if succeeds == False:
            delete_objects(apps_api, core_api, resp, namespace)
            return Response({'message': f'Deployments or services cannot be created: {resp}'}, status=500)
        
        #v1.4.29
        #for deployment in resp[namespace]["deployments"]:
        #    ready = wait_for_deployment_ready(apps_api, namespace, deployment, timeout_seconds=create_timeout)
        #    if ready:
        #        continue
        #    else:
        #        delete_objects(apps_api, core_api, resp, namespace)
        #        return Response({'message': f'Deployment {deployment} did not become ready within the timeout.'}, status=500)


        #found = check_logs_message(f"node-{custom_variables['port']}", f"node-{custom_variables['port']}", namespace, "registered")
        #if found:
         #   resp = exec_cmd(core_api, f"export http_proxy={custom_variables['http_proxy']}; export https_proxy={custom_variables['https_proxy']}; export no_proxy={custom_variables['no_proxy']}")
        #else:
        #    delete_objects(apps_api, core_api, resp, namespace)
        #    return Response({'message': f'Node hasnt been registered'}, status=500)
        #pods = get_pods_by_app_label(f"node-{port}", namespace)
        #print(pods)
        #for pod in pods:
        #    print(pod.metadata.name)
        #    for container in pod.spec.containers:
        #        print(container.name)
        #        if container.name == f"node-{port}":
        #            print("found")
        #            exec_resp = exec_cmd(core_api, pod.metadata.name, container.name, namespace, f"echo \"export http_proxy={custom_variables['http_proxy']}\nexport https_proxy={custom_variables['https_proxy']}\nexport no_proxy={custom_variables['no_proxy']}\" >> ~/.bashrc")
        #            exec_resp = exec_cmd(core_api, pod.metadata.name, container.name, namespace, f". ~/.bashrc")
        #            print(exec_resp)
        #            break
        return Response({'objects_created': resp, "port": custom_variables["port"]})

class PodDeleteView(APIView):
    def delete(self, request):
        load_kubernetes_config()

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
    def get_file_name_pod_exec(self, name, container_name, namespace, command, api_instance):        
        resp = exec_cmd(api_instance, name, container_name, namespace, command)
        while resp.is_open():
            resp.update(timeout=1)
            if resp.peek_stdout():
                output = resp.read_stdout()
                print(f"STDOUT: \n{output}")
                print(output)
                print(type(output))
                file_list = output.split('\n')
                print(file_list)
                for file_name in file_list:
                    print("file_name_before")
                    print(file_name)
                    if ".mp4" in file_name:
                        source_path = file_name
                        print("source_path")
                        print(source_path)
                        return source_path
            if resp.peek_stderr():
                print(f"STDERR: \n{resp.read_stderr()}")

        resp.close()
        
        

        if resp.returncode != 0:
            raise Exception("Script failed")
    def copy_file_from_pod(self, api_instance, pod_name, container_name, src_path, dest_path, namespace="default"):
        try:
            exec_command = ['/bin/sh', '-c', 'cat {src_path} | base64'.format(src_path=src_path)]
            api_response = stream(api_instance.connect_get_namespaced_pod_exec, pod_name, namespace,
                                command=exec_command,
                                container=container_name,
                                stderr=True, stdin=False,
                                stdout=True, tty=False,
                                _preload_content=False)

            file_bytes = b''

            while api_response.is_open():
                api_response.update(timeout=1)
                if api_response.peek_stdout():
                    file_bytes += api_response.read_stdout().encode('utf-8')
                if api_response.peek_stderr():
                    print('STDERR: {0}'.format(api_response.read_stderr()))

            api_response.close()

            # Base64 decode the file content
            file_bytes = base64.b64decode(file_bytes)

            # Write the decoded file content to the destination
            with open(dest_path, 'wb') as dest_file:
                dest_file.write(file_bytes)

            print('File copied successfully.')

        except ApiException as e:
            print('Exception when copying file to the pod: {0} \n'.format(e))
        except Exception as e:
            print('Error copying file: {0} \n'.format(e))

    def delete(self, request, namespace, port):
        load_kubernetes_config()

        # Create Kubernetes API client
        core_api = client.CoreV1Api()
        apps_api = client.AppsV1Api()
        
        pod_data = {"deployments": [], "services": [], "config_maps": []}
        
        # Define a regular expression pattern to match valid port values
        port_pattern = re.compile(r'^\d{1,5}$')
        
        # Validate the port input
        if not port_pattern.match(port):
            return Response({'message': 'Invalid port value'}, status=status.HTTP_400_BAD_REQUEST)
        video_bytes = None
        record_video = False
        try:
             # Example usage:
            destination_path = "/tmp/node-" + port + "-video.mp4"  # Local path where the video will be copied
            container_name = "node-"+ port + "-video"
            pods = get_pods_by_app_label("node-" + port, namespace)
            for pod in pods:
                for container in pod.spec.containers:
                    if container.name == f"node-{port}-video":
                        record_video = True
                        break
                if record_video:
                    print("Record video: on")
                    file_name = self.get_file_name_pod_exec(pod.metadata.name, container_name, namespace, "ls /videos", core_api)
                    print("file_name")
                    print(file_name)
                    src_path = f"/videos/{file_name}"  # File/folder you want to copy
                    dest_path = f"/tmp/{file_name}"  # Destination path on which you want to copy the file/folder
                    self.copy_file_from_pod(api_instance=core_api, pod_name=pod.metadata.name, container_name=container_name, src_path=src_path, dest_path=dest_path,
                                        namespace=namespace)
                    with open(f"/tmp/{file_name}", "rb") as video_file:
                        video_bytes = video_file.read()
                    print("Video read and saved successfully.")
                    os.remove(f"/tmp/{file_name}")
                print("Record video: off")
        except:
            return Response({'message': f'Cannot retrieve video: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        if record_video:
            print(type(video_bytes))
            print(video_bytes)
            response = HttpResponse(video_bytes, content_type='video/mp4')
            response['Content-Disposition'] = 'attachment; filename="video.mp4"'
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
             # Delete matching configsMaps
            config_maps = core_api.list_namespaced_config_map(namespace)
            for config_map in config_maps.items:
                if f"-{port}" in config_map.metadata.name:
                    resp = core_api.delete_namespaced_config_map(config_map.metadata.name, namespace)
                    pod_data["config_maps"].append(config_map.metadata.name)
                    print(resp)
            if record_video:
                return response
            else:
                return Response(pod_data)
        except client.rest.ApiException as e:
            return Response({'message': f'Error deleting: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
