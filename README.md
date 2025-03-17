# Kubernetes Observability with OpenTelemetry and Elastic Cloud

This project demonstrates a three-pod Kubernetes application that generates logs, metrics, and traces and forwards this observability data to Elastic Cloud via the OpenTelemetry Collector.

## Architecture

The project consists of three main components:

1. **Python Flask Application (Pod 1)**: A simple web application that generates logs, metrics, and traces, including occasional error logs.
2. **OpenTelemetry Collector (Pod 2)**: Receives and processes observability data from the application and forwards it to Elastic APM.
3. **Load Generator (Pod 3)**: Sends continuous traffic to the application to ensure constant data flow.

## Prerequisites

- Docker
- Kubernetes cluster (local like Minikube or remote)
- kubectl configured to use your cluster
- Elastic Cloud deployment with the following:
  - Elasticsearch
  - Kibana
  - APM Server with OTLP endpoint and token

## Directory Structure

```
.
├── app/                      # Flask application
│   ├── app.py                # Application code
│   ├── Dockerfile            # Docker build file
│   └── requirements.txt      # Python dependencies
├── load-generator/           # Load generator
│   ├── load_generator.py     # Load generator code
│   ├── Dockerfile            # Docker build file
│   └── requirements.txt      # Python dependencies
├── otel-collector/           # OpenTelemetry Collector
│   └── otel-collector-config.yaml # Collector configuration
├── kubernetes/               # Kubernetes manifests
│   ├── namespace.yaml        # Namespace
│   ├── elastic-secret.yaml   # Secret for Elastic Cloud credentials
│   ├── otel-collector-configmap.yaml # ConfigMap for collector config
│   ├── otel-collector-deployment.yaml # Collector deployment
│   ├── otel-collector-service.yaml # Collector service
│   ├── app-deployment.yaml   # Application deployment
│   ├── app-service.yaml      # Application service
│   ├── load-generator-deployment.yaml # Load generator deployment
│   └── kustomization.yaml    # Kustomize file
└── Makefile                  # Build and deployment commands
```

## Setup and Deployment

### Step 1: Configure Elastic APM Credentials

Edit the `kubernetes/elastic-secret.yaml` file to include your Elastic APM endpoint and token:

```yaml
stringData:
  elastic-apm-endpoint: "https://your-apm-server-endpoint:443"
  elastic-apm-token: "your-apm-token"
```

Note: This project uses the following Elastic APM configurations:
- OTEL_EXPORTER_OTLP_ENDPOINT: The APM server endpoint
- OTEL_EXPORTER_OTLP_HEADERS: Authorization bearer token
- OTEL_METRICS_EXPORTER: otlp
- OTEL_LOGS_EXPORTER: otlp
- OTEL_RESOURCE_ATTRIBUTES: service.name, service.version, and deployment.environment

### Step 2: Build the Docker Images

Build the application and load generator Docker images:

```bash
make build-all
```

### Step 3: Deploy to Kubernetes

Deploy all components to the Kubernetes cluster:

```bash
make deploy-all
```

Alternatively, use Kustomize:

```bash
make deploy-kustomize
```

### Step 4: Check the Status

Check the status of the deployments:

```bash
make status
```

## Verification

### View Kubernetes Resources

```bash
# Check pods
kubectl get pods -n otel-demo

# Check services
kubectl get svc -n otel-demo

# Check logs of the application
kubectl logs -n otel-demo deployment/otel-demo-app

# Check logs of the OpenTelemetry Collector
kubectl logs -n otel-demo deployment/otel-collector

# Check logs of the load generator
kubectl logs -n otel-demo deployment/load-generator
```

### Verify in Elastic Cloud

1. Log in to your Kibana instance in Elastic Cloud
2. Navigate to the "Observability" section
3. Check the "APM" application to see your service
4. View logs, metrics, and traces in the APM UI
5. You can also use the "Logs" and "Metrics" applications to explore the data

## Cleanup

To delete all resources created by this demo:

```bash
make clean-all
```

## Customization

- **Scaling**: Adjust replica counts in deployment files to scale components.
- **Load Generation**: Modify REQUESTS_PER_SECOND in load-generator-deployment.yaml to adjust traffic.
- **Error Rate**: Edit the application code to change the frequency of simulated errors.
- **Service Name**: Update the OTEL_RESOURCE_ATTRIBUTES in app-deployment.yaml to change the service name and version.

## Troubleshooting

### Common Issues

1. **No data in Elastic Cloud**:
   - Verify OpenTelemetry Collector logs
   - Check Elastic APM token and endpoint
   - Ensure all pods are running
   - Verify the OTLP exporter configuration

2. **Application crashes**:
   - Check application logs
   - Verify resource limits are sufficient

3. **Load generator not sending traffic**:
   - Check load generator logs
   - Verify it can reach the application service 