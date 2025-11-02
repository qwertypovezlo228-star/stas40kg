import os
import requests
import json
import logging
import aiohttp
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Union
from config import SUPABASE_URL, SUPABASE_KEY, SUPABASE_SERVICE_KEY
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('database_operations.log')
    ]
)

logger = logging.getLogger('database_operations')
# Enable debug logging for aiohttp if needed
logging.getLogger('aiohttp').setLevel(logging.WARNING)

# Headers for Supabase REST API - using service key for all operations to bypass RLS
HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY or SUPABASE_KEY or '',
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY or SUPABASE_KEY or ''}",
    "Content-Type": "application/json"
}

# Admin headers with service role for admin operations
ADMIN_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY or SUPABASE_KEY or '',
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY or SUPABASE_KEY or ''}",
    "Content-Type": "application/json"
}

# Constants for plan types
PLAN_30 = '30'
PLAN_500 = '500'

def format_username(username: str) -> str:
    """
    Ensure username always starts with @ for database storage
    
    Args:
        username: Raw username from Telegram
        
    Returns:
        Formatted username with @ prefix
    """
    if not username:
        return None
    
    username = username.strip()
    if not username:
        return None
        
    # Add @ prefix if not present
    return f"@{username}" if not username.startswith('@') else username

async def get_premium_users() -> List[Dict[str, Any]]:
    """
    Fetch all users who purchased the premium ($500) plan
    
    Returns:
        List[Dict]: List of premium users with their details
    """
    logger.info("Fetching premium users who purchased the $500 plan")
    
    try:
        # First, get all successful payments for the $500 plan
        payments_url = f"{SUPABASE_URL}/rest/v1/payments"
        params = {
            "select": "user_id,email,payment_id,created_at,metadata",
            "amount": "eq.500",
            "status": "eq.completed"
        }
        
        # Make the request
        async with aiohttp.ClientSession() as session:
            async with session.get(
                payments_url,
                headers=ADMIN_HEADERS,
                params=params
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Error fetching premium users: {response.status} - {error_text}")
                    return []
                    
                payments = await response.json()
                
                if not payments:
                    logger.info("No premium users found")
                    return []
                
                # Get unique user IDs from payments
                user_ids = list({payment['user_id'] for payment in payments if payment.get('user_id')})
                
                if not user_ids:
                    logger.info("No user IDs found in premium payments")
                    return []
                
                # Fetch user details for these users
                users_url = f"{SUPABASE_URL}/rest/v1/users"
                user_params = {
                    "select": "id,username,first_name,last_name,email,created_at,plan,payment_status",
                    "id": f"in.({','.join(map(str, user_ids))})"
                }
                
                async with session.get(
                    users_url,
                    headers=ADMIN_HEADERS,
                    params=user_params
                ) as user_response:
                    if user_response.status != 200:
                        error_text = await user_response.text()
                        logger.error(f"Error fetching user details: {user_response.status} - {error_text}")
                        return []
                        
                    users = await user_response.json()
                    
                    # Create a mapping of user_id to payment details
                    payment_map = {
                        str(payment['user_id']): payment 
                        for payment in payments 
                        if payment.get('user_id')
                    }
                    
                    # Combine user and payment data
                    result = []
                    for user in users:
                        user_id = str(user['id'])
                        payment_data = payment_map.get(user_id, {})
                        
                        result.append({
                            'user_id': user_id,
                            'username': user.get('username', 'N/A'),
                            'first_name': user.get('first_name', ''),
                            'last_name': user.get('last_name', ''),
                            'email': user.get('email', payment_data.get('email', 'N/A')),
                            'plan': user.get('plan', 'N/A'),
                            'payment_status': user.get('payment_status', 'N/A'),
                            'payment_date': payment_data.get('created_at', 'N/A'),
                            'payment_id': payment_data.get('payment_id', 'N/A')
                        })
                    
                    logger.info(f"Found {len(result)} premium users")
                    return result
                    
    except Exception as e:
        logger.error(f"Error in get_premium_users: {str(e)}", exc_info=True)
        return []

def _make_request(method: str, endpoint: str, headers: dict = None, data: dict = None) -> Optional[dict]:
    """
    Helper function to make HTTP requests to Supabase with detailed logging
    
    Args:
        method: HTTP method (GET, POST, PATCH, etc.)
        endpoint: API endpoint (e.g., 'payments', 'users')
        headers: Request headers
        data: Request payload or query parameters
        
    Returns:
        dict: JSON response if successful, None otherwise
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        error_msg = "Supabase configuration is missing. Check SUPABASE_URL and SUPABASE_KEY environment variables."
        logger.critical(error_msg)
        return None
    
    headers = headers or HEADERS
    url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
    
    # Log request details
    request_id = f"req_{int(datetime.utcnow().timestamp())}"
    logger.info(f"[{request_id}] Starting {method} request to {endpoint}")
    logger.debug(f"[{request_id}] URL: {url}")
    logger.debug(f"[{request_id}] Headers: {json.dumps(headers, default=str, indent=2)}")
    if data and method.upper() != 'GET':
        logger.debug(f"[{request_id}] Payload: {json.dumps(data, default=str, indent=2)}")
    
    try:
        start_time = datetime.utcnow()
        
        # Make the request
        if method.upper() == 'GET':
            logger.debug(f"[{request_id}] Sending GET with params: {data}")
            response = requests.get(url, headers=headers, params=data, timeout=10)
        elif method.upper() == 'POST':
            logger.debug(f"[{request_id}] Sending POST with data")
            response = requests.post(url, headers=headers, json=data, timeout=10)
        elif method.upper() == 'PATCH':
            logger.debug(f"[{request_id}] Sending PATCH with data")
            response = requests.patch(url, headers=headers, json=data, timeout=10)
        else:
            error_msg = f"Unsupported HTTP method: {method}"
            logger.error(f"[{request_id}] {error_msg}")
            return None
        
        # Calculate request duration
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        # Log response
        logger.info(f"[{request_id}] {method} {endpoint} -> {response.status_code} ({duration:.2f}s)")
        
        try:
            response_json = response.json() if response.text else {}
            logger.debug(f"[{request_id}] Response: {json.dumps(response_json, default=str, indent=2)}")
            return response_json
        except json.JSONDecodeError:
            logger.warning(f"[{request_id}] Non-JSON response received: {response.text[:500]}")
            return {}
            
    except requests.exceptions.Timeout:
        error_msg = f"Request to {endpoint} timed out after 10 seconds"
        logger.error(f"[{request_id}] {error_msg}")
        return None
        
    except requests.exceptions.RequestException as e:
        error_msg = f"Error making {method} request to {endpoint}: {str(e)}"
        logger.error(f"[{request_id}] {error_msg}", exc_info=True)
        
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_content = e.response.json()
                logger.error(f"[{request_id}] Error details: {json.dumps(error_content, indent=2)}")
            except:
                error_text = e.response.text[:1000]  # Limit log size
                logger.error(f"[{request_id}] Error response: {error_text}")
        
        return None

# --- USERS ---
async def add_or_update_user(user_id, username=None, first_name=None, last_name=None, 
                          email=None, plan=None, payment_status=None):
    log_prefix = f"[User {user_id}]"
    logger.info(f"{log_prefix} Starting user update/create operation")
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        error_msg = "Supabase configuration is missing"
        logger.error(f"{log_prefix} {error_msg}")
        return None
        
    now = datetime.utcnow().isoformat()
    
    # Check if user is admin
    from config import is_admin
    admin_status = is_admin(int(user_id))
    logger.debug(f"{log_prefix} Current timestamp: {now}")
    
    try:
        # Log the input parameters (excluding sensitive data)
        logger.debug(f"{log_prefix} Input parameters - username: {username}, "
                   f"first_name: {first_name}, last_name: {last_name}, "
                   f"email: {'[REDACTED]' if email else 'None'}, "
                   f"plan: {plan}, payment_status: {payment_status}")
        
        # Check if user exists
        url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}"
        logger.info(f"{log_prefix} Checking if user exists: {url}")
        
        async with aiohttp.ClientSession() as session:
            start_time = datetime.utcnow()
            try:
                async with session.get(url, headers=ADMIN_HEADERS, timeout=10) as response:
                    duration = (datetime.utcnow() - start_time).total_seconds()
                    logger.info(f"{log_prefix} User check completed in {duration:.2f}s - Status: {response.status}")
                    
                    if response.status == 200:
                        user_data = await response.json()
                        user_exists = bool(user_data)
                        logger.debug(f"{log_prefix} User exists: {user_exists}, Data: {json.dumps(user_data, default=str)}")
                    else:
                        error_text = await response.text()
                        logger.error(f"{log_prefix} Error checking user existence. Status: {response.status}, Response: {error_text}")
                        return None
            except asyncio.TimeoutError:
                logger.error(f"{log_prefix} Timeout while checking if user exists")
                return None
            except Exception as e:
                logger.error(f"{log_prefix} Exception while checking user existence: {str(e)}", exc_info=True)
                return None
        
        async with aiohttp.ClientSession() as session:
            if user_exists:
                # Update existing user
                patch_url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}"
                data = {"last_activity": now}
                
                # Only update fields that are provided and not None
                update_fields = []
                if username is not None: 
                    data["username"] = format_username(username)
                    update_fields.append("username")
                if first_name is not None: 
                    data["first_name"] = first_name
                    update_fields.append("first_name")
                if last_name is not None: 
                    data["last_name"] = last_name
                    update_fields.append("last_name")
                if email is not None: 
                    data["email"] = email
                    update_fields.append("email")
                if plan is not None: 
                    data["plan"] = plan
                    update_fields.append("plan")
                if payment_status is not None: 
                    data["payment_status"] = payment_status
                    update_fields.append("payment_status")
                    # Check and update admin status when payment is processed
                    data["is_admin"] = admin_status
                    update_fields.append("is_admin")
                
                logger.info(f"{log_prefix} Updating user with fields: {', '.join(update_fields) if update_fields else 'last_activity only'}")
                logger.debug(f"{log_prefix} Update data: {json.dumps(data, default=str)}")
                
                try:
                    start_time = datetime.utcnow()
                    async with session.patch(
                        patch_url, 
                        headers=ADMIN_HEADERS, 
                        json=data,
                        timeout=10
                    ) as update_response:
                        duration = (datetime.utcnow() - start_time).total_seconds()
                        logger.info(f"{log_prefix} User update completed in {duration:.2f}s - Status: {update_response.status}")
                        
                        if update_response.status != 204:
                            error_text = await update_response.text()
                            logger.error(f"{log_prefix} Error updating user. Status: {update_response.status}, Response: {error_text}")
                            return None
                            
                        logger.info(f"{log_prefix} User updated successfully")
                        return data
                        
                except asyncio.TimeoutError:
                    logger.error(f"{log_prefix} Timeout while updating user")
                    return None
                    
            else:
                # Insert new user
                data = {
                    "user_id": user_id,
                    "username": format_username(username),
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": email,
                    "plan": plan,
                    "payment_status": payment_status or "unpaid",
                    "first_seen": now,
                    "last_activity": now,
                    "is_admin": admin_status
                }
                
                logger.info(f"{log_prefix} Creating new user")
                logger.debug(f"{log_prefix} User data: {json.dumps(data, default=str)}")
                
                try:
                    start_time = datetime.utcnow()
                    headers = dict(ADMIN_HEADERS)
                    headers["Prefer"] = "return=representation"

                    async with session.post(
                        f"{SUPABASE_URL}/rest/v1/users",
                        headers=headers,
                        json=data,
                        timeout=10
                    ) as create_response:
                        duration = (datetime.utcnow() - start_time).total_seconds()
                        logger.info(f"{log_prefix} User creation completed in {duration:.2f}s - Status: {create_response.status}")
                        
                        if create_response.status != 201:
                            error_text = await create_response.text()
                            logger.error(f"{log_prefix} Error creating user. Status: {create_response.status}, Response: {error_text}")
                            return None
                            
                        try:
                            try:
                                response_data = await create_response.json()

                                # 🔽 Исправление: если вернулся список, достаём первый элемент
                                if isinstance(response_data, list):
                                    if response_data:
                                        response_data = response_data[0]
                                    else:
                                        response_data = {}

                                logger.info(f"{log_prefix} User created successfully with ID: {response_data.get('id')}")
                                logger.debug(f"{log_prefix} Created user data: {json.dumps(response_data, default=str)}")
                                return response_data
                            except aiohttp.ContentTypeError:
                                logger.warning(f"{log_prefix} Response not JSON. Skipping parsing.")
                                response_data = {"user_id": user_id}  # или просто return data
                            logger.info(f"{log_prefix} User created successfully with ID: {response_data.get('id')}")
                            logger.debug(f"{log_prefix} Created user data: {json.dumps(response_data, default=str)}")
                            return response_data
                        except Exception as json_error:
                            logger.error(f"{log_prefix} Error parsing user creation response: {str(json_error)}")
                            return None
                            
                except asyncio.TimeoutError:
                    logger.error(f"{log_prefix} Timeout while creating user")
                    return None
                
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error in add_or_update_user: {str(e)}", exc_info=True)
        return None
    finally:
        logger.info(f"{log_prefix} User operation completed")

def get_recent_users(limit=10):
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error(f"Supabase config missing")
        return []
    url = f"{SUPABASE_URL}/rest/v1/users?order=first_seen.desc&limit={limit}"
    r = requests.get(url, headers=HEADERS)
    if not r.ok:
        return []
    users = r.json()
    result = []
    for user in users:
        result.append({
            'id': user['user_id'],
            'username': user.get('username'),
            'first_name': user.get('first_name'),
            'last_name': user.get('last_name'),
            'created_at': user.get('first_seen', '')
        })
    return result

# --- BUTTON CLICKS ---
def log_button_click(user_id, button_type, button_data=None):
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error(f"Supabase config missing")
        return
    data = {
        "user_id": user_id,
        "button_type": button_type,
        "button_data": str(button_data) if button_data else None,
        "timestamp": datetime.utcnow().isoformat()
    }
    requests.post(f"{SUPABASE_URL}/rest/v1/button_clicks", headers=HEADERS, json=data)

# --- PAYMENTS ---
async def log_payment(
    user_id: Union[str, int],
    email: str,
    amount: float,
    status: str = 'completed',
    payment_method: str = 'stripe',
    payment_id: str = None,
    metadata: dict = None,
    currency: str = 'USD',
    telegram_user_id: Union[str, int] = None,
    telegram_username: str = None
) -> Optional[dict]:
    """
    Log a payment in the payments table with comprehensive logging and Telegram info.
    """
    log_prefix = f"[Payment {payment_id or 'new'}]"
    logger.info(f"{log_prefix} Starting payment logging for user {user_id}")

    if not SUPABASE_URL or not SUPABASE_KEY:
        error_msg = "Supabase configuration is missing"
        logger.error(f"{log_prefix} {error_msg}")
        return None

    # Generate payment ID if not provided
    if not payment_id:
        payment_id = f"pmt_{int(datetime.utcnow().timestamp())}"
        logger.info(f"{log_prefix} Generated payment ID: {payment_id}")

    # Prepare payment data with properly formatted username and test mode flag
    raw_username = telegram_username or (metadata.get('username') if metadata else None)
    formatted_username = format_username(raw_username)
    
    # Import test mode checker
    from config import is_test_mode
    
    payment_data = {
        'telegram_user_id': str(telegram_user_id or user_id),
        'username': formatted_username,  # Changed from 'telegram_username' to 'username'
        'amount': float(amount),
        'currency': currency.upper(),
        'status': status.lower(),
        'payment_method': payment_method.lower(),
        'payment_id': payment_id,
        'metadata': json.dumps(metadata) if metadata else None,
        'email': email,
        'is_test_mode': is_test_mode(),  # Add test mode flag
        'created_at': datetime.utcnow().isoformat()
    }

    test_mode_flag = is_test_mode()
    logger.info(f"{log_prefix} Prepared payment data (test_mode: {test_mode_flag})")
    logger.debug(f"{log_prefix} Payment details: {json.dumps(payment_data, default=str, indent=2)}")

    try:
        logger.info(f"{log_prefix} Creating aiohttp session")
        start_time = datetime.utcnow()

        async with aiohttp.ClientSession() as session:
            logger.info(f"{log_prefix} Sending payment data to Supabase")

            try:
                headers = dict(ADMIN_HEADERS)
                headers["Prefer"] = "return=representation"

                async with session.post(
                    f"{SUPABASE_URL}/rest/v1/payments",
                    headers=headers,
                    json=payment_data,
                    timeout=10
                ) as response:
                    duration = (datetime.utcnow() - start_time).total_seconds()
                    logger.info(f"{log_prefix} Supabase response received in {duration:.2f}s - Status: {response.status}")

                    response_text = await response.text()
                    logger.debug(f"{log_prefix} Raw response: {response_text}")

                    if response.status >= 400:
                        error_msg = f"Failed to log payment. Status: {response.status}, Response: {response_text}"
                        logger.error(f"{log_prefix} {error_msg}")
                        return None

                    try:
                        response_data = await response.json() if response_text else {}
                        
                        # Handle both array and object responses from Supabase
                        if isinstance(response_data, list):
                            payment_record = response_data[0] if response_data else {}
                            record_id = payment_record.get('id') if payment_record else 'unknown'
                        else:
                            payment_record = response_data
                            record_id = response_data.get('id', 'unknown')
                            
                        logger.info(f"{log_prefix} Payment logged successfully. ID: {record_id}")

                        # Log user action for analytics
                        try:
                            log_user_action(
                                user_id=user_id,
                                action='payment_processed',
                                metadata={
                                    'payment_id': payment_id,
                                    'amount': amount,
                                    'currency': currency,
                                    'status': status,
                                    'payment_method': payment_method,
                                    'email': email,
                                    **(metadata or {})
                                }
                            )
                            logger.info(f"{log_prefix} User action logged successfully")
                        except Exception as log_error:
                            logger.error(f"{log_prefix} Failed to log user action: {str(log_error)}", exc_info=True)

                        return payment_record

                    except json.JSONDecodeError:
                        error_msg = f"Failed to decode JSON response: {response_text}"
                        logger.error(f"{log_prefix} {error_msg}")
                        return None

            except asyncio.TimeoutError:
                error_msg = "Request to Supabase timed out after 10 seconds"
                logger.error(f"{log_prefix} {error_msg}")
                return None

            except aiohttp.ClientError as ce:
                error_msg = f"HTTP client error: {str(ce)}"
                logger.error(f"{log_prefix} {error_msg}", exc_info=True)
                return None

    except Exception as e:
        error_msg = f"Unexpected error in log_payment: {str(e)}"
        logger.error(f"{log_prefix} {error_msg}", exc_info=True)
        return None
    finally:
        logger.info(f"{log_prefix} Payment logging process completed")


def get_payment_stats(days: int = 30):
    """
    Get comprehensive payment statistics for admin panel
    
    Args:
        days: Number of days to look back for statistics
        
    Returns:
        Dict with payment statistics including revenue, counts, and trends
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("Supabase config missing")
        return {}
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    try:
        # Get payment summary
        summary_url = f"""
        {SUPABASE_URL}/rest/v1/rpc/get_payment_summary
        """.strip()
        
        summary_params = {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat()
        }
        
        summary_resp = requests.post(
            summary_url,
            headers=ADMIN_HEADERS,
            json=summary_params
        )
        summary_resp.raise_for_status()
        
        # Get monthly revenue trend
        trend_url = f"""
        {SUPABASE_URL}/rest/v1/rpc/get_monthly_revenue
        """.strip()
        
        trend_resp = requests.post(
            trend_url,
            headers=ADMIN_HEADERS,
            json={}
        )
        trend_resp.raise_for_status()
        
        # Get payment methods distribution
        methods_url = f"""
        {SUPABASE_URL}/rest/v1/rpc/get_payment_methods_distribution
        """.strip()
        
        methods_resp = requests.post(
            methods_url,
            headers=ADMIN_HEADERS,
            json={}
        )
        methods_resp.raise_for_status()
        
        return {
            'summary': summary_resp.json() if summary_resp.text else {},
            'trend': trend_resp.json() if trend_resp.text else [],
            'payment_methods': methods_resp.json() if methods_resp.text else {}
        }
        
    except Exception as e:
        logger.error(f"Error getting payment stats: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response: {e.response.text}")
        return {}

def get_payments_by_user(user_id: Union[str, int], limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get payment history for a specific user
    
    Args:
        user_id: Telegram user ID
        limit: Maximum number of payments to return
        
    Returns:
        List of payment records
    """
    response = _make_request(
        'GET', 
        f'payments?customer_telegram_id=eq.{user_id}&order=paid_at.desc&limit={limit}'
    )
    
    if not response or not isinstance(response, list):
        return []
    
    return response

# --- USER JOURNEY ---
def log_user_journey(user_id, action, details=None, session_id=None):
    """Legacy function, use log_user_action for new code"""
    log_user_action(user_id, action, details=details, session_id=session_id)

def log_user_action(user_id, action, details=None, session_id=None, action_type='user_action', metadata=None):
    """
    Log a user action to the database for analytics and tracking.
    
    Args:
        user_id: Telegram user ID
        action: String describing the action (e.g., 'button_click', 'plan_viewed')
        details: Optional dictionary with additional details about the action (deprecated, use metadata)
        session_id: Optional session ID to group related actions
        action_type: Type of action (e.g., 'button_click', 'page_view', 'system')
        metadata: Additional metadata as a dictionary
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("Supabase config missing")
        return
        
    try:
        # Get username from database if available (should already be formatted with @)
        username_with_at = None
        try:
            user_url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}&select=username"
            user_resp = requests.get(user_url, headers=HEADERS)
            if user_resp.ok:
                user_data = user_resp.json()
                if user_data and user_data[0].get('username'):
                    # Username should already be formatted with @ from database
                    username_with_at = user_data[0]['username']
        except Exception:
            pass
            
        data = {
            "user_id": user_id,
            "username": username_with_at,
            "action": action,
            "action_type": action_type,
            "session_id": session_id,
            "metadata": metadata if metadata else {},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Log to database
        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/user_actions", 
            headers=HEADERS, 
            json=data
        )
        
        if not response.ok:
            logger.error(f"Failed to log user action: {response.status_code} - {response.text}")
            
    except Exception as e:
        logger.error(f"Error logging user action: {str(e)}", exc_info=True)

def get_user_actions(user_id=None, action_type=None, limit=100, offset=0):
    """
    Retrieve user actions from the database
    
    Args:
        user_id: Optional filter by user ID
        action_type: Optional filter by action type
        limit: Maximum number of results to return
        offset: Offset for pagination
        
    Returns:
        List of action records or empty list on error
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("Supabase config missing")
        return []
        
    try:
        url = f"{SUPABASE_URL}/rest/v1/user_actions?select=*&order=timestamp.desc"
        
        # Add filters if provided
        if user_id:
            url += f"&user_id=eq.{user_id}"
        if action_type:
            url += f"&action_type=eq.{action_type}"
            
        # Add pagination
        url += f"&limit={limit}&offset={offset}"
        
        response = requests.get(url, headers=HEADERS)
        
        if response.ok:
            return response.json()
        else:
            logger.error(f"Failed to get user actions: {response.status_code} - {response.text}")
            return []
            
    except Exception as e:
        logger.error(f"Error getting user actions: {str(e)}", exc_info=True)
        return []

# --- PAYMENT STATUS UPDATE ---
def update_payment_status(stripe_session_id, status):
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error(f"Supabase config missing")
        return
    patch_url = f"{SUPABASE_URL}/rest/v1/payment_attempts?stripe_session_id=eq.{stripe_session_id}"
    data = {"status": status, "timestamp": datetime.utcnow().isoformat()}
    if status == 'completed':
        data['completed_at'] = datetime.utcnow().isoformat()
    elif status == 'failed':
        data['failed_at'] = datetime.utcnow().isoformat()
    requests.patch(patch_url, headers=HEADERS, json=data)

# --- ADMIN PANEL STATS ---

def get_time_based_stats(time_period: str = '24h') -> Dict[str, Any]:
    """
    Get statistics for a specific time period
    
    Args:
        time_period: Time period to get stats for ('1h', '24h', '7d', '30d')
        
    Returns:
        Dict with payment and user statistics for the specified period
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("Supabase configuration is missing")
        return {}
    
    try:
        # Calculate time range
        now = datetime.utcnow()
        if time_period == '1h':
            time_ago = now - timedelta(hours=1)
        elif time_period == '24h':
            time_ago = now - timedelta(days=1)
        elif time_period == '7d':
            time_ago = now - timedelta(days=7)
        elif time_period == '30d':
            time_ago = now - timedelta(days=30)
        else:
            time_ago = now - timedelta(days=1)  # Default to 24h
            
        time_ago_iso = time_ago.isoformat()
        
        # Get payment statistics
        payments_url = f"""
            {SUPABASE_URL}/rest/v1/rpc/get_payment_summary
            ?start_date={time_ago_iso}
            &end_date={now.isoformat()}
        """.replace('\n', '').replace(' ', '')
        
        payments_resp = requests.get(payments_url, headers=ADMIN_HEADERS)
        payment_stats = payments_resp.json() if payments_resp.ok else {}
        
        # Get user actions for conversion funnel
        funnel_url = f"""
            {SUPABASE_URL}/rest/v1/user_actions
            ?select=action,count(*)
            &timestamp=gte.{time_ago_iso}
            &group=action
        """.replace('\n', '').replace(' ', '')
        
        funnel_resp = requests.get(funnel_url, headers=ADMIN_HEADERS)
        funnel_data = {}
        if funnel_resp.ok:
            for item in funnel_resp.json():
                funnel_data[item['action']] = item['count']
        
        # Get back button metrics (users who viewed plan but didn't pay)
        back_metrics = {
            'viewed_plan_30': 0,
            'viewed_plan_500': 0,
            'back_after_30': 0,
            'back_after_500': 0,
            'switched_plans': 0
        }
        
        return {
            'time_period': time_period,
            'payment_stats': payment_stats,
            'funnel_metrics': funnel_data,
            'conversion_metrics': back_metrics
        }
        
    except Exception as e:
        logger.error(f"Error getting time-based stats: {str(e)}")
        return {}

def get_conversion_funnel() -> Dict[str, Any]:
    """
    Get detailed conversion funnel metrics
    
    Returns:
        Dict with conversion funnel data
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("Supabase configuration is missing")
        return {}
    
    try:
        # Get funnel data for different time periods
        funnel_url = f"""
            {SUPABASE_URL}/rest/v1/rpc/get_conversion_funnel
        """.strip()
        
        funnel_resp = requests.post(funnel_url, headers=ADMIN_HEADERS, json={})
        
        if funnel_resp.ok:
            return funnel_resp.json()
            
        # Fallback to simple funnel if RPC fails
        return {
            'steps': [
                {'name': 'Started Bot', 'count': 0, 'conversion': 100},
                {'name': 'Viewed Plans', 'count': 0, 'conversion': 0},
                {'name': 'Started Checkout', 'count': 0, 'conversion': 0},
                {'name': 'Completed Payment', 'count': 0, 'conversion': 0},
                {'name': 'Activated Plan', 'count': 0, 'conversion': 0}
            ],
            'overall_conversion': 0
        }
        
    except Exception as e:
        logger.error(f"Error getting conversion funnel: {str(e)}")
        return {}

# --- ADMIN PANEL STATS ---
async def get_admin_dashboard_stats() -> Dict[str, Any]:
    """
    Get comprehensive statistics for the admin dashboard
    
    Returns:
        Dict containing various statistics including user counts, payment info, and recent actions
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("Supabase configuration is missing")
        return {
            'user_stats': {
                'total_users': 0,
                'new_users': {'7d': 0, '30d': 0},
                'active_users': {'1d': 0, '7d': 0, '30d': 0},
                'retention_rate': 0
            },
            'payment_stats': {
                'summary': {
                    'total_revenue': 0,
                    'successful_payments': 0,
                    'failed_payments': 0,
                    'avg_payment': 0,
                    'revenue_by_plan': {}
                },
                'recent_payments': []
            },
            'recent_actions': []
        }

    try:
        # Get total users
        users_url = f"{SUPABASE_URL}/rest/v1/users?select=user_id,first_seen,last_activity"
        users_response = requests.get(users_url, headers=HEADERS)
        users_response.raise_for_status()
        users = users_response.json()
        
        # Calculate user statistics
        now = datetime.utcnow()
        week_ago = (now - timedelta(days=7)).isoformat()
        month_ago = (now - timedelta(days=30)).isoformat()
        
        new_users_7d = sum(1 for u in users if 'first_seen' in u and u['first_seen'] >= week_ago)
        new_users_30d = sum(1 for u in users if 'first_seen' in u and u['first_seen'] >= month_ago)
        active_users_1d = sum(1 for u in users if 'last_activity' in u and u['last_activity'] >= (now - timedelta(days=1)).isoformat())
        active_users_7d = sum(1 for u in users if 'last_activity' in u and u['last_activity'] >= week_ago)
        active_users_30d = sum(1 for u in users if 'last_activity' in u and u['last_activity'] >= month_ago)
        
        # Get payment statistics
        payments_url = f"{SUPABASE_URL}/rest/v1/payments?select=status,amount,plan_id,created_at&order=created_at.desc&limit=100"
        payments_response = requests.get(payments_url, headers=HEADERS)
        payments_response.raise_for_status()
        payments = payments_response.json()
        
        # Calculate payment statistics
        successful_payments = [p for p in payments if p.get('status') == 'completed']
        failed_payments = [p for p in payments if p.get('status') == 'failed']
        total_revenue = sum(float(p.get('amount', 0) or 0) for p in successful_payments)
        avg_payment = total_revenue / len(successful_payments) if successful_payments else 0
        
        # Group revenue by plan
        revenue_by_plan = {}
        for p in successful_payments:
            plan_id = str(p.get('plan_id', 'other'))
            amount = float(p.get('amount', 0) or 0)
            if plan_id in revenue_by_plan:
                revenue_by_plan[plan_id]['revenue'] += amount
                revenue_by_plan[plan_id]['count'] += 1
            else:
                revenue_by_plan[plan_id] = {'revenue': amount, 'count': 1}
        
        # Get recent user actions
        actions_url = f"{SUPABASE_URL}/rest/v1/user_actions?select=*,user:users(username,first_name,last_name)&order=timestamp.desc&limit=10"
        actions_response = requests.get(actions_url, headers=HEADERS)
        recent_actions = actions_response.json() if actions_response.ok else []
        
        # Format recent payments
        recent_payments = [{
            'id': p.get('id'),
            'amount': p.get('amount'),
            'currency': p.get('currency', 'USD'),
            'status': p.get('status'),
            'created_at': p.get('created_at'),
            'user_id': p.get('user_id')
        } for p in payments[:5]]
        
        return {
            'user_stats': {
                'total_users': len(users),
                'new_users': {'7d': new_users_7d, '30d': new_users_30d},
                'active_users': {'1d': active_users_1d, '7d': active_users_7d, '30d': active_users_30d},
                'retention_rate': (active_users_30d / len(users) * 100) if users else 0
            },
            'payment_stats': {
                'summary': {
                    'total_revenue': round(total_revenue, 2),
                    'successful_payments': len(successful_payments),
                    'failed_payments': len(failed_payments),
                    'avg_payment': round(avg_payment, 2),
                    'revenue_by_plan': revenue_by_plan
                },
                'recent_payments': recent_payments
            },
            'recent_actions': recent_actions
        }
        
    except Exception as e:
        logger.error(f"Error getting admin dashboard stats: {str(e)}")
        # Return empty stats on error
        return {
            'user_stats': {
                'total_users': 0,
                'new_users': {'7d': 0, '30d': 0},
                'active_users': {'1d': 0, '7d': 0, '30d': 0},
                'retention_rate': 0
            },
            'payment_stats': {
                'summary': {
                    'total_revenue': 0,
                    'successful_payments': 0,
                    'failed_payments': 0,
                    'avg_payment': 0,
                    'revenue_by_plan': {}
                },
                'recent_payments': []
            },
            'recent_actions': []
        }
