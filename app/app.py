import logging
import os
import random
import time
import uuid
import json
import socket
import platform
import datetime
from flask import Flask, request, jsonify, g
import traceback

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

# Custom JSON formatter for ECS-compatible logs
class EcsJsonFormatter(logging.Formatter):
    def format(self, record):
        # Standard ECS fields
        timestamp = datetime.datetime.utcnow().isoformat() + "Z"
        ecs_version = "1.12.0"  # Using current ECS version
        
        # Build ECS-compliant log record
        log_record = {
            "@timestamp": timestamp,
            "ecs": {
                "version": ecs_version
            },
            "log": {
                "level": record.levelname.lower(),  # ECS uses lowercase level names
                "logger": record.name,
                "origin": {
                    "file": {
                        "name": os.path.basename(record.pathname),
                        "line": record.lineno
                    },
                    "function": record.funcName
                }
            },
            "message": record.getMessage(),
            "process": {
                "pid": record.process,
                "thread": {
                    "id": record.thread,
                    "name": record.threadName
                }
            },
            "host": {
                "hostname": socket.gethostname(),
                "os": {
                    "platform": platform.system(),
                    "version": platform.release(),
                    "name": platform.system()
                }
            },
            "service": {
                "name": "otel-demo-app",
                "version": "1.0.0",
                "environment": os.getenv("DEPLOYMENT_ENVIRONMENT", "production")
            },
            "event": {
                "created": timestamp,
                "module": record.module
            }
        }
        
        # Add trace context if available
        current_span = trace.get_current_span()
        if hasattr(current_span, "get_span_context"):
            ctx = current_span.get_span_context()
            if ctx.is_valid:
                trace_id = format(ctx.trace_id, '032x')
                span_id = format(ctx.span_id, '016x')
                
                # Add trace info in ECS format
                if "trace" not in log_record:
                    log_record["trace"] = {}
                log_record["trace"]["id"] = trace_id
                
                if "span" not in log_record:
                    log_record["span"] = {}
                log_record["span"]["id"] = span_id
        
        # Add request context if available
        if hasattr(g, 'request_id'):
            if "transaction" not in log_record:
                log_record["transaction"] = {}
            log_record["transaction"]["id"] = g.request_id
            
            # Add HTTP request details if this is a web request
            if request:
                if "http" not in log_record:
                    log_record["http"] = {
                        "request": {
                            "method": request.method,
                            "body": {
                                "bytes": request.content_length or 0
                            }
                        }
                    }
                    
                    if "url" not in log_record["http"]:
                        log_record["http"]["url"] = {}
                    
                    log_record["http"]["url"]["path"] = request.path
                    log_record["http"]["url"]["query"] = request.query_string.decode('utf-8') if request.query_string else ""
                    log_record["http"]["url"]["original"] = request.url
                    
                    if "client" not in log_record:
                        log_record["client"] = {}
                    
                    log_record["client"]["ip"] = request.headers.get('X-Forwarded-For', request.remote_addr)
                    log_record["client"]["user_agent"] = {"original": request.headers.get('User-Agent', 'Unknown')}
        
        # Add any exception info
        if record.exc_info:
            exception_type = record.exc_info[0].__name__
            exception_message = str(record.exc_info[1])
            exception_stacktrace = traceback.format_exception(*record.exc_info)
            
            if "error" not in log_record:
                log_record["error"] = {}
            
            log_record["error"]["type"] = exception_type
            log_record["error"]["message"] = exception_message
            log_record["error"]["stack_trace"] = exception_stacktrace
        
        # Add extra fields from record
        if hasattr(record, "extra_fields"):
            for key, value in record.extra_fields.items():
                # Handle special ECS fields
                if key == "event_type":
                    if "event" not in log_record:
                        log_record["event"] = {}
                    log_record["event"]["type"] = value
                elif key == "error_type" and "error" not in log_record:
                    log_record["error"] = {"type": value}
                elif key == "error_details" and "error" in log_record:
                    log_record["error"]["message"] = value
                elif key == "duration_ms":
                    if "event" not in log_record:
                        log_record["event"] = {}
                    log_record["event"]["duration"] = value * 1000000  # ms to nanoseconds per ECS
                else:
                    # Put custom fields under labels or custom namespace
                    if "labels" not in log_record:
                        log_record["labels"] = {}
                    log_record["labels"][key] = value
        
        return json.dumps(log_record)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("otel-demo-app")

# Remove default handlers and add JSON handler
for handler in logger.handlers[:]:
    logger.removeHandler(handler)

# Create console handler with ECS JSON formatter
console_handler = logging.StreamHandler()
console_handler.setFormatter(EcsJsonFormatter())
logger.addHandler(console_handler)

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

@app.before_request
def before_request():
    # Generate unique request ID for each request and store in Flask g object
    g.request_id = str(uuid.uuid4())
    g.start_time = time.time()
    
    # Log request details
    user_agent = request.headers.get('User-Agent', 'Unknown')
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    
    logger.info(
        f"Request received: {request.method} {request.path}",
        extra={"extra_fields": {
            "request_id": g.request_id,
            "method": request.method,
            "path": request.path,
            "ip": client_ip,
            "user_agent": user_agent,
            "query_params": dict(request.args),
            "request_headers": dict(request.headers),
            "event_type": "request_received"
        }}
    )

@app.after_request
def after_request(response):
    # Calculate request duration
    duration = time.time() - g.start_time
    
    # Log response details
    logger.info(
        f"Response sent: {response.status_code}",
        extra={"extra_fields": {
            "request_id": g.request_id,
            "status_code": response.status_code,
            "duration_ms": round(duration * 1000, 2),
            "response_size_bytes": len(response.get_data(as_text=False)),
            "event_type": "response_sent",
            "path": request.path
        }}
    )
    
    return response

@app.route("/")
def hello():
    # Log start of business logic processing
    logger.debug(
        "Processing root endpoint request",
        extra={"extra_fields": {
            "request_id": g.request_id,
            "endpoint": "root",
            "event_type": "processing_started"
        }}
    )
    
    # Record request metric
    request_counter.add(1, {"endpoint": "root", "method": "GET"})
    
    # Start timing
    start_time = time.time()
    
    # Add application runtime info
    logger.info(
        "Application runtime details",
        extra={"extra_fields": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "memory_info": {
                "virtual_memory": os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / (1024. ** 3),
                "available_memory": os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_AVPHYS_PAGES') / (1024. ** 3)
            },
            "event_type": "runtime_info"
        }}
    )
    
    # Simulate random processing time
    processing_time = random.uniform(0.05, 0.2)
    time.sleep(processing_time)
    
    logger.info(
        f"Simulated processing delay of {processing_time:.3f} seconds",
        extra={"extra_fields": {
            "request_id": g.request_id,
            "processing_time": processing_time,
            "event_type": "processing_delay"
        }}
    )
    
    # Randomly generate an error (1 in 10 chance)
    if random.randint(1, 10) == 1:
        error_type = random.choice(["database_error", "timeout_error", "validation_error", "authentication_error"])
        error_details = {
            "database_error": "Failed to connect to database after 3 retries",
            "timeout_error": "External API call timed out after 5000ms",
            "validation_error": "Required parameter 'transaction_id' was missing or invalid",
            "authentication_error": "Invalid or expired session token"
        }
        
        error_message = error_details[error_type]
        
        error_counter.add(1, {"endpoint": "root", "method": "GET", "error_type": error_type})
        
        logger.error(
            f"Error in root endpoint: {error_message}",
            extra={"extra_fields": {
                "request_id": g.request_id,
                "error_type": error_type,
                "error_details": error_message,
                "endpoint": "root",
                "event_type": "error_generated"
            }}
        )
        
        # Generate some sample diagnostic data
        logger.debug(
            "Diagnostic information for troubleshooting",
            extra={"extra_fields": {
                "request_id": g.request_id,
                "system_load": os.getloadavg()[0],
                "database_connections": random.randint(5, 30),
                "cache_hit_ratio": random.uniform(0.6, 0.95),
                "event_type": "error_diagnostics"
            }}
        )
        
        # Record response time
        elapsed = time.time() - start_time
        response_time_histogram.record(elapsed, {"endpoint": "root", "method": "GET", "status": "error"})
        
        return jsonify({
            "error": "Random error occurred",
            "error_type": error_type,
            "error_message": error_message,
            "request_id": g.request_id
        }), 500
    
    # Record response time
    elapsed = time.time() - start_time
    response_time_histogram.record(elapsed, {"endpoint": "root", "method": "GET", "status": "success"})
    
    logger.debug(
        "Successfully processed root endpoint request",
        extra={"extra_fields": {
            "request_id": g.request_id,
            "processing_time": elapsed,
            "event_type": "processing_completed"
        }}
    )
    
    return jsonify({
        "message": "Hello from the OpenTelemetry Demo App!",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "request_id": g.request_id
    })

@app.route("/api/data")
def get_data():
    logger.info(
        "Processing data endpoint request",
        extra={"extra_fields": {
            "request_id": g.request_id,
            "endpoint": "api_data",
            "event_type": "processing_started"
        }}
    )
    
    # Record request metric
    request_counter.add(1, {"endpoint": "api_data", "method": "GET"})
    
    # Start timing
    start_time = time.time()
    
    with tracer.start_as_current_span("process-data") as span:
        # Add span attributes
        span.set_attribute("component", "data_processor")
        span.set_attribute("request_id", g.request_id)
        
        logger.debug(
            "Started data processing span",
            extra={"extra_fields": {
                "request_id": g.request_id,
                "span_name": "process-data",
                "event_type": "span_started"
            }}
        )
        
        # Simulate data processing
        processing_time = random.uniform(0.1, 0.3)
        time.sleep(processing_time)
        
        logger.info(
            f"Database query executed in {processing_time:.3f}s",
            extra={"extra_fields": {
                "request_id": g.request_id,
                "query_time": processing_time,
                "db_server": "postgres-primary",
                "db_name": "otel_demo",
                "query_type": "SELECT",
                "rows_returned": random.randint(5, 50),
                "event_type": "database_query"
            }}
        )
        
        # Simulate a sub-operation
        with tracer.start_as_current_span("fetch-data-items") as child_span:
            items_count = random.randint(10, 50)
            child_span.set_attribute("items_count", items_count)
            
            logger.debug(
                f"Fetching {items_count} data items",
                extra={"extra_fields": {
                    "request_id": g.request_id,
                    "items_count": items_count,
                    "cache_status": random.choice(["hit", "miss"]),
                    "event_type": "data_fetch"
                }}
            )
            
            sub_op_time = random.uniform(0.05, 0.15)
            time.sleep(sub_op_time)
            
            logger.info(
                f"Data items fetched in {sub_op_time:.3f}s",
                extra={"extra_fields": {
                    "request_id": g.request_id,
                    "fetch_time": sub_op_time,
                    "items_count": items_count,
                    "event_type": "data_fetch_completed"
                }}
            )
            
            # Randomly generate an error (1 in 10 chance)
            if random.randint(1, 10) == 1:
                error_type = random.choice([
                    "connection_timeout", 
                    "record_not_found", 
                    "schema_validation_error",
                    "permission_denied",
                    "rate_limit_exceeded"
                ])
                
                error_details = {
                    "connection_timeout": "Database connection timed out after 3 seconds",
                    "record_not_found": "Requested record with ID 'txn-12345' was not found in the collection",
                    "schema_validation_error": "Response payload failed schema validation: missing required field 'transaction_date'",
                    "permission_denied": "User 'api-user' lacks permission 'READ_SENSITIVE_DATA' for this resource",
                    "rate_limit_exceeded": "API rate limit of 100 requests per minute exceeded, retry after 24 seconds"
                }
                
                error_message = error_details[error_type]
                
                error_counter.add(1, {"endpoint": "api_data", "method": "GET", "error_type": error_type})
                
                logger.error(
                    f"Error fetching data items: {error_message}",
                    extra={"extra_fields": {
                        "request_id": g.request_id,
                        "error_type": error_type,
                        "error_details": error_message,
                        "source_component": "data_service",
                        "items_processed": random.randint(1, items_count - 1),
                        "retry_count": random.randint(0, 3),
                        "event_type": "data_fetch_error"
                    }}
                )
                
                child_span.set_status(trace.StatusCode.ERROR)
                child_span.record_exception(Exception(f"Failed to fetch data items: {error_message}"))
                
                # Generate more detailed technical error information
                stack_snapshot = [
                    {"function": "fetch_data_items", "line": 247, "file": "data_service.py"},
                    {"function": "query_database", "line": 123, "file": "database.py"},
                    {"function": "execute_query", "line": 89, "file": "connection_pool.py"}
                ]
                
                logger.debug(
                    "Technical error details",
                    extra={"extra_fields": {
                        "request_id": g.request_id,
                        "stack_snapshot": stack_snapshot,
                        "connection_id": f"conn-{random.randint(1000, 9999)}",
                        "sql_state": "08006" if error_type == "connection_timeout" else "42P01",
                        "driver_version": "psycopg2 2.9.3",
                        "event_type": "technical_error_details"
                    }}
                )
                
                # Record response time
                elapsed = time.time() - start_time
                response_time_histogram.record(elapsed, {"endpoint": "api_data", "method": "GET", "status": "error"})
                
                return jsonify({
                    "error": "Failed to process data",
                    "error_type": error_type, 
                    "error_message": error_message,
                    "request_id": g.request_id
                }), 500
    
    # Generate sample data
    items = []
    for i in range(random.randint(5, 15)):
        creation_time = datetime.datetime.utcnow() - datetime.timedelta(days=random.randint(0, 30))
        items.append({
            "id": f"item-{i}-{random.randint(1000, 9999)}",
            "value": random.randint(1, 100),
            "name": f"Sample Item {i}",
            "category": random.choice(["electronics", "books", "clothing", "food"]),
            "created_at": creation_time.isoformat() + "Z",
            "status": random.choice(["pending", "processed", "shipped", "delivered"])
        })
    
    data = {
        "items": items,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "request_id": g.request_id,
        "count": len(items),
        "page": 1,
        "total_pages": random.randint(1, 5)
    }
    
    # Log a summary of the data being returned
    logger.info(
        f"Returning {len(items)} data items",
        extra={"extra_fields": {
            "request_id": g.request_id,
            "items_count": len(items),
            "categories": list(set(item["category"] for item in items)),
            "event_type": "data_returned"
        }}
    )
    
    # Record response time
    elapsed = time.time() - start_time
    response_time_histogram.record(elapsed, {"endpoint": "api_data", "method": "GET", "status": "success"})
    
    logger.debug(
        "Successfully processed data endpoint request",
        extra={"extra_fields": {
            "request_id": g.request_id,
            "processing_time": elapsed,
            "event_type": "processing_completed"
        }}
    )
    
    return jsonify(data)

@app.route("/health")
def health():
    # Generate some system health metrics
    system_stats = {
        "cpu_load": random.uniform(0.1, 0.7),
        "memory_usage_pct": random.uniform(20, 70),
        "disk_usage_pct": random.uniform(30, 80),
        "uptime_seconds": random.randint(3600, 2592000),  # 1 hour to 30 days
        "active_connections": random.randint(1, 50)
    }
    
    logger.info(
        "Health check executed",
        extra={"extra_fields": {
            "request_id": g.request_id,
            "system_stats": system_stats,
            "event_type": "health_check"
        }}
    )
    
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "version": "1.0.0",
        "system_stats": system_stats
    })

@app.route("/logs/sample")
def log_sample():
    """An endpoint that generates sample logs at different levels"""
    logger.debug(
        "This is a DEBUG level message with detailed diagnostic information",
        extra={"extra_fields": {
            "request_id": g.request_id,
            "debug_info": {
                "memory_usage": random.randint(100, 500),
                "thread_count": random.randint(5, 20),
                "cache_size": random.randint(1000, 5000)
            },
            "event_type": "sample_debug"
        }}
    )
    
    logger.info(
        "This is an INFO level message about normal operation",
        extra={"extra_fields": {
            "request_id": g.request_id,
            "user_id": f"user-{random.randint(1000, 9999)}",
            "action": "sample_info_log",
            "event_type": "sample_info"
        }}
    )
    
    logger.warning(
        "This is a WARNING level message about something unusual",
        extra={"extra_fields": {
            "request_id": g.request_id,
            "warning_type": "resource_warning",
            "resource_usage": random.uniform(0.8, 0.9),
            "threshold": 0.85,
            "event_type": "sample_warning"
        }}
    )
    
    logger.error(
        "This is an ERROR level message about something that failed",
        extra={"extra_fields": {
            "request_id": g.request_id,
            "error_code": random.randint(400, 599),
            "component": "sample_component",
            "operation": "sample_operation",
            "event_type": "sample_error"
        }}
    )
    
    try:
        # Simulate an exception
        division_by_zero = 1 / 0
    except Exception as e:
        logger.critical(
            "This is a CRITICAL level message with exception information",
            exc_info=True,
            extra={"extra_fields": {
                "request_id": g.request_id,
                "critical_code": "SYSTEM_FAILURE",
                "impact": "high",
                "event_type": "sample_critical"
            }}
        )
    
    return jsonify({
        "message": "Sample logs generated at all levels",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "request_id": g.request_id
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    
    logger.info(
        f"Starting otel-demo-app on port {port}",
        extra={"extra_fields": {
            "port": port,
            "environment": os.getenv("DEPLOYMENT_ENVIRONMENT", "production"),
            "python_version": platform.python_version(),
            "event_type": "application_startup"
        }}
    )
    
    app.run(host="0.0.0.0", port=port) 