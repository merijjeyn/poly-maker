import logging
import os
import sys
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telemetry import setup_telemetry


def test_telemetry_integration():
    print("🧪 Testing Telemetry Integration (OTLP)...")
    
    # Mock the OTLP Exporter
    with patch('telemetry.OTLPLogExporter') as MockExporter:
        mock_exporter_instance = MagicMock()
        MockExporter.return_value = mock_exporter_instance
        
        # Setup telemetry
        provider = setup_telemetry(service_name="test-bot-otlp")
        
        # Test OTel logger directly
        logger = logging.getLogger("poly-maker-bot")
        logger.info("Test log message to OTel Collector")
        
        # Force flush
        provider.shutdown()
        
        # Verify exporter was initialized with correct endpoint
        MockExporter.assert_called_with(endpoint="http://localhost:4317", insecure=True)
        print("✅ OTLP Exporter initialized with correct endpoint.")
        
        # Verify export was called (OTLP exporter uses export method)
        # Note: The BatchLogRecordProcessor calls export on the exporter
        if mock_exporter_instance.export.called:
            print("✅ OTLP Exporter received export call.")
            print(f"   Call args: {mock_exporter_instance.export.call_args}")
        else:
            print("❌ OTLP Exporter did NOT receive export call.")

if __name__ == "__main__":
    test_telemetry_integration()
