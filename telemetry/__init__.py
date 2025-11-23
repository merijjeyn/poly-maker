import logging
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import set_tracer_provider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.metrics import set_meter_provider
from logan import Logan

def setup_telemetry(service_name="poly-maker-bot", collector_endpoint="http://localhost:4317", nologan=False):
    """
    Configures OpenTelemetry to send logs, traces, and metrics to the OTel Collector via OTLP/gRPC.
    """
    resource = Resource.create({"service.name": service_name})
    
    # 1. Configure Logging Provider
    logger_provider = LoggerProvider(resource=resource)
    set_logger_provider(logger_provider)

    # 2. Configure OTLP Log Exporter (sends to Collector)
    log_exporter = OTLPLogExporter(endpoint=collector_endpoint, insecure=True)
    
    # 3. Add Log Processor
    log_processor = BatchLogRecordProcessor(log_exporter)
    logger_provider.add_log_record_processor(log_processor)
    
    # 4. Attach OTel handler to Python logging
    # This captures all standard logging.info/error calls
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
    Logan.init(logging_handler=handler, no_server=nologan)
    
    # 5. Configure Tracing Provider
    tracer_provider = TracerProvider(resource=resource)
    set_tracer_provider(tracer_provider)
    
    # 6. Configure OTLP Span Exporter
    span_exporter = OTLPSpanExporter(endpoint=collector_endpoint, insecure=True)
    span_processor = BatchSpanProcessor(span_exporter)
    tracer_provider.add_span_processor(span_processor)
    
    # 7. Configure Metrics Provider
    metric_exporter = OTLPMetricExporter(endpoint=collector_endpoint, insecure=True)
    metric_reader = PeriodicExportingMetricReader(metric_exporter)
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    set_meter_provider(meter_provider)
    
    return logger_provider, tracer_provider, meter_provider
