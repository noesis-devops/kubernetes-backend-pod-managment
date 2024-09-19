# Use a base image
FROM python:3.9

# Set environment variables
ENV PYTHONUNBUFFERED 1

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY ./k8s_pod_manager/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY ./k8s_pod_manager/. /app/

RUN mkdir -p /app/config

ARG KUBECONFIG
RUN if [ -n "$KUBECONFIG" ]; then echo $KUBECONFIG | base64 -d > /app/config/kubeconfig; fi

ENV KUBECONFIG=/app/config/kubeconfig

# Expose the port the application runs on
EXPOSE 8000

# Command to run the application
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "k8s_pod_manager.asgi:application"]

