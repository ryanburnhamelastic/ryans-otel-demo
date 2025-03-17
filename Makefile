.PHONY: build-app build-load-generator build-all deploy-all deploy-namespace deploy-collector deploy-app deploy-load-generator clean-all

# Build Docker images
build-app:
	docker build -t otel-demo-app:latest ./app

build-load-generator:
	docker build -t load-generator:latest ./load-generator

build-all: build-app build-load-generator

# Kubernetes deployments
deploy-namespace:
	kubectl apply -f ./kubernetes/namespace.yaml

deploy-collector: deploy-namespace
	kubectl apply -f ./kubernetes/elastic-secret.yaml
	kubectl apply -f ./kubernetes/otel-collector-configmap.yaml
	kubectl apply -f ./kubernetes/otel-collector-deployment.yaml
	kubectl apply -f ./kubernetes/otel-collector-service.yaml

deploy-app: deploy-namespace
	kubectl apply -f ./kubernetes/app-deployment.yaml
	kubectl apply -f ./kubernetes/app-service.yaml

deploy-load-generator: deploy-namespace
	kubectl apply -f ./kubernetes/load-generator-deployment.yaml

deploy-all: deploy-namespace deploy-collector deploy-app deploy-load-generator

# Alternative deployment using kustomize
deploy-kustomize:
	kubectl apply -k ./kubernetes

# Clean up
clean-all:
	kubectl delete namespace otel-demo

# Check status
status:
	@echo "Checking pod status..."
	kubectl get pods -n otel-demo
	@echo "\nChecking service status..."
	kubectl get svc -n otel-demo 