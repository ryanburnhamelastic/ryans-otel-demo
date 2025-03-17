import logging
import os
import random
import time
from flask import Flask, request, jsonify

# OpenTelemetry imports
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Set up OpenTelemetry resource
resource = Resource(attributes={
    SERVICE_NAME: "otel-demo-app"
})

# Configure trace provider
trace_exporter = OTLPSpanExporter(
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://otel-collector:4318/v1/traces")
)
trace_provider = TracerProvider(resource=resource)
trace_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
trace.set_tracer_provider(trace_provider)

# Configure metrics provider
metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(
        endpoint=os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "http://otel-collector:4318/v1/metrics")
    ),
    export_interval_millis=5000
)
metric_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(metric_provider)

# Create tracer and meter
tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)

# Create metrics
request_counter = meter.create_counter(
    "app_request_count",
    description="Number of requests received"
)
response_time_histogram = meter.create_histogram(
    "app_response_time",
    description="Response time in seconds"
)
error_counter = meter.create_counter(
    "app_error_count",
    description="Number of errors generated"
)

# Create Flask app
app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)

@app.route("/")
def hello():
    logger.info("Received request to root endpoint")
    
    # Record request metric
    request_counter.add(1, {"endpoint": "root", "method": "GET"})
    
    # Start timing
    start_time = time.time()
    
    # Simulate random processing time
    time.sleep(random.uniform(0.05, 0.2))
    
    # Randomly generate an error (1 in 10 chance)
    if random.randint(1, 10) == 1:
        error_counter.add(1, {"endpoint": "root", "method": "GET"})
        logger.error("Random error generated on root endpoint")
        
        # Record response time
        elapsed = time.time() - start_time
        response_time_histogram.record(elapsed, {"endpoint": "root", "method": "GET", "status": "error"})
        
        return jsonify({"error": "Random error occurred"}), 500
    
    # Record response time
    elapsed = time.time() - start_time
    response_time_histogram.record(elapsed, {"endpoint": "root", "method": "GET", "status": "success"})
    
    return jsonify({"message": "Hello from the OpenTelemetry Demo App!"})

@app.route("/api/data")
def get_data():
    logger.info("Received request to /api/data endpoint")
    
    # Record request metric
    request_counter.add(1, {"endpoint": "api_data", "method": "GET"})
    
    # Start timing
    start_time = time.time()
    
    with tracer.start_as_current_span("process-data") as span:
        # Add span attributes
        span.set_attribute("component", "data_processor")
        
        # Simulate data processing
        time.sleep(random.uniform(0.1, 0.3))
        
        # Simulate a sub-operation
        with tracer.start_as_current_span("fetch-data-items") as child_span:
            child_span.set_attribute("items_count", random.randint(10, 50))
            time.sleep(random.uniform(0.05, 0.15))
            
            # Randomly generate an error (1 in 10 chance)
            if random.randint(1, 10) == 1:
                error_counter.add(1, {"endpoint": "api_data", "method": "GET"})
                logger.error("Error fetching data items")
                child_span.set_status(trace.StatusCode.ERROR)
                child_span.record_exception(Exception("Failed to fetch data items"))
                
                # Record response time
                elapsed = time.time() - start_time
                response_time_histogram.record(elapsed, {"endpoint": "api_data", "method": "GET", "status": "error"})
                
                return jsonify({"error": "Failed to process data"}), 500
    
    # Generate sample data
    data = {
        "items": [{"id": i, "value": random.randint(1, 100)} for i in range(random.randint(5, 15))],
        "timestamp": time.time()
    }
    
    # Record response time
    elapsed = time.time() - start_time
    response_time_histogram.record(elapsed, {"endpoint": "api_data", "method": "GET", "status": "success"})
    
    return jsonify(data)

@app.route("/health")
def health():
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port) 