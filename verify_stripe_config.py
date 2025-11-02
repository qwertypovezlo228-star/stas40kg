#!/usr/bin/env python3
"""
Stripe Configuration Verification Script for Updated Pricing (29$ and 490$)

This script helps verify that your Stripe configuration is properly set up
for the updated pricing structure.
"""

import os
from dotenv import load_dotenv

def main():
    # Load environment variables
    load_dotenv()
    
    print("🔍 Stripe Configuration Verification for Updated Pricing")
    print("=" * 60)
    print("💡 NOTE: Now using Price IDs from environment variables")
    print("   Plan '30' → 29$ pricing, Plan '500' → 490$ pricing")
    print()
    
    # Check mode configuration
    test_mode = os.getenv('STRIPE_IS_TEST_MODE_ON', 'False')
    one_dollar_mode = os.getenv('USE_ONE_DOLLAR_PRICES', 'False')
    
    print(f"Test Mode: {test_mode}")
    print(f"One Dollar Testing: {one_dollar_mode}")
    print()
    
    # Determine current configuration and required variables
    if test_mode == 'True':
        mode = "TEST MODE"
        required_vars = [
            'STRIPE_TEST_API_KEY',
            'STRIPE_TEST_WEBHOOK_SECRET',
            'PRICE_ID_TEST_29',
            'PRICE_ID_TEST_490'
        ]
    elif one_dollar_mode == 'True':
        mode = "LIVE MODE ($1 TESTING)"
        required_vars = [
            'STRIPE_LIVE_API_KEY',
            'STRIPE_LIVE_WEBHOOK_SECRET',
            'PRICE_ID_LIVE_1_DOLLAR_30',
            'PRICE_ID_LIVE_1_DOLLAR_500'
        ]
    else:
        mode = "LIVE MODE (REAL PRICES)"
        required_vars = [
            'STRIPE_LIVE_API_KEY',
            'STRIPE_LIVE_WEBHOOK_SECRET',
            'PRICE_ID_LIVE_30',
            'PRICE_ID_LIVE_500'
        ]
    
    print(f"Current Mode: {mode}")
    print()
    
    # Check required environment variables
    print("Required Environment Variables:")
    print("-" * 40)
    
    all_present = True
    for var in required_vars:
        value = os.getenv(var)
        if value:
            # Mask sensitive values
            if 'API_KEY' in var or 'SECRET' in var:
                display_value = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "***"
            else:
                display_value = value
            print(f"✅ {var}: {display_value}")
        else:
            print(f"❌ {var}: NOT SET")
            all_present = False
    
    print()
      # Check optional variables (for other modes)
    print("Other Environment Variables (for reference):")
    print("-" * 50)
    
    other_vars = [
        'PRICE_ID_TEST_29',
        'PRICE_ID_TEST_490', 
        'PRICE_ID_LIVE_30',
        'PRICE_ID_LIVE_500',
        'PRICE_ID_LIVE_1_DOLLAR_30',
        'PRICE_ID_LIVE_1_DOLLAR_500'
    ]
    
    for var in other_vars:
        if var not in required_vars:
            value = os.getenv(var)
            status = "✅ SET" if value else "⚪ NOT SET"
            print(f"{status} {var}")
    
    print()    # Summary
    if all_present:
        print("🎉 Configuration Status: READY")
        print(f"Your bot is configured for {mode}")
        print("You can now process payments with the updated pricing (29$ and 490$)")
    else:
        print("⚠️  Configuration Status: INCOMPLETE")
        print("Please set the missing environment variables before deploying.")
        print("See STRIPE_SETUP_INSTRUCTIONS.md for detailed setup instructions.")
    
    print()
    
    # Plan mapping reminder
    print("📋 Plan Mapping:")
    print("- Internal plan '30' → 29$ pricing")
    print("- Internal plan '500' → 490$ pricing")
    print("(Plan identifiers remain unchanged for system consistency)")

if __name__ == "__main__":
    main()
