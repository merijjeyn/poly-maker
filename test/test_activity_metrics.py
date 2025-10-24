"""
Simple test for activity metrics functionality without external dependencies
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from configuration import TCNF

def test_configuration_values():
    """Test that all new configuration values are accessible and have reasonable defaults"""
    print("Testing configuration values...")
    
    try:
        # Test that all new config values are accessible
        config_tests = [
            ("ACTIVITY_LOOKBACK_DAYS", TCNF.ACTIVITY_LOOKBACK_DAYS, int),
            ("DECAY_HALF_LIFE_HOURS", TCNF.DECAY_HALF_LIFE_HOURS, int),
            ("SPREAD_MULTIPLIER", TCNF.SPREAD_MULTIPLIER, float),
            ("MIN_TOTAL_VOLUME", TCNF.MIN_TOTAL_VOLUME, float),
            ("MIN_VOLUME_USD", TCNF.MIN_VOLUME_USD, float),
            ("MIN_DECAY_WEIGHTED_VOLUME", TCNF.MIN_DECAY_WEIGHTED_VOLUME, float),
            ("MIN_AVG_TRADES_PER_DAY", TCNF.MIN_AVG_TRADES_PER_DAY, float),
            ("MIN_UNIQUE_TRADERS", TCNF.MIN_UNIQUE_TRADERS, int),
        ]
        
        for name, value, expected_type in config_tests:
            assert isinstance(value, expected_type), f"{name} should be {expected_type.__name__}, got {type(value).__name__}"
            print(f"✓ {name}: {value} ({expected_type.__name__})")
        
        print("✓ Configuration test passed")
        return True
        
    except Exception:
        print("Configuration test failed")
        return False

def test_activity_metrics_imports():
    """Test that we can import the activity metrics module"""
    print("\nTesting activity metrics imports...")
    
    try:
        from data_updater.activity_metrics import (
            calculate_market_activity_metrics
        )
        
        print("✓ All activity metrics functions imported successfully")
        
        # Test that the main function exists and accepts the right parameters
        import inspect
        sig = inspect.signature(calculate_market_activity_metrics)
        params = list(sig.parameters.keys())
        expected_params = ['condition_id', 'best_bid', 'best_ask']
        
        assert params == expected_params, f"Expected parameters {expected_params}, got {params}"
        print("✓ Main function signature is correct")
        
        return True
        
    except Exception:
        print("Import test failed")
        return False

def test_market_filtering_logic():
    """Test filtering logic without external dependencies"""
    print("\nTesting market filtering logic...")
    
    try:
        import pandas as pd
        
        # Create test data
        test_data = pd.DataFrame([
            {
                'question': 'High Volume Market',
                'attractiveness_score': 10.0,
                'volatility_sum': 15.0,
                'best_bid': 0.45, 'best_ask': 0.55,
                'total_volume': 200.0,  # Above threshold
                'avg_trades_per_day': 5.0,  # Above threshold
                'unique_traders': 10  # Above threshold
            },
            {
                'question': 'Low Volume Market', 
                'attractiveness_score': 8.0,
                'volatility_sum': 12.0,
                'best_bid': 0.30, 'best_ask': 0.40,
                'total_volume': 50.0,  # Below threshold (100.0)
                'avg_trades_per_day': 0.5,  # Below threshold (1.0) 
                'unique_traders': 1  # Below threshold (2)
            }
        ])
        
        # Test filtering conditions
        volume_filter = test_data['total_volume'].fillna(0) >= TCNF.MIN_TOTAL_VOLUME
        trades_filter = test_data['avg_trades_per_day'].fillna(0) >= TCNF.MIN_AVG_TRADES_PER_DAY
        traders_filter = test_data['unique_traders'].fillna(0) >= TCNF.MIN_UNIQUE_TRADERS
        
        print(f"Volume filter results: {volume_filter.tolist()}")
        print(f"Trades filter results: {trades_filter.tolist()}")
        print(f"Traders filter results: {traders_filter.tolist()}")
        
        # Apply filters
        filtered_data = test_data[volume_filter & trades_filter & traders_filter]
        
        print(f"Original markets: {len(test_data)}")
        print(f"Filtered markets: {len(filtered_data)}")
        
        # Should only keep the high volume market
        assert len(filtered_data) == 1, f"Expected 1 market after filtering, got {len(filtered_data)}"
        assert filtered_data.iloc[0]['question'] == 'High Volume Market'
        
        print("✓ Filtering logic test passed")
        return True
        
    except Exception:
        print("Filtering logic test failed")
        return False

def main():
    """Run all tests"""
    print("=== Enhanced Market Selection Tests ===\n")
    
    tests = [
        ("Configuration Values", test_configuration_values),
        ("Activity Metrics Imports", test_activity_metrics_imports),
        ("Market Filtering Logic", test_market_filtering_logic),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"--- Running {test_name} ---")
        result = test_func()
        results.append((test_name, result))
    
    # Summary
    print("\n=== Test Summary ===")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{test_name}: {status}")
    
    print(f"\nTests passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 All tests passed! Enhanced market selection is ready.")
        print("\nNext steps:")
        print("1. Run: python update_markets.py")  
        print("2. Check the Google Sheets for new activity metrics columns")
        print("3. Adjust configuration values in configuration.py as needed")
    else:
        print("❌ Some tests failed. Please review the implementation.")
    
    return passed == total

if __name__ == "__main__":
    main()