# Use a base image
FROM python:3.9

#USER root
# Set environment variables
ENV PYTHONUNBUFFERED 1

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . /app/

# Expose the port the application runs on
EXPOSE 8000
#RUN mkdir /root/.kube
#RUN ls -la /root
#COPY ./config /root/.kube/
#RUN cat /root/.kube/config


# Command to run the application
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
