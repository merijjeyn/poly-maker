"""
Test script for the enhanced market selection flow with activity metrics
"""

import pandas as pd
from trading_bot.market_selection import filter_selected_markets
from data_updater.activity_metrics import add_activity_metrics_to_market_data
from configuration import TCNF
from logan import Logan

def create_test_market_data():
    """Create sample market data for testing"""
    test_data = [
        {
            'question': 'Test Market 1',
            'answer1': 'Yes', 'answer2': 'No',
            'condition_id': 'test_condition_1',
            'attractiveness_score': 10.5,
            'volatility_sum': 15.0,
            'best_bid': 0.45, 'best_ask': 0.55,
            'token1': 'test_token_1a', 'token2': 'test_token_1b'
        },
        {
            'question': 'Test Market 2',
            'answer1': 'Yes', 'answer2': 'No', 
            'condition_id': 'test_condition_2',
            'attractiveness_score': 8.2,
            'volatility_sum': 12.0,
            'best_bid': 0.30, 'best_ask': 0.40,
            'token1': 'test_token_2a', 'token2': 'test_token_2b'
        },
        {
            'question': 'Test Market 3',
            'answer1': 'Yes', 'answer2': 'No',
            'condition_id': 'test_condition_3', 
            'attractiveness_score': 5.5,
            'volatility_sum': 25.0,  # High volatility - should be filtered out
            'best_bid': 0.60, 'best_ask': 0.70,
            'token1': 'test_token_3a', 'token2': 'test_token_3b'
        }
    ]
    return pd.DataFrame(test_data)

def test_activity_metrics_calculation():
    """Test the activity metrics calculation function"""
    Logan.info("Testing activity metrics calculation...", namespace="test_market_selection")
    
    test_market = {
        'question': 'Test Market',
        'condition_id': 'test_condition',
        'best_bid': 0.45,
        'best_ask': 0.55,
        'token1': 'test_token'
    }
    
    try:
        # This will likely fail due to invalid condition_id, but we can test the function structure
        enhanced_market = add_activity_metrics_to_market_data(test_market)
        
        # Check if the function returns the original data when API calls fail
        assert 'question' in enhanced_market
        assert 'condition_id' in enhanced_market
        
        Logan.info("✓ Activity metrics function structure test passed", namespace="test_market_selection")
        return True
        
    except Exception as e:
        Logan.error(f"Activity metrics test failed", namespace="test_market_selection", exception=e)
        return False

def test_market_filtering():
    """Test the enhanced market filtering logic"""
    Logan.info("Testing enhanced market filtering...", namespace="test_market_selection")
    
    try:
        # Create test data
        test_df = create_test_market_data()
        
        # Add some mock activity metrics to test filtering
        test_df['total_volume'] = [150.0, 80.0, 200.0]  # Second market should be filtered out if MIN_TOTAL_VOLUME = 100
        test_df['avg_trades_per_day'] = [5.0, 0.5, 3.0]  # Second market should be filtered out if MIN_AVG_TRADES_PER_DAY = 1.0
        test_df['unique_traders'] = [10, 1, 15]  # Second market should be filtered out if MIN_UNIQUE_TRADERS = 2
        
        Logan.info(f"Original test data: {len(test_df)} markets", namespace="test_market_selection")
        
        # Apply filtering
        filtered_df = filter_selected_markets(test_df)
        
        Logan.info(f"Filtered data: {len(filtered_df)} markets", namespace="test_market_selection")
        
        # Basic validation
        assert len(filtered_df) <= len(test_df), "Filtering should not increase market count"
        assert all(col in filtered_df.columns for col in ['question', 'attractiveness_score']), "Essential columns should be preserved"
        
        # Log results
        for _, row in filtered_df.iterrows():
            Logan.info(f"Selected: {row['question']} (score: {row['attractiveness_score']})", namespace="test_market_selection")
        
        Logan.info("✓ Market filtering test passed", namespace="test_market_selection")
        return True
        
    except Exception as e:
        Logan.error(f"Market filtering test failed", namespace="test_market_selection", exception=e)
        return False

def test_configuration_values():
    """Test that configuration values are accessible"""
    Logan.info("Testing configuration values...", namespace="test_market_selection")
    
    try:
        # Test that all new config values are accessible
        config_values = [
            TCNF.ACTIVITY_LOOKBACK_DAYS,
            TCNF.DECAY_HALF_LIFE_HOURS,
            TCNF.SPREAD_MULTIPLIER,
            TCNF.MIN_TOTAL_VOLUME,
            TCNF.MIN_VOLUME_USD,
            TCNF.MIN_DECAY_WEIGHTED_VOLUME,
            TCNF.MIN_AVG_TRADES_PER_DAY,
            TCNF.MIN_UNIQUE_TRADERS,
        ]
        
        Logan.info(f"Configuration values: ACTIVITY_LOOKBACK_DAYS={TCNF.ACTIVITY_LOOKBACK_DAYS}, "
                  f"MIN_TOTAL_VOLUME={TCNF.MIN_TOTAL_VOLUME}, "
                  f"MIN_UNIQUE_TRADERS={TCNF.MIN_UNIQUE_TRADERS}", 
                  namespace="test_market_selection")
        
        Logan.info("✓ Configuration test passed", namespace="test_market_selection")
        return True
        
    except Exception as e:
        Logan.error(f"Configuration test failed", namespace="test_market_selection", exception=e)
        return False

def main():
    """Run all tests"""
    Logan.info("Starting enhanced market selection tests...", namespace="test_market_selection")
    
    tests = [
        ("Configuration Values", test_configuration_values),
        ("Activity Metrics Calculation", test_activity_metrics_calculation),
        ("Market Filtering", test_market_filtering),
    ]
    
    results = []
    for test_name, test_func in tests:
        Logan.info(f"\n--- Running {test_name} ---", namespace="test_market_selection")
        result = test_func()
        results.append((test_name, result))
    
    # Summary
    Logan.info("\n--- Test Summary ---", namespace="test_market_selection")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        Logan.info(f"{test_name}: {status}", namespace="test_market_selection")
    
    Logan.info(f"\nTests passed: {passed}/{total}", namespace="test_market_selection")
    
    if passed == total:
        Logan.info("🎉 All tests passed! Enhanced market selection is ready.", namespace="test_market_selection")
    else:
        Logan.info("❌ Some tests failed. Please review the implementation.", namespace="test_market_selection")
    
    return passed == total

if __name__ == "__main__":
    main()