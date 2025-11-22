import os
import logging
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry._logs import set_logger_provider

def setup_telemetry(service_name="poly-maker-bot", collector_endpoint="http://localhost:4317"):
    """
    Configures OpenTelemetry to send logs to the OTel Collector via OTLP/gRPC.
    """
    # 1. Configure Logging Provider
    logger_provider = LoggerProvider(
        resource=Resource.create({"service.name": service_name})
    )
    set_logger_provider(logger_provider)

    # 2. Configure OTLP Exporter (sends to Collector)
    exporter = OTLPLogExporter(endpoint=collector_endpoint, insecure=True)
    
    # 3. Add Processor
    processor = BatchLogRecordProcessor(exporter)
    logger_provider.add_log_record_processor(processor)
    
    # 4. Attach OTel handler to Python logging
    # This captures all standard logging.info/error calls
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    
    return logger_provider
