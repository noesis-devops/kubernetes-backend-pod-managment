from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
import requests, logging

logger = logging.getLogger(__name__)

def load_kubernetes_config():
    try:
        config.load_incluster_config()
        logger.info("Running inside the cluster, using in-cluster configuration")
    except Exception as e:
        config.load_kube_config()
        logger.info("Running outside the cluster, using kubeconfig")

@csrf_exempt
def proxy_view(request, subpath=''):
    namespace = 'testingon'
    service_name = f'selenium-hub-service'
    
    base_url = f'http://{service_name}.{namespace}.svc.cluster.local:32000/graphql'
    logger.info(f"Base URL: {base_url}")
    
    if subpath.startswith('/'):
        subpath = subpath[1:]
        
    selenium_grid_url = f'{base_url}/{subpath}' if subpath else base_url

    try:
        excluded_headers = ['host', 'content-length', 'transfer-encoding', 'connection']
        headers = {key: value for key, value in request.headers.items() if key.lower() not in excluded_headers}
        data = request.body if request.method in ['POST', 'PUT', 'PATCH'] else None

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

    except requests.RequestException as e:
        logger.exception(f"ClientError while proxying request to {selenium_grid_url}: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
def proxy_delete(request, namespace, port):
    v1 = client.CoreV1Api()
    service_name = f'ntx-api-kubernetes-ntx-pod-management-service'
    namespace = 'testingon'

    try:
        service = v1.read_namespaced_service(name=service_name, namespace=namespace)
        logger.info(f"Fetched service '{service_name}' in namespace '{namespace}'.")
    except ApiException as e:
        logger.error(f"Error fetching service {service_name}: {str(e)}")
        return JsonResponse({'error': f'Error fetching service {service_name}: {str(e)}'}, status=500)

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
        response = requests.delete(
            url=base_url,
            headers=headers,
            params=request.GET,
            data=data,
            timeout=30
        )

        logger.info(f"Received response with status code {response.status_code} from {base_url}")
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


def health_check(request):
    selenium_hub_url = 'http://selenium-hub.testingon.svc.cluster.local:4444/status'
    try:
        response = requests.get(selenium_hub_url)
        if response.status_code == 200:
            return JsonResponse({'status': 'healthy'})
        else:
            return JsonResponse({'status': 'unhealthy'}, status=500)
    except requests.RequestException as e:
        logger.error(f"Health check failed for Selenium Hub: {str(e)}")
        return JsonResponse({'status': 'unhealthy', 'error': str(e)}, status=500)
