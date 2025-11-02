import os
from flask import request, jsonify
from config import *
from datetime import datetime
import asyncio
import stripe
import nest_asyncio
import logging
import pytz
from database_postgres import log_payment
from config import get_admin_ids
from bot_instance import bot, telegram_app

logger = logging.getLogger(__name__)

def get_checkout_session_url(user, plan:str):
    """ plan have to be either 30 or 500 in str 
    Note: Plan identifiers remain '30' and '500' for internal consistency,
    but these now correspond to 29$ and 490$ pricing respectively.
    
    Now uses Price IDs from environment variables for dynamic checkout session creation.
    """
    logger.info(f"=== CREATING CHECKOUT SESSION ===")
    logger.info(f"User ID: {user.id}, Plan: {plan}")
    
    if plan == '30':
        price_id = PRICE_ID_30
    elif plan == '500':
        price_id = PRICE_ID_500
    else:
        logger.error(f"Invalid plan type: {plan}")
        raise ValueError('При вызове функции по возвращении ссылки вы выбрали не план "30" и не план "500"')
    
    logger.info(f"Using Price ID: {price_id} for plan {plan}")
    
    if not price_id:
        logger.error(f"Price ID not configured for plan {plan}")
        raise ValueError(f'Price ID not configured for plan {plan}. Please check your environment variables.')
    
    metadata = {
        "telegram_user_id": str(user.id),
        "telegram_username": user.username or "unknown",
        "plan_type": plan
    }
    logger.info(f"Session metadata: {metadata}")
    
    checkout_session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price": price_id,  # Price ID from environment variables
            "quantity": 1,
        }],
        mode="payment",
        success_url='https://t.me/minys40kg_start_bot',
        cancel_url='https://t.me/minys40kg_start_bot',
        metadata=metadata
    )
    
    logger.info(f"✅ Created checkout session: {checkout_session.id}")
    return checkout_session.url
    

""" checkout_session_500 = stripe.checkout.Session.create(
    payment_method_types=["card"],
    line_items=[{
        "price": PRICE_ID_500,  # Price ID из Stripe
        "quantity": 1,
    }],
    mode="payment",
    success_url='https://t.me/minys40kg_start_bot',
    cancel_url='https://t.me/minys40kg_start_bot',
    metadata={
        "telegram_user_id": str(user.id),
        "telegram_username": user.username or "unknown",
        "plan_type": "30"
    }
) """

""" async def get_checkout_session(plan):
    stripe.checkout.Session.create(
    payment_method_types=["card"],
    line_items=[{
        "price": "price_30ABCDEF123",  # Price ID из Stripe
        "quantity": 1,
    }],
    mode="payment",
    success_url=YOUR_SUCCESS_URL,
    cancel_url=YOUR_CANCEL_URL,
    metadata={
        "telegram_user_id": str(user.id),
        "telegram_username": user.username or "unknown",
        "plan_type": "30"
    }
)  """


async def send_files_async(user_id, plan_type):
    from telegram_bot import send_file_to_user
    """Helper function to send files asynchronously"""
    import time
    files_start_time = time.time()
    
    try:
        logger.info("📂 ==========================================")
        logger.info("📂 SEND_FILES_ASYNC STARTED")
        logger.info("📂 ==========================================")
        logger.info(f"👤 User ID: {user_id} (type: {type(user_id)})")
        logger.info(f"📦 Plan type: {plan_type} (type: {type(plan_type)})")
        logger.info(f"⏰ Start time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Validate inputs
        if not user_id:
            logger.error("❌ No user_id provided to send_files_async")
            return False
        
        if not plan_type:
            logger.error("❌ No plan_type provided to send_files_async")
            return False
        
        logger.info(f"📞 Calling send_file_to_user function...")
        file_send_start = time.time()
        
        await send_file_to_user(user_id, plan_type)
        
        file_send_duration = time.time() - file_send_start
        total_duration = time.time() - files_start_time
        
        logger.info(f"⏱️ File sending took: {file_send_duration:.2f} seconds")
        logger.info(f"⏱️ Total send_files_async duration: {total_duration:.2f} seconds")
        logger.info(f"✅ send_file_to_user completed successfully for user {user_id} plan {plan_type}")
        return True
    except Exception as e:
        error_duration = time.time() - files_start_time
        logger.error(f"⏱️ Error occurred after {error_duration:.2f} seconds")
        logger.error(f"❌ Error in send_files_async for user {user_id} plan {plan_type}: {e}", exc_info=True)
        return False


def get_plan_type_from_price_id(price_id):
    """Determine plan type from Price ID by checking against all possible config vars"""
    from config import get_all_price_ids, get_current_pricing_mode, is_test_mode, is_using_one_dollar_prices
    
    logger.info(f"=== PRICE ID DETERMINATION ===")
    logger.info(f"Received price_id: {price_id}")
    logger.info(f"Current pricing mode: {get_current_pricing_mode()}")
    logger.info(f"Is test mode: {is_test_mode()}")
    logger.info(f"Is using one dollar prices: {is_using_one_dollar_prices()}")
    
    all_prices = get_all_price_ids()
    logger.info(f"All available price IDs: {all_prices}")
    
    # Check in all possible price ID combinations
    for mode in ['test', 'live_real', 'live_one_dollar']:
        logger.info(f"Checking mode '{mode}': 30={all_prices[mode]['30']}, 500={all_prices[mode]['500']}")
        if all_prices[mode]['30'] == price_id:
            logger.info(f"✅ MATCH FOUND: Price ID {price_id} matches plan '30' in mode '{mode}'")
            return '30'
        elif all_prices[mode]['500'] == price_id:
            logger.info(f"✅ MATCH FOUND: Price ID {price_id} matches plan '500' in mode '{mode}'")
            return '500'
    
    # Check current Price IDs as well (for extra safety)
    current_prices = all_prices.get('current', {})
    logger.info(f"Also checking current prices: 30={current_prices.get('30')}, 500={current_prices.get('500')}")
    if current_prices.get('30') == price_id:
        logger.info(f"✅ MATCH FOUND: Price ID {price_id} matches CURRENT plan '30'")
        return '30'
    elif current_prices.get('500') == price_id:
        logger.info(f"✅ MATCH FOUND: Price ID {price_id} matches CURRENT plan '500'")
        return '500'
    
    logger.warning(f"❌ NO MATCH: Unknown price_id: {price_id}, defaulting to '30'")
    logger.warning(f"This may cause files not to be sent properly!")
    return '30'

async def get_price_id_from_session(session):
    """Extract Price ID from Stripe session"""
    try:
        logger.info(f"=== EXTRACTING PRICE ID FROM SESSION ===")
        logger.info(f"Session ID: {session.get('id')}")
        logger.info(f"Session keys: {list(session.keys())}")
        
        # Get the line items from the session
        if 'line_items' in session:
            line_items = session['line_items']
            logger.info(f"Found line_items in session: {line_items}")
            if line_items and len(line_items) > 0:
                price_data = line_items[0].get('price', {})
                price_id = price_data.get('id')
                logger.info(f"Extracted price_id from session line_items: {price_id}")
                if price_id:
                    return price_id
        
        # Fallback: retrieve session details from Stripe API
        session_id = session.get('id')
        if session_id:
            logger.info(f"Fallback: Retrieving session details from Stripe API for session: {session_id}")
            stripe_session = stripe.checkout.Session.retrieve(
                session_id,
                expand=['line_items', 'line_items.data.price']
            )
            
            logger.info(f"Retrieved session from Stripe API: {stripe_session}")
            
            if stripe_session.line_items and len(stripe_session.line_items.data) > 0:
                price_id = stripe_session.line_items.data[0].price.id
                logger.info(f"✅ Retrieved price_id from Stripe API: {price_id}")
                return price_id
        
        logger.warning("❌ Could not extract price_id from session")
        return None
        
    except Exception as e:
        logger.error(f"Error getting price_id from session: {e}", exc_info=True)
        return None

async def process_payment_async(session):
    """Process payment and send files asynchronously"""
    import time
    async_start_time = time.time()
    
    try:
        logger.info("💎 ==========================================")
        logger.info("💎 PROCESS_PAYMENT_ASYNC STARTED")
        logger.info("💎 ==========================================")
        
        # Extract basic session information
        session_id = session.get('id', 'unknown')
        customer_email = session.get('customer_details', {}).get('email', '')
        amount = session.get('amount_total', 0) / 100  # Convert from cents to dollars
        currency = session.get('currency', 'USD').upper()
        payment_status = session.get('payment_status', 'unknown')
        
        logger.info(f"💳 Session ID: {session_id}")
        logger.info(f"📧 Customer email: {customer_email}")
        logger.info(f"💰 Amount: {amount} {currency} (cents: {session.get('amount_total', 0)})")
        logger.info(f"📊 Payment status: {payment_status}")
        logger.info(f"🏦 Currency: {currency}")
        logger.info(f"🏗️ Session keys: {list(session.keys())}")
        
        # Debug: log the full session object
        logger.debug(f"Full session object: {session}")
        
        # Get metadata and custom fields from the session
        metadata = session.get('metadata', {})
        custom_fields = session.get('custom_fields', [])
        
        # Log all available data for debugging
        logger.info(f"📝 Metadata keys: {list(metadata.keys()) if metadata else 'None'}")
        logger.info(f"📝 Metadata: {metadata}")
        logger.info(f"📋 Custom fields count: {len(custom_fields)}")
        logger.info(f"📋 Custom fields: {custom_fields}")
        
        # Get Price ID from session to determine plan type
        logger.info("🔍 ========== PRICE ID EXTRACTION ==========")
        price_id_start_time = time.time()
        price_id = await get_price_id_from_session(session)
        price_id_duration = time.time() - price_id_start_time
        logger.info(f"⏱️ Price ID extraction took: {price_id_duration:.2f} seconds")
        logger.info(f"🏷️ Extracted price_id: {price_id}")
        
        # Determine plan type based on Price ID
        logger.info("🧮 ========== PLAN TYPE DETERMINATION ==========")
        if price_id:
            plan_determination_start = time.time()
            plan_type = get_plan_type_from_price_id(price_id)
            plan_determination_duration = time.time() - plan_determination_start
            logger.info(f"⏱️ Plan determination took: {plan_determination_duration:.2f} seconds")
            logger.info(f"✅ Determined plan_type from price_id: {plan_type}")
        else:
            logger.warning("⚠️ No price_id found, using fallback logic")
            # Fallback: try to determine from metadata or amount
            logger.warning("No price_id found, using fallback methods")
            
            # First, try to get from session metadata
            plan_type_from_metadata = metadata.get('plan_type')
            logger.info(f"Metadata contains plan_type: {plan_type_from_metadata}")
            
            if plan_type_from_metadata and plan_type_from_metadata in ['30', '500']:
                plan_type = plan_type_from_metadata
                logger.info(f"✅ Using plan_type from metadata: {plan_type}")
            else:
                # Last resort: determine by amount
                # For $1 prices, we need to check metadata more carefully
                from config import is_using_one_dollar_prices
                
                if is_using_one_dollar_prices():
                    # In $1 mode, both plans cost $1, so we can't determine by amount
                    # But we can try to get it from the original metadata or other hints
                    logger.warning(f"In $1 mode with amount ${amount}, cannot determine plan by amount alone")
                    
                    # Try to extract from customer details or other session data
                    # Check if there are any hints in the session
                    session_plan_hint = None
                    if 'custom_fields' in session and session['custom_fields']:
                        for field in session['custom_fields']:
                            if 'plan' in field.get('key', '').lower():
                                session_plan_hint = field.get('text', {}).get('value')
                                break
                    
                    if session_plan_hint and session_plan_hint in ['30', '500']:
                        plan_type = session_plan_hint
                        logger.info(f"Found plan hint in custom fields: {plan_type}")
                    else:
                        plan_type = '30'  # Default fallback
                        logger.info(f"Defaulting to plan_type '30' for $1 payment")
                else:
                    # Regular price mode - determine by amount
                    # Updated for new pricing: 29$ and 490$
                    if amount >= 400:  # 490$ plan (using 400 as threshold to account for any fees)
                        plan_type = '500'
                        logger.info(f"Determined plan_type '500' (490$ plan) based on amount: ${amount}")
                    else:  # 29$ plan
                        plan_type = '30'
                        logger.info(f"Determined plan_type '30' (29$ plan) based on amount: ${amount}")
        
        logger.info(f"Final determined plan_type: {plan_type}")
        
        # Extract user_id from custom fields (primary source)
        user_id = None
        username = None
        
        # First, process all custom fields to find both user_id and username
        for field in custom_fields:
            field_key = field.get('key', '').lower()
            field_type = field.get('type', '').lower()
            
            # Check for user_id in various possible field names
            if field_key in ['myidbot', 'telegram_user_id', 'yourtelegramid', 'yourtelegramidmyidbot']:
                if field_type == 'numeric':
                    user_id = str(field.get('numeric', {}).get('value', '')).strip()
                elif field_type == 'text':
                    # Try to extract numeric ID from text field
                    value = field.get('text', {}).get('value', '').strip()
                    if value.isdigit():
                        user_id = value
                
                if user_id and user_id.lower() != 'none':
                    logger.info(f"Found Telegram ID in custom field '{field_key}': {user_id}")
                    # Store the user_id in metadata for later use
                    metadata['telegram_user_id'] = user_id
            
            # Check for username
            elif field_key == 'username':
                if field_type == 'text':
                    username = field.get('text', {}).get('value', '').strip('@')
                    if username and username.lower() != 'none':
                        logger.info(f"Found Telegram username in custom field: {username}")
                        metadata['username'] = username
        
        # Fallback to metadata if not found in custom fields
        if not user_id:
            raw_user_id = metadata.get('telegram_user_id')
            if raw_user_id and raw_user_id.isdigit():
                user_id = raw_user_id

        if not username:
            raw_username = metadata.get('telegram_username')
            if raw_username and not raw_username.startswith("{"):
                username = raw_username.strip("@")
        
        # Log the extracted values for debugging
        logger.info(f"Extracted user_id: {user_id}, username: {username}")
        
        # If we still don't have a user_id, try to get it from the customer email as a last resort
        if not user_id and session.get('customer_details', {}).get('email'):
            email = session['customer_details']['email']
            if email and email.split('@')[0].isdigit():
                user_id = email.split('@')[0]
                logger.info(f"Extracted Telegram ID from email: {user_id}")
        
        amount = session.get('amount_total', 0) / 100  # Convert from cents
        currency = session.get('currency', 'usd').upper()
        payment_status = session.get('payment_status', 'unknown')
        payment_method = session.get('payment_method_types', ['unknown'])[0]
        payment_id = session.get('id', 'unknown')
        
        logger.info(f"Payment details - User ID: {user_id}, Amount: {amount} {currency}, Status: {payment_status}")
        
        # Log the payment attempt to the database
        try:
            logger.info(f"Attempting to log payment to database. Payment ID: {payment_id}")
            
            # Make sure we have a valid user_id
            if not user_id or str(user_id).lower() == 'none':
                raise ValueError("No valid Telegram user ID found in payment data")
                
            # Import here to avoid circular imports
            try:
                logger.info("Successfully imported log_payment from database_postgres")
            except ImportError as ie:
                logger.error(f"Failed to import log_payment: {str(ie)}", exc_info=True)
                raise
            
            # Create a clean metadata dictionary that's JSON serializable
            clean_metadata = {
                'stripe_session_id': session.get('id'),
                'payment_status': session.get('payment_status'),
                'payment_intent': session.get('payment_intent'),
                'customer_details': {
                    k: v for k, v in session.get('customer_details', {}).items() 
                    if not isinstance(v, (bytes, bytearray))
                } if session.get('customer_details') else {},
                'subscription': session.get('subscription'),
            }
            
            # Get customer email
            customer_email = session.get('customer_email') or session.get('customer_details', {}).get('email')
            
            # Log the payment
            logger.info(f"Logging payment: user_id={user_id}, email={customer_email}, "
                      f"amount={amount}, status={payment_status}, payment_id={payment_id}, currency={currency}")
            
            # Create metadata for the payment
            payment_metadata = {
                'plan': 'premium' if plan_type == '500' else 'basic',
                'plan_type': plan_type,
                'price_id': price_id,
                'username': username or f"user_{user_id}",
                'telegram_user_id': user_id
            }
            
            # Clean up metadata to avoid JSON serialization issues
            clean_metadata = {k: str(v) for k, v in payment_metadata.items() if v is not None}
            
            # Log the payment to the database with correct column names
            result = await log_payment(
                user_id=user_id,
                email=customer_email,
                amount=amount,
                status=payment_status,
                payment_method=payment_method,
                payment_id=payment_id,
                metadata=payment_metadata,
                currency=currency,
                telegram_user_id=user_id,
                telegram_username=username
            )
            logger.info(f"Successfully logged payment to database. Result: {result}")
            
            # Process payments based on status
            logger.info(f"=== PAYMENT STATUS CHECK ===")
            logger.info(f"Payment status: '{payment_status}'")
            logger.info(f"Session status: '{session.get('status', 'unknown')}'")
            
            # Accept multiple payment statuses for test and live modes
            valid_statuses = ['paid', 'complete', 'succeeded']
            session_status = session.get('status', '')
            
            if payment_status not in valid_statuses and session_status != 'complete':
                logger.warning(f"Payment status '{payment_status}' and session status '{session_status}' - processing anyway for test mode")
                if not (payment_status in ['unpaid', 'no_payment_required'] and session_status == 'complete'):
                    logger.info(f"Skipping processing due to payment status: {payment_status}, session status: {session_status}")
                    return {"status": "success", "message": f"Payment logged but not processed (status: {payment_status}, session: {session_status})"}
            
            logger.info(f"✅ Payment status acceptable, proceeding with processing")
            
            # Update user information with payment details
            try:
                from database_postgres import add_or_update_user
                
                # Prepare user data
                first_name = ''
                last_name = ''
                if session.get('customer_details', {}).get('name'):
                    name_parts = session['customer_details']['name'].split(' ', 1)
                    first_name = name_parts[0] if name_parts else ''
                    last_name = name_parts[1] if len(name_parts) > 1 else ''
                
                # Plan type already determined from Price ID above
                logger.info(f"Using plan_type: {plan_type} (determined from Price ID: {price_id})")
                
                # Update user with payment details
                user_update = await add_or_update_user(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    email=customer_email,
                    plan=plan_type
                )
                
                if not user_update:
                    logger.error(f"Failed to update user {user_id} in database")
                    return {"status": "error", "message": "Failed to update user in database"}
                
                logger.info(f"Successfully updated user {user_id} with payment details")
                
                # Send admin notification based on plan type
                logger.info(f"=== ADMIN NOTIFICATIONS ===")
                admin_ids = get_admin_ids()
                logger.info(f"Admin IDs: {admin_ids}")
                logger.info(f"Plan type: {plan_type}")

                if plan_type == '500' and admin_ids:
                    logger.info("Sending premium subscription notification to admins")
                    try:
                        mexico_tz = pytz.timezone('America/Mexico_City')
                        payment_time = datetime.now(mexico_tz).strftime('%d.%m.%Y %H:%M:%S')
                        
                        # Escape username to prevent markdown parsing issues
                        safe_username = (username or 'Не указан').replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[').replace(']', '\\]')
                        
                        # Format the message without problematic Markdown
                        message = (
                            "💰 Пользователь купил у вас ведение и ожидает, что вы ему напишите! 💰\n\n"
                            f"👤 Пользователь: @{safe_username}\n"
                            f"🆔 ID: {user_id}\n"
                            f"💳 Сумма: {amount} {currency.upper()}\n"
                            f"🔖 Price ID: {price_id}\n"
                            f"📦 План: {plan_type}\n"
                            f"📅 Дата и время: {payment_time} (Mexico)"
                        )
                        
                        # Send the message without parse mode to avoid errors
                        for admin_id in admin_ids:
                            try:
                                await telegram_app.bot.send_message(
                                    chat_id=admin_id,
                                    text=message
                                )
                                logger.info(f"✅ Sent notification to admin {admin_id}")
                            except Exception as e:
                                # Handle common Telegram errors gracefully
                                if "Chat not found" in str(e) or "Forbidden" in str(e):
                                    logger.warning(f"Admin {admin_id} is unreachable (blocked bot or deleted chat): {e}")
                                else:
                                    logger.error(f"Failed to send admin notification to {admin_id}: {e}", exc_info=True)
                        logger.info(f"Sent admin notification for premium subscription to user {user_id}")
                    except Exception as e:
                        logger.error(f"Failed to send admin notification: {str(e)}", exc_info=True)
                elif plan_type == '30' and admin_ids:
                    try:
                        mexico_tz = pytz.timezone('America/Mexico_City')
                        payment_time = datetime.now(mexico_tz).strftime('%d.%m.%Y %H:%M:%S')
                        
                        # Escape username to prevent markdown parsing issues
                        safe_username = (username or 'Не указан').replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[').replace(']', '\\]')
                        
                        # Format the message without problematic Markdown
                        message = (
                            "💰 Пользователь купил у вас план питания и ожидает, что вы его сделаете! 💰\n\n"
                            f"👤 Пользователь: @{safe_username}\n"
                            f"🆔 ID: {user_id}\n"
                            f"💳 Сумма: {amount} {currency.upper()}\n"
                            f"🔖 Price ID: {price_id}\n"
                            f"📦 План: {plan_type}\n"
                            f"📅 Дата и время: {payment_time} (Mexico)"
                        )
                        
                        # Send the message without parse mode to avoid errors
                        for admin_id in admin_ids:
                            try:
                                await telegram_app.bot.send_message(
                                    chat_id=admin_id,
                                    text=message
                                )
                                logger.info(f"✅ Sent notification to admin {admin_id}")
                            except Exception as e:
                                # Handle common Telegram errors gracefully
                                if "Chat not found" in str(e) or "Forbidden" in str(e):
                                    logger.warning(f"Admin {admin_id} is unreachable (blocked bot or deleted chat): {e}")
                                else:
                                    logger.error(f"Failed to send admin notification to {admin_id}: {e}", exc_info=True)
                        logger.info(f"Sent admin notification for basic subscription to user {user_id}")
                    except Exception as e:
                        logger.error(f"Failed to send admin notification: {str(e)}", exc_info=True)
                
                # Send files to the user
                logger.info("📤 ========== SENDING FILES ==========")
                logger.info(f"👤 User ID: {user_id}")
                logger.info(f"📦 Plan Type: {plan_type}")
                logger.info(f"🏷️ Price ID used: {price_id}")
                logger.info(f"💰 Payment amount: {amount} {currency}")
                
                files_start_time = time.time()
                success = await send_files_async(user_id, plan_type)
                files_duration = time.time() - files_start_time
                
                logger.info(f"⏱️ File sending process took: {files_duration:.2f} seconds")
                
                if success:
                    logger.info(f"✅ Successfully sent files to user {user_id} for plan {plan_type}")
                    
                    # Log final summary
                    total_processing_time = time.time() - async_start_time
                    logger.info("🎉 ========== PAYMENT PROCESSING COMPLETED ==========")
                    logger.info(f"⏱️ Total processing time: {total_processing_time:.2f} seconds")
                    logger.info(f"✅ Final result: SUCCESS")
                    
                    return {"status": "success", "message": f"Successfully processed payment and sent files to user {user_id}"}
                else:
                    error_msg = f"❌ Failed to send files to user {user_id} for plan {plan_type}"
                    logger.error(error_msg)
                    
                    total_processing_time = time.time() - async_start_time
                    logger.error("💥 ========== PAYMENT PROCESSING FAILED ==========")
                    logger.error(f"⏱️ Total processing time: {total_processing_time:.2f} seconds")
                    logger.error(f"❌ Final result: FAILURE (file sending)")
                    
                    return {"status": "error", "message": error_msg}
                    
            except Exception as e:
                error_msg = f"Error processing payment: {str(e)}"
                logger.error(error_msg, exc_info=True)
                return {"status": "error", "message": error_msg}
                
        except Exception as e:
            error_msg = f"Unexpected error in process_payment_async: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {"status": "error", "message": error_msg}
    except Exception as e:
        error_msg = f"Error in payment processing: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"status": "error", "message": error_msg}

           
def handle_successful_payment(session):
    """Handle successful Stripe payment"""
    import time
    handler_start_time = time.time()
    
    try:
        logger.info("🚀 ==========================================")
        logger.info("🚀 HANDLE_SUCCESSFUL_PAYMENT STARTED")
        logger.info("🚀 ==========================================")
        logger.info(f"📋 Session ID: {session.get('id', 'unknown')}")
        
        # Create a new event loop for this thread
        logger.info("🔄 Creating new event loop for payment processing")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Run the async function and get the result
            logger.info("⚡ Starting async payment processing")
            async_start_time = time.time()
            result = loop.run_until_complete(process_payment_async(session))
            async_duration = time.time() - async_start_time
            logger.info(f"⏱️ Async processing completed in {async_duration:.2f} seconds")
            
            handler_duration = time.time() - handler_start_time
            logger.info(f"⏱️ Total handler duration: {handler_duration:.2f} seconds")
            
            return result
            
        except Exception as e:
            error_msg = f"Error in payment processing: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {"status": "error", "message": error_msg}
            
        finally:
            # Clean up the loop
            loop.close()
            
    except Exception as e:
        error_msg = f"Unexpected error in handle_successful_payment: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"status": "error", "message": error_msg}
            
    except Exception as e:
        logger.error("Error handling successful payment", exc_info=True)

def handle_failed_payment(session):
    """Handle failed/expired Stripe payment"""
    user_id = session.get('metadata', {}).get('telegram_user_id')
    amount = session.get('amount_total', 0) / 100
    
    logger.info(f"Failed payment: ${amount} for user {user_id}")

    if not user_id:
        logger.warning("No telegram_user_id provided")
        return

    nest_asyncio.apply()
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    async def send_failure_message():
        try:
            await telegram_app.bot.send_message(
                chat_id=user_id,
                text="К сожалению, оплата не прошла или была отменена. Попробуйте еще раз или свяжитесь с поддержкой."
            )
            logger.info(f"Failure message sent to user {user_id}")
        except Exception as e:
            logger.error(f"Error sending failure message to user {user_id}", exc_info=True)

    asyncio.run(send_failure_message())

def stripe_webhook():
    import time
    webhook_start_time = time.time()
    
    try:
        logger.info("🔄 ===============================================")
        logger.info("🔄 STRIPE WEBHOOK PROCESSING STARTED")
        logger.info("🔄 ===============================================")
        logger.info(f"🔧 Current config - Test mode: {STRIPE_IS_TEST_MODE_ON}, Use $1: {USE_ONE_DOLLAR_PRICES}")
        logger.info(f"🔧 Stripe API key starts with: {STRIPE_API_KEY[:7]}...")
        logger.info(f"🔧 Webhook secret starts with: {STRIPE_WEBHOOK_SECRET[:7]}...")
        
        payload = request.get_data(as_text=True)
        sig_header = request.headers.get('stripe-signature')
        
        logger.info(f"📡 Payload length: {len(payload)} characters")
        logger.info(f"🔐 Signature header: {sig_header[:50]}..." if sig_header else "❌ No signature header")
        logger.info(f"🔑 Webhook secret configured: {bool(STRIPE_WEBHOOK_SECRET)}")
        
        # Log first 200 chars of payload for debugging (remove sensitive data first)
        safe_payload = payload[:200].replace('"card"', '"[CARD]"').replace('"payment_method"', '"[PM]"')
        logger.info(f"📄 Payload preview: {safe_payload}...")

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
            logger.info(f"✅ Webhook signature verification successful")
            logger.info(f"📋 Event type: {event['type']}")
            logger.info(f"🆔 Event ID: {event.get('id', 'unknown')}")
            logger.info(f"⏰ Event created timestamp: {event.get('created', 'unknown')}")
            logger.info(f"🔍 Event livemode: {event.get('livemode', 'unknown')}")
            
            # Handle the event
            if event['type'] == 'checkout.session.completed':
                logger.info("🎯 Processing checkout.session.completed event")
                session = event['data']['object']
                session_id = session.get('id', 'unknown')
                logger.info(f"💰 Processing checkout session: {session_id}")
                logger.info(f"💰 Session status: {session.get('payment_status', 'unknown')}")
                logger.info(f"💰 Session mode: {session.get('mode', 'unknown')}")
                logger.info(f"💰 Customer email: {session.get('customer_details', {}).get('email', 'not provided')}")
                
                payment_start_time = time.time()
                result = handle_successful_payment(session)
                payment_duration = time.time() - payment_start_time
                
                logger.info(f"⏱️ Payment processing took: {payment_duration:.2f} seconds")
                
                if result and result.get('status') == 'error':
                    logger.error(f"❌ Payment processing failed: {result.get('message', 'Unknown error')}")
                else:
                    logger.info(f"✅ Payment processing completed successfully")
                    
                return jsonify(result or {"status": "success", "message": "Payment processed"}), 200
                
            elif event['type'] == 'checkout.session.async_payment_succeeded':
                session = event['data']['object']
                logger.info(f"Processing checkout.session.async_payment_succeeded for session: {session.id}")
                result = handle_successful_payment(session)
                if result and result.get('status') == 'error':
                    logger.error(f"Error processing async payment: {result.get('message', 'Unknown error')}")
                return jsonify(result or {"status": "success", "message": "Async payment processed"}), 200
                
            elif event['type'] == 'checkout.session.async_payment_failed':
                session = event['data']['object']
                logger.warning(f"Processing checkout.session.async_payment_failed for session: {session.id}")
                handle_failed_payment(session)
                return jsonify({"status": "success", "message": "Payment failure handled"}), 200
                
            elif event['type'] == 'payment_intent.payment_failed':
                payment_intent = event['data']['object']
                logger.warning(f"Payment failed for payment intent: {payment_intent.id}")
                return jsonify({"status": "success", "message": "Payment failure logged"}), 200
                
            else:
                logger.info(f"Unhandled event type: {event['type']}")
                return jsonify({"status": "success", "message": f"Unhandled event type: {event['type']}"}), 200
                
        except ValueError as e:
            error_msg = f"Invalid payload: {e}"
            logger.error(error_msg)
            return jsonify({"status": "error", "message": error_msg}), 400
            
        except stripe.error.SignatureVerificationError as e:
            error_msg = f"Invalid signature: {e}"
            logger.error(error_msg)
            return jsonify({"status": "error", "message": error_msg}), 400
            
    except Exception as e:
        error_msg = f"Unexpected error processing webhook: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500

__all__ = [
    'handle_successful_payment',
    'handle_failed_payment',
    'stripe_webhook'
]
