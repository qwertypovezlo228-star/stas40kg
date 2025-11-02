import os
import stripe
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

# Load environment variables from .env file if it exists
load_dotenv()

# Telegram Bot Configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
WEBHOOK_URL = os.getenv('WEBHOOK_URL') or f"https://{os.getenv('HEROKU_APP_NAME')}.herokuapp.com"
""" ADMIN_ID = os.getenv('ADMIN_USER_ID', '') """
ADMIN_IDS = os.getenv('ADMIN_USER_IDS', '')

# Stripe Configuration
STRIPE_IS_TEST_MODE_ON = os.getenv('STRIPE_IS_TEST_MODE_ON')
USE_ONE_DOLLAR_PRICES = os.getenv('USE_ONE_DOLLAR_PRICES', 'False')

# Price ID configuration for different modes
if STRIPE_IS_TEST_MODE_ON == 'True':
    # Test mode - using test Price IDs
    STRIPE_API_KEY = os.getenv('STRIPE_TEST_API_KEY')
    STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_TEST_WEBHOOK_SECRET')
    PRICE_ID_30 = os.getenv('PRICE_ID_TEST_29')  # Test Price ID for 29$ plan
    PRICE_ID_500 = os.getenv('PRICE_ID_TEST_490')  # Test Price ID for 490$ plan
    stripe.api_key = STRIPE_API_KEY
    logger.info(f'Stripe test mode is chosen. Price IDs: 30=${PRICE_ID_30}, 500=${PRICE_ID_500}', exc_info=True)
else:
    # Live mode
    STRIPE_API_KEY = os.getenv('STRIPE_LIVE_API_KEY')
    STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_LIVE_WEBHOOK_SECRET')
    
    if USE_ONE_DOLLAR_PRICES == 'True':
        # Live mode with $1 prices for testing
        PRICE_ID_30 = os.getenv('PRICE_ID_LIVE_1_DOLLAR_30')  # $1 version of 29$ plan
        PRICE_ID_500 = os.getenv('PRICE_ID_LIVE_1_DOLLAR_500')  # $1 version of 490$ plan
        logger.info(f'✅ Stripe live mode with $1 prices is chosen. PRICE_ID_30={PRICE_ID_30}, PRICE_ID_500={PRICE_ID_500}', exc_info=True)
    else:
        # Live mode with real prices
        PRICE_ID_30 = os.getenv('PRICE_ID_LIVE_30')  # Live Price ID for 29$ plan  
        PRICE_ID_500 = os.getenv('PRICE_ID_LIVE_500')  # Live Price ID for 490$ plan
        logger.info(f'Stripe live mode with real prices is chosen. PRICE_ID_30={PRICE_ID_30}, PRICE_ID_500={PRICE_ID_500}', exc_info=True)
    
    stripe.api_key = STRIPE_API_KEY

# Supabase Configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_ANON_KEY')
SUPABASE_SERVICE_KEY = os.getenv('SUPABASE_SERVICE_ROLE')

# Other Configuration
JOIN_GROUP_LINK = os.getenv('JOIN_GROUP_LINK')
SUPPORT_LINK = os.getenv('ACCOUNT_OF_SUPPORT')
SUPABASE_POSTGRES_URL = os.getenv('SUPABASE_POSTGRES_URL')
HEROKU_APP_NAME = os.getenv('HEROKU_APP_NAME')
HEROKU_API_KEY = os.getenv('HEROKU_API_KEY')

# New Price IDs for live $1 testing (keeping old variable names for compatibility)
PRICE_ID_LIVE_1_DOLLAR_30 = os.getenv('PRICE_ID_LIVE_1_DOLLAR_30')
PRICE_ID_LIVE_1_DOLLAR_500 = os.getenv('PRICE_ID_LIVE_1_DOLLAR_500')




def get_admin_ids() -> set[int]:
    return {int(i.strip()) for i in ADMIN_IDS.split(',') if i.strip().isdigit()}

def is_admin(user_id: int) -> bool:
    return user_id in get_admin_ids()

def is_test_mode() -> bool:
    """
    Check if Stripe is currently in test mode
    
    Returns:
        bool: True if test mode is enabled, False for live mode
    """
    return STRIPE_IS_TEST_MODE_ON == 'True'

def is_using_one_dollar_prices() -> bool:
    """
    Check if live mode is using $1 prices for testing
    
    Returns:
        bool: True if using $1 prices in live mode, False for real prices
    """
    return USE_ONE_DOLLAR_PRICES == 'True'

def get_current_pricing_mode() -> str:
    """
    Get current pricing mode description
    
    Returns:
        str: Description of current pricing mode
    """
    if is_test_mode():
        return "Test mode (no real money)"
    elif is_using_one_dollar_prices():
        return "Live mode with $1 prices"
    else:
        return "Live mode with real prices"

def get_all_price_ids() -> dict:
    """
    Get all available price IDs
    
    Returns:
        dict: Dictionary with all price IDs
    """
    return {
        'test': {
            '30': os.getenv('PRICE_ID_TEST_29'),  # Test Price ID for 29$ plan
            '500': os.getenv('PRICE_ID_TEST_490')  # Test Price ID for 490$ plan
        },
        'live_real': {
            '30': os.getenv('PRICE_ID_LIVE_30'),  # Live Price ID for 29$ plan
            '500': os.getenv('PRICE_ID_LIVE_500')  # Live Price ID for 490$ plan
        },
        'live_one_dollar': {
            '30': os.getenv('PRICE_ID_LIVE_1_DOLLAR_30'),  # $1 version of 29$ plan
            '500': os.getenv('PRICE_ID_LIVE_1_DOLLAR_500')  # $1 version of 490$ plan
        },
        'current': {
            '30': PRICE_ID_30,
            '500': PRICE_ID_500
        }
    }

    """ "ADMIN_ID", """
__all__ = [
    # Telegram
    "TELEGRAM_TOKEN",
    "WEBHOOK_URL",
    "ADMIN_IDS",
    
    # Stripe
    "STRIPE_API_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "PRICE_ID_30",
    "PRICE_ID_500",
    "STRIPE_IS_TEST_MODE_ON",
    "USE_ONE_DOLLAR_PRICES",
    "PRICE_ID_LIVE_1_DOLLAR_30",
    "PRICE_ID_LIVE_1_DOLLAR_500",
    
    # Supabase
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_KEY",
    "SUPABASE_POSTGRES_URL",
    
    # Other
    "JOIN_GROUP_LINK",
    "SUPPORT_LINK",
    "HEROKU_APP_NAME",
    "HEROKU_API_KEY",
    
    # Functions
    "get_admin_ids",
    "is_admin",
    "is_test_mode",
    "is_using_one_dollar_prices",
    "get_current_pricing_mode",
    "get_all_price_ids",
]