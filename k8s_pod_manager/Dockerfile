# Use a base image
FROM python:3.9

#USER root
# Set environment variables
ENV PYTHONUNBUFFERED 1

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY ./k8s_pod_manager/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /app/charts

# Copy the rest of the application
COPY ./k8s_pod_manager/. /app/

# Install dependencies and Helm
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3 \
    && chmod +x get_helm.sh \
    && ./get_helm.sh

COPY ./charts/selenium-grid/. /app/selenium-grid-chart/

# Expose the port the application runs on
EXPOSE 8000
#RUN mkdir /root/.kube
#RUN ls -la /root
#COPY ./config /root/.kube/
#RUN cat /root/.kube/config


# Command to run the application
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
