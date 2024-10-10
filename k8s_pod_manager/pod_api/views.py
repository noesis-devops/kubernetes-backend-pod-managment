from django.http import StreamingHttpResponse, JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from kubernetes import client, config
from kubernetes.stream import stream
from kubernetes.client.rest import ApiException
import json, logging, requests, time

logger = logging.getLogger(__name__)

def load_kubernetes_config():
    try:
        config.load_incluster_config()
        logger.info("Running inside the cluster, using in-cluster configuration")
    except Exception:
        config.load_kube_config()
        logger.info("Running outside the cluster, using kubeconfig")

def ensure_selenium_hub(namespace, selenium_hub_image):
    apps_api = client.AppsV1Api()
    deployment_name = 'selenium-hub'
    try:
        deployment = apps_api.read_namespaced_deployment(deployment_name, namespace)
        current_image = deployment.spec.template.spec.containers[0].image
        if current_image != selenium_hub_image:
            deployment.spec.template.spec.containers[0].image = selenium_hub_image
            apps_api.patch_namespaced_deployment(deployment_name, namespace, deployment)
            logger.info(f"Selenium Hub deployment '{deployment_name}' updated to image '{selenium_hub_image}'.")
        else:
            logger.info(f"Selenium Hub deployment '{deployment_name}' already has image '{selenium_hub_image}'.")
    except ApiException as e:
        if e.status == 404:
            deployment = {
                'apiVersion': 'apps/v1',
                'kind': 'Deployment',
                'metadata': {'name': deployment_name, 'namespace': namespace},
                'spec': {
                    'replicas': 1,
                    'selector': {'matchLabels': {'app': 'selenium-hub'}},
                    'template': {
                        'metadata': {'labels': {'app': 'selenium-hub'}},
                        'spec': {
                            'containers': [{
                                'name': 'selenium-hub',
                                'image': selenium_hub_image,
                                'ports': [
                                    {'containerPort': 4442, 'name': 'publish'},
                                    {'containerPort': 4443, 'name': 'subscribe'},
                                    {'containerPort': 4444, 'name': 'hub'}
                                ],
                                'livenessProbe': {
                                    'httpGet': {'path': '/readyz', 'port': 4444},
                                    'initialDelaySeconds': 10,
                                    'periodSeconds': 10,
                                    'timeoutSeconds': 10,
                                    'successThreshold': 1,
                                    'failureThreshold': 10
                                },
                                'readinessProbe': {
                                    'httpGet': {'path': '/readyz', 'port': 4444},
                                    'initialDelaySeconds': 12,
                                    'periodSeconds': 10,
                                    'timeoutSeconds': 10,
                                    'successThreshold': 1,
                                    'failureThreshold': 10
                                },
                                'env': [
                                    {'name': 'SE_SUB_PATH', 'value': '/'}
                                ]
                            }]
                        }
                    }
                }
            }
            apps_api.create_namespaced_deployment(namespace=namespace, body=deployment)
            logger.info(f"Selenium Hub deployment '{deployment_name}' created successfully.")
        else:
            logger.error(f"Error ensuring Selenium Hub deployment: {str(e)}")
            raise

def create_selenium_node_deployment(namespace, selenium_node_image, selenium_node_video_image=None):
    apps_api = client.AppsV1Api()
    deployment_name = 'selenium-chrome-node'
    try:
        deployment = apps_api.read_namespaced_deployment(deployment_name, namespace)
        current_image = deployment.spec.template.spec.containers[0].image
        if current_image != selenium_node_image:
            deployment.spec.template.spec.containers[0].image = selenium_node_image
            apps_api.patch_namespaced_deployment(deployment_name, namespace, deployment)
            logger.info(f"Selenium Node deployment '{deployment_name}' updated to image '{selenium_node_image}'.")
        else:
            logger.info(f"Selenium Node deployment '{deployment_name}' already has image '{selenium_node_image}'.")
    except ApiException as e:
        if e.status == 404:
            containers = [{
                'name': 'selenium-chrome-node',
                'image': selenium_node_image,
                'ports': [{'containerPort': 5555}],
                'env': [
                    {'name': 'HTTP_PROXY', 'value': ""},
                    {'name': 'HTTPS_PROXY', 'value': ""},
                    {'name': 'NO_PROXY', 'value': ""},
                    {'name': 'SE_EVENT_BUS_HOST', 'value': 'selenium-hub-service'},
                    {'name': 'SE_EVENT_BUS_PUBLISH_PORT', 'value': '4442'},
                    {'name': 'SE_EVENT_BUS_SUBSCRIBE_PORT', 'value': '4443'},
                    {'name': 'SE_NODE_SESSION_TIMEOUT', 'value': '60'}
                ],
                'volumeMounts': [{'name': 'dshm', 'mountPath': '/dev/shm'}],
                'resources': {
                    'limits': {'cpu': '0.5', 'memory': '1Gi'},
                    'requests': {'cpu': '0.5', 'memory': '1Gi'}
                }
            }]
            if selenium_node_video_image:
                containers.append({
                    'name': 'selenium-chrome-node-video',
                    'image': selenium_node_video_image,
                    'imagePullPolicy': 'IfNotPresent',
                    'env': [
                        {'name': 'UPLOAD_DESTINATION_PREFIX', 'value': 'video_'},
                        {'name': 'SE_EVENT_BUS_HOST', 'value': 'selenium-hub-service'},
                        {'name': 'SE_EVENT_BUS_PUBLISH_PORT', 'value': '4442'},
                        {'name': 'SE_EVENT_BUS_SUBSCRIBE_PORT', 'value': '4443'},
                        {'name': 'SE_NODE_SESSION_TIMEOUT', 'value': '60'}
                    ],
                    'ports': [{'containerPort': 5666, 'protocol': 'TCP'}],
                    'volumeMounts': [
                        {'name': 'dshm', 'mountPath': '/dev/shm'},
                        {'name': 'video-scripts', 'mountPath': '/opt/bin/video.sh', 'subPath': 'video.sh'}
                    ],
                    'resources': {
                        'limits': {'cpu': '0.5', 'memory': '1Gi'},
                        'requests': {'cpu': '0.5', 'memory': '1Gi'}
                    }
                })
            deployment = {
                'apiVersion': 'apps/v1',
                'kind': 'Deployment',
                'metadata': {'name': deployment_name, 'namespace': namespace},
                'spec': {
                    'replicas': 0,
                    'selector': {'matchLabels': {'app': deployment_name}},
                    'template': {
                        'metadata': {'labels': {'app': deployment_name}},
                        'spec': {
                            'containers': containers,
                            'volumes': [
                                {'name': 'dshm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '1Gi'}}
                            ]
                        }
                    }
                }
            }
            if selenium_node_video_image:
                deployment['spec']['template']['spec']['volumes'].append({
                    'name': 'video-scripts',
                    'configMap': {'name': 'selenium-video'}
                })
            apps_api.create_namespaced_deployment(namespace=namespace, body=deployment)
            logger.info(f"Selenium Node deployment '{deployment_name}' created successfully.")
        else:
            logger.error(f"Error ensuring Selenium Node deployment: {str(e)}")
            raise

def stream_video_from_pod(api_instance, pod_name, container_name, namespace, file_path):
    exec_command = ['cat', file_path]
    try:
        resp = stream(api_instance.connect_get_namespaced_pod_exec,
                      pod_name,
                      namespace,
                      command=exec_command,
                      container=container_name,
                      stderr=True, stdin=False,
                      stdout=True, tty=False,
                      _preload_content=False)
    except ApiException as e:
        logger.error(f"Error executing command in pod '{pod_name}': {str(e)}")
        raise

    def file_stream_generator():
        while resp.is_open():
            resp.update(timeout=1)
            if resp.peek_stdout():
                yield resp.read_stdout()
            if resp.peek_stderr():
                logger.error(f"Error streaming video from pod: {resp.read_stderr()}")
        resp.close()

    return file_stream_generator

def get_pod_for_session(selenium_hub_url, session_id):
    try:
        query = {"query": "{ sessionsInfo { sessions { sessionId nodeId } } }"}
        response = requests.post(f"{selenium_hub_url}", json=query)
        response.raise_for_status()
        data = response.json()
        sessions = data.get("data", {}).get("sessionsInfo", {}).get("sessions", [])
        for session in sessions:
            if session.get("sessionId") == session_id:
                node_id = session.get("nodeId")
                query_node = {"query": "{ nodes { id uri } }"}
                response_node = requests.post(f"{selenium_hub_url}", json=query_node)
                response_node.raise_for_status()
                nodes_data = response_node.json()
                for node in nodes_data.get("data", {}).get("nodes", []):
                    if node.get("id") == node_id:
                        return node.get("uri")
        return None
    except Exception as e:
        logger.error(f"Error querying Selenium Hub: {str(e)}")
        return None

@csrf_exempt
def proxy_view(request, subpath=''):
    namespace = 'testingon'
    service_name = 'selenium-hub-service'
    base_url = f'http://{service_name}.{namespace}.svc.cluster.local:32000/wd/hub'
    logger.info(f"Base URL: {base_url}")
    if subpath.startswith('/'):
        subpath = subpath[1:]
    selenium_grid_url = f'{base_url}/{subpath}' if subpath else base_url
    try:
        excluded_headers = ['host', 'content-length', 'transfer-encoding', 'connection']
        headers = {key: value for key, value in request.headers.items() if key.lower() not in excluded_headers}
        data = request.body if request.method in ['POST', 'PUT', 'PATCH'] else None
        if request.method == 'POST' and (subpath == 'session' or subpath.startswith('session')):
            payload = json.loads(data)
            capabilities = payload.get('capabilities', {})
            always_match = capabilities.get('alwaysMatch', {})
            record_video = payload.get('record_video', False)
            if record_video:
                always_match['recordVideo'] = True
            else:
                always_match['recordVideo'] = False
            capabilities['alwaysMatch'] = always_match
            payload['capabilities'] = capabilities
            selenium_hub_image = payload.get('selenium-hub-image', 'selenium/hub:4.11.0')
            selenium_node_image = payload.get('selenium-node-image', 'selenium/node-chrome:4.11.0')
            selenium_node_video_image = payload.get('selenium-node-video-image', 'ghcr.io/noesis-devops/kubernetes-backend-pod-managment/selenium/video:1.0.1') if record_video else None
            ensure_selenium_hub(namespace, selenium_hub_image)
            create_selenium_node_deployment(namespace, selenium_node_image, selenium_node_video_image)
            data = json.dumps(payload)
        logger.info(f"Proxying {request.method} request to {selenium_grid_url}")
        response = requests.request(
            method=request.method,
            url=selenium_grid_url,
            headers=headers,
            data=data,
            params=request.GET
        )
        if request.method == 'POST' and (subpath == 'session' or subpath.startswith('session')):
            if response.status_code in [200, 201]:
                response_json = response.json()
                session_id = response_json.get('sessionId')
                if not session_id:
                    logger.error("Session ID not found in the response.")
                    return JsonResponse({'error': 'Session ID not found in the response.'}, status=500)
                if record_video:
                    logger.info(f"Recording video for session {session_id}. Monitoring session status...")
                    poll_interval = 5
                    max_wait_time = 300
                    elapsed_time = 0
                    selenium_hub_url = f'http://{service_name}.{namespace}.svc.cluster.local:32000/graphql'
                    while elapsed_time < max_wait_time:
                        pod_uri = get_pod_for_session(selenium_hub_url, session_id)
                        if not pod_uri:
                            logger.info(f"Session {session_id} has completed.")
                            break
                        logger.info(f"Session {session_id} is still running. Waiting...")
                        time.sleep(poll_interval)
                        elapsed_time += poll_interval
                    if elapsed_time >= max_wait_time:
                        logger.error(f"Timeout while waiting for session {session_id} to complete.")
                        return JsonResponse({'error': 'Timeout while waiting for session to complete.'}, status=504)
                    pod_uri = get_pod_for_session(selenium_hub_url, session_id)
                    if not pod_uri:
                        logger.error(f"Session {session_id} has completed but pod URI not found.")
                        return JsonResponse({'error': 'Pod URI not found after session completion.'}, status=500)
                    try:
                        pod_ip = pod_uri.split("http://")[1].split(":")[0]
                    except IndexError:
                        logger.error(f"Invalid pod URI format: {pod_uri}")
                        return JsonResponse({"error": "Invalid pod URI format"}, status=500)
                    core_api = client.CoreV1Api()
                    try:
                        pods = core_api.list_namespaced_pod(namespace=namespace).items
                        pod = next((p for p in pods if p.status.pod_ip == pod_ip), None)
                    except ApiException as e:
                        logger.error(f"Error listing pods: {str(e)}")
                        return JsonResponse({"error": "Error listing pods"}, status=500)
                    if pod is None:
                        logger.error(f"Pod with IP {pod_ip} not found.")
                        return JsonResponse({"error": "Pod not found"}, status=404)
                    video_container = None
                    for container in pod.spec.containers:
                        if 'video' in container.name.lower():
                            video_container = container
                            break
                    if not video_container:
                        logger.error(f"Video container not found in pod {pod.metadata.name}.")
                        return JsonResponse({"error": "Video recording not enabled for this session."}, status=400)
                    file_path = f"/videos/{session_id}.mp4"
                    try:
                        video_stream = stream_video_from_pod(core_api, pod.metadata.name, video_container.name, namespace, file_path)
                        video_response = StreamingHttpResponse(video_stream(), content_type='video/mp4')
                        video_response['Content-Disposition'] = f'attachment; filename="{session_id}.mp4"'
                        logger.info(f"Video for session {session_id} retrieved successfully.")
                        return video_response
                    except Exception as e:
                        logger.error(f"Error streaming video: {str(e)}")
                        return JsonResponse({"error": f"Error streaming video: {str(e)}"}, status=500)
        return HttpResponse(
            content=response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type')
        )
    except Exception as e:
        logger.error(f"Error streaming video: {str(e)}")
