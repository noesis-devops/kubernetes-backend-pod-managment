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
    except Exception as e:
        logger.warning(f"Failed to load in-cluster config: {str(e)}. Falling back to kubeconfig.")
        config.load_kube_config()
        logger.info("Running outside the cluster, using kubeconfig")


def ensure_selenium_hub(namespace, selenium_hub_image):
    apps_api = client.AppsV1Api()
    load_kubernetes_config()
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
                                    'timeoutSeconds': 60,
                                    'successThreshold': 1,
                                    'failureThreshold': 10
                                },
                                'readinessProbe': {
                                    'httpGet': {'path': '/readyz', 'port': 4444},
                                    'initialDelaySeconds': 12,
                                    'periodSeconds': 10,
                                    'timeoutSeconds': 60,
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
            try:
                apps_api.create_namespaced_deployment(namespace=namespace, body=deployment)
                logger.info(f"Selenium Hub deployment '{deployment_name}' created successfully.")
            except ApiException as create_e:
                logger.error(f"Failed to create Selenium Hub deployment: {str(create_e)}")
                raise
        else:
            logger.error(f"Error ensuring Selenium Hub deployment: {str(e)}")
            raise


def create_selenium_node_deployment(namespace, selenium_node_image, selenium_node_video_image=None):
    apps_api = client.AppsV1Api()
    load_kubernetes_config()
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
            try:
                apps_api.create_namespaced_deployment(namespace=namespace, body=deployment)
                logger.info(f"Selenium Node deployment '{deployment_name}' created successfully.")
            except ApiException as create_e:
                logger.error(f"Failed to create Selenium Node deployment: {str(create_e)}")
                raise
        else:
            logger.error(f"Error ensuring Selenium Node deployment: {str(e)}")
            raise


@csrf_exempt
def proxy_view(request, subpath=''):
    namespace = 'testingon'
    service_name = 'selenium-hub-service'
    load_kubernetes_config()
    base_url = f'http://{service_name}.{namespace}.svc.cluster.local:32000/wd/hub/session'
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
            # Force record_video to be False by removing related variables
            # record_video = False  # No longer needed
            # selenium_node_video_image = None  # No longer needed
            selenium_hub_image = payload.get('selenium-hub-image', 'selenium/hub:4.1.2')
            selenium_node_image = payload.get('selenium-node-image', 'selenium/node-chrome:4.1.2')
            ensure_selenium_hub(namespace, selenium_hub_image)
            create_selenium_node_deployment(namespace, selenium_node_image)
            data = json.dumps(payload)

        logger.info(f"Proxying {request.method} request to {selenium_grid_url}")
        response = requests.request(
            method=request.method,
            url=selenium_grid_url,
            headers=headers,
            data=data,
            params=request.GET
        )


        return HttpResponse(
            content=response.content,
            status=response.status_code,
            content_type=response.headers.get('Content-Type')
        )
    except Exception as e:
        logger.error(f"Unhandled exception in proxy_view: {str(e)}")
        return JsonResponse({"error": f"Unhandled exception: {str(e)}"}, status=500)
