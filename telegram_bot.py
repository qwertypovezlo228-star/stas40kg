import os
import uuid
import asyncio
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from flask import session as flask_session
from config import *
from config import get_admin_ids
from database_postgres import log_user_action
# from handlers.admin_handlers import get_admin_handlers  # No longer needed
from telegram.request import HTTPXRequest
import logging
import aiohttp
import asyncpg
from collections import Counter
from datetime import datetime, timedelta
import pytz
from typing import List, Dict, Any
from stripe_handlers import get_checkout_session_url
from bot_instance import bot, telegram_app
from heroku_config_manager import get_current_stripe_mode, toggle_stripe_mode, set_stripe_mode

logger = logging.getLogger(__name__)

# Словарь для отслеживания состояний пользователей
user_states = {}

# Константы состояний
STATE_RUSSIA_PAYMENT_30 = "russia_payment_30"
STATE_RUSSIA_PAYMENT_500 = "russia_payment_500"

def format_relative_time(payment_time: datetime) -> str:
    """Format payment time as relative time (e.g., '2 часа назад')"""
    now = datetime.now(pytz.timezone('America/Mexico_City'))
    time_diff = now - payment_time
    
    if time_diff < timedelta(minutes=1):
        return "только что"
    elif time_diff < timedelta(hours=1):
        minutes = int(time_diff.seconds / 60)
        if 10 <= minutes % 100 <= 20 or minutes % 10 >= 5 or minutes % 10 == 0:
            return f"{minutes} минут назад"
        elif minutes % 10 == 1:
            return f"{minutes} минуту назад"
        else:
            return f"{minutes} минуты назад"
    elif time_diff < timedelta(days=1):
        hours = int(time_diff.seconds / 3600)
        if hours == 1 or (hours % 10 == 1 and hours != 11):
            return f"{hours} час назад"
        elif 2 <= hours % 10 <= 4 and (hours < 10 or hours > 20):
            return f"{hours} часа назад"
        else:
            return f"{hours} часов назад"
    else:
        days = time_diff.days
        if days == 1:
            return f"{days} день назад в {payment_time.strftime('%H:%M')}"
        elif 2 <= days <= 4:
            return f"{days} дня назад в {payment_time.strftime('%H:%M')}"
        else:
            return f"{days} дней назад в {payment_time.strftime('%H:%M')}"

async def get_premium_users() -> List[Dict[str, Any]]:
    """Fetch users who purchased the $490 plan"""
    try:
        # Connect to Supabase
        conn = await asyncpg.connect(SUPABASE_POSTGRES_URL)
        
        # Query payments table for personal coaching plan purchases (amount = 30)
        query = """
        SELECT p.telegram_user_id as user_id, p.created_at as payment_time, p.email, 
               p.metadata->>'username' as username, 
               u.first_name, u.last_name, u.username as tg_username
        FROM payments p
        LEFT JOIN users u ON p.telegram_user_id = u.user_id::text
        WHERE p.amount = 30 AND p.status = 'completed'
        ORDER BY p.created_at DESC
        """
        
        rows = await conn.fetch(query)
        await conn.close()
        
        # Convert to list of dicts and format times
        mexico_tz = pytz.timezone('America/Mexico_City')
        result = []
        
        for row in rows:
            payment_time = row['payment_time']
            if payment_time.tzinfo is None:
                payment_time = pytz.utc.localize(payment_time)
            
            result.append({
                'user_id': row['user_id'],
                'username': row['username'] or row['tg_username'],
                'first_name': row['first_name'],
                'last_name': row['last_name'],
                'email': row['email'],
                'payment_time': payment_time.astimezone(mexico_tz),
                'formatted_time': payment_time.astimezone(mexico_tz).strftime('%d.%m.%Y %H:%M'),
                'relative_time': format_relative_time(payment_time.astimezone(mexico_tz))
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Error fetching premium users: {str(e)}", exc_info=True)
        return []

async def handle_admin_panel(query, user, bot):
    from config import is_test_mode, is_using_one_dollar_prices
    
    admin_ids = [int(i.strip()) for i in ADMIN_IDS.split(',') if i.strip().isdigit()]

    if user.id not in admin_ids:
        await query.answer("🚫 Нет доступа!", show_alert=True)
        return

    await query.message.delete()

    # Get current pricing state for display with detailed info
    if is_test_mode():
        status_text = "🧪 *ТЕСТОВЫЙ РЕЖИМ*\n• Без реальных денег\n• Тестовые карты Stripe\n• Файлы отправляются как обычно"
    elif is_using_one_dollar_prices():
        status_text = "🔥 *ЛАЙВ $1 ТЕСТ*\n• Реальные деньги ($1)\n• Тестирование функционала\n• Все файлы и уведомления работают"
    else:
        status_text = "💰 *БОЕВОЙ РЕЖИМ*\n• Реальные цены ($29/$490)\n• Продажи клиентам\n• Полный функционал"

    keyboard = [
        [InlineKeyboardButton("📊 Общая статистика кнопок", callback_data='admin__stats')],
        [InlineKeyboardButton("⚙️ Тестовый режим для Stripe", callback_data='admin__test_mode')],
        [InlineKeyboardButton("💰 Переключение лайв цен", callback_data='admin__live_prices')],
        [InlineKeyboardButton("Назад", callback_data="to_start_from_admin_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await bot.send_message(
        chat_id=query.message.chat_id,
        text=(f"*Админ панель*\n\n{status_text}\n\n"
              "Здесь вы можете просмотреть общую статистику по активности пользователей.\n"
              "• *Статистика кнопок* — показывает, сколько раз и какие кнопки нажимали все пользователи, что помогает анализировать их поведение и улучшать работу бота."
        ),
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def show_premium_users_page(query, premium_users: List[Dict[str, Any]], page: int, users_per_page: int, total_pages: int):
    """Display a page of premium users with pagination"""
    start_idx = page * users_per_page
    end_idx = min(start_idx + users_per_page, len(premium_users))
    current_users = premium_users[start_idx:end_idx]
    
    # Format the message
    message = "👑 *Пользователи, оплатившие личное ведение у Стаса*\n\n"
    
    for i, user in enumerate(current_users, start=start_idx + 1):
        username = f"@{user['username']}" if user['username'] else "Без username"
        name_parts = []
        if user['first_name']:
            name_parts.append(user['first_name'])
        if user['last_name']:
            name_parts.append(user['last_name'])
        name = ' '.join(name_parts) if name_parts else 'Без имени'
        
        message += (
            f"{i}. {username} ({name})\n"
            f"   📧 {user['email'] or 'Нет email'}\n"
            f"   🕒 {user['formatted_time']} (МСК)\n"
            f"   ⏱ {user['relative_time']}\n\n"
        )
    
    # Add pagination info
    message += f"\nСтраница {page + 1} из {total_pages}"
    
    # Create pagination buttons
    keyboard = []
    
    # Previous page button
    if page > 0:
        keyboard.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"premium_users_page_{page-1}"))
    
    # Next page button
    if page < total_pages - 1:
        if keyboard:  # If we have a previous button, add next to the same row
            keyboard[-1] = [keyboard[-1], InlineKeyboardButton("Вперед ➡️", callback_data=f"premium_users_page_{page+1}")]
        else:
            keyboard.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"premium_users_page_{page+1}"))
    
    # Add back to admin panel button
    keyboard.append([InlineKeyboardButton("🔙 В админ панель", callback_data="admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error showing premium users page: {str(e)}", exc_info=True)
        await query.answer("Произошла ошибка при загрузке данных.", show_alert=True)

# --- Обработчики кнопок ---
async def handle_admin_stats(query):
    stats_text = await get_button_stats()

    keyboard = [[InlineKeyboardButton("Назад", callback_data="admin")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        stats_text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )


async def handle_admin_users(query, bot):
    users_text = await get_user_stats()

    keyboard = [[InlineKeyboardButton("Назад", callback_data="admin")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if len(users_text) > 4000:
        parts = [users_text[i:i + 4000] for i in range(0, len(users_text), 4000)]
        for idx, part in enumerate(parts):
            if idx == 0:
                await query.edit_message_text(
                    part,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            else:
                await bot.send_message(
                    chat_id=query.message.chat_id,
                    text=part,
                    parse_mode="HTML"
                )
    else:
        await query.edit_message_text(
            users_text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        
        
async def handle_admin_stripe_test_mode(query, bot):
    """Обработчик для управления режимом Stripe"""
    current_mode = get_current_stripe_mode()
    
    keyboard = [
        [
            InlineKeyboardButton(
                f"🔄 Переключить режим (сейчас: {current_mode})", 
                callback_data='admin__toggle_stripe_mode'
            )
        ],
        [InlineKeyboardButton("🔄 Обновить статус", callback_data='admin__refresh_stripe_status')],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    status_icon = "🟡" if current_mode == "TEST" else "🟢"
    message = (
        f'⚙️ <b>Управление режимом Stripe</b>\n\n'
        f'<b>Текущий режим:</b> {status_icon} {current_mode}.\n\n'
        f"🟡 <b>TEST режим:</b>\n"
        f"• Безопасные тестовые платежи.\n"
        f"• Деньги не списываются с карт.\n"
        f"• Используются специальные тестовые карты.\n"
        f"• Подходит для проверки работы бота.\n\n"
        f"🟢 <b>LIVE режим:</b>\n"
        f"• Настоящие платежи с реальных карт.\n"
        f"• Деньги списываются со счетов клиентов.\n"
        f"• Тестовые карты не работают.\n"
        f"• Используется в боевом режиме.\n\n"
        f'Ниже предоставлены платежные данные карт для проверки работоспособности бота при разных сценариях произведения оплаты Stripe:\n\n'
        f"✅ <b>Успешная оплата:</b>\n"
        f"💳 Номер: <code>4242424242424242</code>\n"
        f"📅 Срок: <code>12/30</code>\n"
        f"🔐 CVC: <code>123</code>\n"
        f"👤 Имя: <code>Test User</code>\n"
        f"📧 Email: <code>test@example.com</code>\n\n"
        f"❌ <b>Отклоненная оплата:</b>\n"
        f"💳 Номер: <code>4000000000000002</code>\n"
        f"📅 Срок: <code>12/30</code>\n"
        f"🔐 CVC: <code>123</code>\n"
        f"👤 Имя: <code>Test Decline</code>\n"
        f"📧 Email: <code>decline@example.com</code>\n\n"
        f"⚠️ Изменение режима потребует перезагрузки приложения (~30 сек)"
    )
    
    try:
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error in handle_admin_stripe_test_mode: {e}")
        await query.answer("Произошла ошибка при загрузке настроек Stripe.", show_alert=True)

async def handle_stripe_mode_actions(query, bot):
    """Обработчик действий с режимом Stripe"""
    try:
        if query.data == 'admin__toggle_stripe_mode':
            success, new_mode = toggle_stripe_mode()
            
            if success:
                await query.answer(
                    f"✅ Режим изменён на {new_mode}!\nПриложение перезагружается...", 
                    show_alert=True
                )
                # Обновляем интерфейс
                await handle_admin_stripe_test_mode(query, bot)
            else:
                await query.answer("❌ Ошибка при изменении режима!", show_alert=True)
                                      
        elif query.data == 'admin__refresh_stripe_status':
            await handle_admin_stripe_test_mode(query, bot)
            await query.answer("🔄 Статус обновлён", show_alert=False)
            
    except Exception as e:
        logger.error(f"Error in handle_stripe_mode_actions: {e}")
        await query.answer("Произошла ошибка при выполнении действия.", show_alert=True)

async def handle_admin_live_prices(query, bot):
    """Обработчик для переключения лайв цен между $1 и реальными ценами"""
    from config import is_test_mode, is_using_one_dollar_prices
    import requests
    import os
    
    # Проверяем, что мы в лайв режиме
    if is_test_mode():
        await query.answer("❌ Эта функция доступна только в лайв режиме!", show_alert=True)
        return
    
    current_dollar_mode = is_using_one_dollar_prices()
    
    keyboard = [
        [
            InlineKeyboardButton(
                f"🔄 Переключить цены", 
                callback_data='admin__toggle_live_prices'
            )
        ],
        [InlineKeyboardButton("🔄 Обновить статус", callback_data='admin__refresh_live_prices')],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if current_dollar_mode:
        current_icon = "🔥"
        current_text = "Лайв $1 цены"
        next_text = "реальные цены ($29/$490)"
    else:
        current_icon = "💰"
        current_text = "Реальные цены ($29/$490)"
        next_text = "лайв $1 цены"
    
    message = (
        f'💰 <b>Управление лайв ценами</b>\n\n'
        f'<b>Текущий режим:</b> {current_icon} {current_text}\n\n'
        f"🔥 <b>Лайв $1 цены:</b>\n"
        f"• Используются реальные Stripe ссылки\n"
        f"• Цена товаров: $1 за оба плана\n"
        f"• Для тестирования функционала с реальными деньгами\n"
        f"• Подходит для проверки всего процесса\n\n"
        f"💰 <b>Реальные цены:</b>\n"
        f"• Используются боевые Stripe ссылки\n"
        f"• Цена товаров: $29 и $490\n"
        f"• Для работы с клиентами\n"
        f"• Боевой режим продаж\n\n"
        f"При переключении будут использоваться {next_text}.\n\n"
        f"⚠️ Изменение цен потребует перезагрузки приложения (~30 сек)"
    )
    
    try:
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error in handle_admin_live_prices: {e}")
        await query.answer("Произошла ошибка при загрузке настроек цен.", show_alert=True)

async def handle_live_prices_actions(query, bot):
    """Обработчик действий с лайв ценами"""
    from config import is_using_one_dollar_prices, is_test_mode
    import requests
    import os
    
    try:
        if query.data == 'admin__toggle_live_prices':
            # Проверяем, что мы в лайв режиме
            if is_test_mode():
                await query.answer("❌ Эта функция доступна только в лайв режиме!", show_alert=True)
                return
                
            # Get current setting and toggle it
            current_dollar_mode = is_using_one_dollar_prices()
            new_dollar_mode = not current_dollar_mode
            
            # Update Heroku config var
            heroku_app_name = os.getenv('HEROKU_APP_NAME')
            heroku_api_key = os.getenv('HEROKU_API_KEY')
            
            if not heroku_app_name or not heroku_api_key:
                await query.answer("❌ Heroku credentials not configured!", show_alert=True)
                return
            
            url = f"https://api.heroku.com/apps/{heroku_app_name}/config-vars"
            headers = {
                "Authorization": f"Bearer {heroku_api_key}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.heroku+json; version=3"
            }
            
            data = {
                "USE_ONE_DOLLAR_PRICES": str(new_dollar_mode)
            }
            
            response = requests.patch(url, json=data, headers=headers)
            response.raise_for_status()
            
            price_text = "$1" if new_dollar_mode else "реальные ($29/$490)"
            await query.answer(
                f"✅ Цены переключены на {price_text}!\nПриложение перезагружается...", 
                show_alert=True
            )
            # Обновляем интерфейс
            await handle_admin_live_prices(query, bot)
                                      
        elif query.data == 'admin__refresh_live_prices':
            await handle_admin_live_prices(query, bot)
            await query.answer("🔄 Статус обновлён", show_alert=False)
            
    except Exception as e:
        logger.error(f"Error in handle_live_prices_actions: {e}")
        await query.answer("❌ Ошибка при переключении цен!", show_alert=True)

# Общая статистика кнопок
async def fetch_from_supabase(endpoint: str, params: dict = None):
    # Use SUPABASE_SERVICE_ROLE instead of SUPABASE_SERVICE_KEY
    service_key = os.getenv('SUPABASE_SERVICE_ROLE', '')
    if not service_key:
        logger.error("SUPABASE_SERVICE_ROLE environment variable is not set")
        raise ValueError("SUPABASE_SERVICE_ROLE is not configured")

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    # Rest of the function remains the same...
    headers = {k: v for k, v in headers.items() if v is not None}
    params = params or {}
    
    clean_params = {}
    for key, value in params.items():
        if value is not None:
            clean_params[key] = value

    try:
        async with aiohttp.ClientSession() as session:
            url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
            logger.info(f"Making request to: {url}")
            logger.info(f"Headers: {headers}")
            logger.info(f"Params: {clean_params}")
            
            async with session.get(
                url,
                headers=headers,
                params=clean_params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Supabase API error: {resp.status} - {text}")
                    raise Exception(f"Supabase API error: {resp.status} - {text}")
                return await resp.json()
    except Exception as e:
        logger.error(f"Error in fetch_from_supabase: {str(e)}", exc_info=True)
        raise

# Общая статистика кнопок
async def get_button_stats():
    try:
        if not SUPABASE_URL or not os.getenv('SUPABASE_SERVICE_ROLE'):
            logger.error("Missing Supabase configuration")
            return "❌ Ошибка конфигурации: отсутствуют настройки Supabase"

        rows = await fetch_from_supabase("user_actions", {"select": "action"})
        if not rows:
            return "ℹ️ Нет данных о кликах"

        actions = []
        admin_actions = {
            'button_click_admin', 'button_click_admin_users', 'button_click_admin_payments',
            'button_click_admin_funnel', 'button_click_admin_refresh', 'button_click_admin_stats',
            'button_click_admin_analytics', 'button_click_admin__stats', 'button_click_admin__users'
        }

        for row in rows:
            action = row.get("action")
            if action and action not in admin_actions:
                actions.append(str(action))

        if not actions:
            return "ℹ️ Нет данных о кликах"

        total_clicks = len(actions)
        stats = Counter(actions)

        # Категории и действия
        categories = {
            "📋 Выбор плана": [
                "button_click_plan_30",
                "button_click_more_about_plan_30",
                "button_click_plan_500",
            ],
            "🔙 Назад": [
                "button_click_back_to_start_from_plan_30",
                "button_click_back_to_plan_30_from_details",
                "button_click_back_to_plan_30_from_russia_payment",
                "button_click_back_to_start_from_plan_500",
                "button_click_back_to_plan_500_from_russia_payment",
            ],
            "💳 Оплата": [
                "button_click_PAYMENT_RUSSIA_30",
                "button_click_PAYMENT_RUSSIA_500",
                "button_click_PAYMENT_STRIPE_30",
                "button_click_PAYMENT_STRIPE_500",
            ]
        }

        friendly_names = {
            "button_click_plan_30": "Выбор плана за 29$",
            "button_click_more_about_plan_30": "Подробнее о плане за 30",
            "button_click_plan_500": "Выбор плана за 490$",
            "button_click_back_to_start_from_plan_30": "Назад на старт из плана 29$",
            "button_click_back_to_plan_30_from_details": "Назад к плану за 29$ из 'Подробнее'",
            "button_click_back_to_plan_30_from_russia_payment": "Назад к плану за 29$ из оплаты для РФ",
            "button_click_back_to_plan_500_from_russia_payment": "Назад к плану за 490$ из оплаты для РФ",
            "button_click_back_to_start_from_plan_500": "Назад на старт из плана за 490$",
            "button_click_PAYMENT_RUSSIA_30": "Оплата для РФ (план за 29$)",
            "button_click_PAYMENT_RUSSIA_500": "Оплата для РФ (план за 490$)",
            "button_click_PAYMENT_STRIPE_30": "Оплата Stripe (план за 29$)",
            "button_click_PAYMENT_STRIPE_500": "Оплата Stripe (план за 490$)",
        }

        result = "📊 <b>Общая статистика кнопок</b>\n\n"

        for category, action_keys in categories.items():
            category_actions = {k: v for k, v in stats.items() if k in action_keys}
            if not category_actions:
                continue

            result += f"<b>{category}</b>\n"
            for action, count in sorted(category_actions.items(), key=lambda x: -x[1]):
                percent = (count / total_clicks) * 100
                friendly = friendly_names.get(action, action)
                result += f"• {friendly}: {count} ({percent:.1f}%)\n"
            result += "\n"

        # Прочие
        categorized = set(sum(categories.values(), []))
        uncategorized = {k: v for k, v in stats.items() if k not in categorized}

        """ basically clicks from admin panel, not important, result is: 📌 Прочее • button_click_to_start_from_admin_panel: 2 (9.1%)"""
        
        """ if uncategorized:
            result += "<b>📌 Прочее</b>\n"
            for action, count in sorted(uncategorized.items(), key=lambda x: -x[1]):
                percent = (count / total_clicks) * 100
                friendly = friendly_names.get(action, action)
                result += f"• {friendly}: {count} ({percent:.1f}%)\n" """

        result += f"\n<b>Всего кликов:</b> {total_clicks}"

        # Подсчёт уникальных пользователей за последний месяц
        try:
            one_month_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
            params = {
                "select": "user_id",
                "timestamp": f"gte.{one_month_ago}"
            }
            user_actions = await fetch_from_supabase("user_actions", params)
            unique_users = set(action['user_id'] for action in user_actions if 'user_id' in action and action['user_id'])
            result += f"\n<b>Уникальных пользователей за месяц:</b> {len(unique_users)}"
        except Exception as e:
            logger.error(f"Error getting unique users count: {e}")
            result += "\n⚠️ Не удалось загрузить данные об уникальных пользователях"

        return result

    except Exception as e:
        logger.error(f"Error in get_button_stats: {str(e)}", exc_info=True)
        return f"❌ Ошибка при получении статистики: {str(e)}"
   
# Статистика по пользователям
async def get_user_stats():
    try:
        rows = await fetch_from_supabase(
            "user_actions",
            {"select": "user_id,action,users!inner(username)"}
        )

        user_data = {}
        for row in rows:
            try:
                user_id = str(row.get("user_id"))
                if not user_id or user_id == "None":
                    continue

                action = row.get("action")
                if action is None:  # Skip None actions
                    continue

                username = row.get("users", {}).get("username", "")
                if not username:  # Skip empty usernames
                    continue

                if user_id not in user_data:
                    user_data[user_id] = {
                        "username": username,
                        "actions": []
                    }
                user_data[user_id]["actions"].append(str(action))

            except Exception as e:
                logger.error(f"Error processing row {row}: {str(e)}")
                continue

        if not user_data:
            return "ℹ️ Нет данных о действиях пользователей."

        result = "<b>👤 Статистика по пользователям</b>\n\n"
        for user_id, data in user_data.items():
            username = f" @{data['username']}" if data['username'] else ""
            result += f"👤 <b>User {user_id}{username}</b>:\n"

            stats = Counter(data["actions"])
            for action, count in stats.items():
                result += f"   • {action}: {count}\n"
            result += "\n"

        return result

    except Exception as e:
        logger.error(f"Error in get_user_stats: {str(e)}", exc_info=True)
        return f"❌ Ошибка при получении статистики пользователей: {str(e)}"
    
def patched_get_bot(self):
    return telegram_app.bot

Message.get_bot = patched_get_bot

def generate_session_id():
    return str(uuid.uuid4())

async def send_file_to_user(user_id, plan_type):
    """Отправляем разный набор файлов и сообщение в зависимости от плана"""
    import time
    send_start_time = time.time()
    
    try:
        logger.info("📨 ==========================================")
        logger.info("📨 SEND_FILE_TO_USER STARTED")
        logger.info("📨 ==========================================")
        logger.info(f"👤 User ID: {user_id} (type: {type(user_id)})")
        logger.info(f"📦 Plan Type: '{plan_type}' (type: {type(plan_type)})")
        logger.info(f"⏰ Start time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Validate inputs
        if not user_id:
            logger.error("❌ user_id is empty or None")
            return
        
        if not plan_type:
            logger.error("❌ plan_type is empty or None")
            return
        
        # Ensure user_id is integer
        try:
            user_id = int(user_id)
            logger.info(f"✅ Converted user_id to integer: {user_id}")
        except (ValueError, TypeError) as e:
            logger.error(f"❌ Cannot convert user_id to integer: {e}")
            return
        
        if plan_type == "30":
            logger.info("📦 ========== PROCESSING PLAN 30 ==========")
            plan_30_start = time.time()
            try:
                await telegram_app.bot.send_message(chat_id=user_id, text="Супер! Оплата прошла успешно ✅\n\nВаш персональный план питания уже в работе — вы получите его в течение 12 часов.\nА пока — вот доступ к курсу из 5 модулей, где только самое важное о похудении без диет и срывов.", parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Ошибка при отправке приветственного сообщения пользователю {user_id}: {e}", exc_info=True)
            
            folder_path = os.path.join(os.path.dirname(__file__), "files_30")
            
            # Создаем папку, если она не существует
            os.makedirs(folder_path, exist_ok=True)
            
            # ЖЕСТКО ЗАДАННЫЙ ПОРЯДОК файлов
            file_order = [
                "Почему вес не уходит",
                "Основа питания", 
                "Рецепты и лайфхаки",
                "Как сжигать жир",
                "Вода, гликоген, циклы",
                "Финальный - 10 главных правил",
                "Бонус модуль"
            ]
            
            # Получаем все файлы в папке (исключаем видеофайлы, которые отправляются отдельно)
            try:
                all_files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f)) and f not in ["course.mp4", "start.mp4"]]
                logger.info(f"Все файлы в папке {folder_path}: {all_files}")
            except Exception as e:
                logger.error(f"Ошибка при получении списка файлов в {folder_path}: {e}", exc_info=True)
                all_files = []
            
            # Отправляем course.mp4 сначала
            course_video_path = os.path.join(folder_path, "course.mp4")
            if os.path.exists(course_video_path):
                try:
                    with open(course_video_path, "rb") as video_obj:
                        await telegram_app.bot.send_video(
                            chat_id=user_id, 
                            video=video_obj
                        )
                    logger.info(f"Видео course.mp4 успешно отправлено пользователю {user_id}")
                    await asyncio.sleep(1.0)
                except Exception as e:
                    logger.error(f"Ошибка при отправке видео course.mp4: {e}", exc_info=True)
            
            # Отправляем файлы в строго заданном порядке
            for expected_name in file_order:
                # Ищем файл, который содержит ожидаемое название
                matching_file = None
                for file in all_files:
                    # Убираем расширение для сравнения
                    file_name_without_ext = os.path.splitext(file)[0]
                    if expected_name.lower() in file_name_without_ext.lower():
                        matching_file = file
                        break
                
                if matching_file:
                    file_path = os.path.join(folder_path, matching_file)
                    try:
                        with open(file_path, "rb") as file_obj:
                            await telegram_app.bot.send_document(
                                chat_id=user_id, 
                                document=file_obj
                            )
                        logger.info(f"Файл {matching_file} ('{expected_name}') успешно отправлен пользователю {user_id}")
                        # Увеличенная задержка для гарантии порядка
                        await asyncio.sleep(1.0)
                    except Exception as e:
                        logger.error(f"Ошибка при отправке файла {matching_file}: {e}", exc_info=True)
                        continue
                else:
                    logger.warning(f"Файл для '{expected_name}' не найден в папке {folder_path}")
                    # Отправляем сообщение о том, что файл не найден
                    try:
                        await telegram_app.bot.send_message(
                            chat_id=user_id,
                            text=f"⚠️ Файл '{expected_name}' временно недоступен. Мы исправим это в ближайшее время."
                        )
                    except:
                        pass
                
            try:
                await telegram_app.bot.send_message(
                    chat_id=user_id, 
                    text="👉[Заполнить анкету](https://docs.google.com/forms/d/e/1FAIpQLSeBMSz4nofrh_pUzcexSMaPC3pzQXwf5ADTXxNEQB9j3pijeQ/viewform)👈",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Ошибка при отправке ссылки на анкету пользователю {user_id}: {e}", exc_info=True)
                
        else:
            logger.info("💎 ========== PROCESSING PLAN 500 ==========")
            plan_500_start = time.time()
            logger.info(f"💎 Processing plan 500 (or other plan) for user {user_id}")
            try:
                message_start = time.time()
                await telegram_app.bot.send_message(
                    chat_id=user_id, 
                    text="Супер! Оплата прошла успешно ✅\n\nВ ближайшее время с вами лично свяжется Стас — вы договоритесь об удобном времени для первой консультации. После этого начнётся полное сопровождение: индивидуальный рацион, поддержка, правки, созвоны.\n\nСпасибо за доверие — теперь вы не одни в этом пути 💪",
                    parse_mode='Markdown'
                )
                message_duration = time.time() - message_start
                plan_500_duration = time.time() - plan_500_start
                logger.info(f"⏱️ Plan 500 message sent in {message_duration:.2f} seconds")
                logger.info(f"⏱️ Total plan 500 processing: {plan_500_duration:.2f} seconds")
                logger.info(f"✅ Successfully sent plan 500 message to user {user_id}")
            except Exception as e:
                error_duration = time.time() - plan_500_start
                logger.error(f"⏱️ Plan 500 error after {error_duration:.2f} seconds")
                logger.error(f"❌ Ошибка при отправке сообщения для плана 500 пользователю {user_id}: {e}", exc_info=True)
        
        # Log completion
        total_duration = time.time() - send_start_time
        logger.info(f"⏱️ TOTAL send_file_to_user duration: {total_duration:.2f} seconds")
        logger.info(f"✅ send_file_to_user completed for user {user_id} plan {plan_type}")
        logger.info("📨 ========== SEND_FILE_TO_USER COMPLETED ==========")
                
    except Exception as e:
        error_duration = time.time() - send_start_time
        logger.error(f"⏱️ Critical error after {error_duration:.2f} seconds")
        logger.error(f"❌ Критическая ошибка в send_file_to_user: {e}", exc_info=True)
        raise

async def process_telegram_update(data):
    try:
        update = Update.de_json(data, bot)
        logger.info(f"Received update: {update}")
        await telegram_app.process_update(update)
    except Exception as e:
        logger.error(f"Error processing update: {e}", exc_info=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'session_id' not in flask_session:
        flask_session['session_id'] = generate_session_id()
        flask_session.permanent = True

    keyboard = [
        [InlineKeyboardButton("План питания за 29$", callback_data="plan_30")],
        [InlineKeyboardButton("Личное ведение за 490$", callback_data="plan_500")],
        [InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)],
    ]
    
    user_id = update.effective_user.id
    admin_ids = get_admin_ids()
    
    for admin_id in admin_ids:
        try:
            if str(user_id) == str(admin_id):
                keyboard.append([InlineKeyboardButton("⚙️ Админ панель", callback_data="admin")])
            else:
                pass
        except Exception as e:
                    # Handle common Telegram errors gracefully
                    if "Chat not found" in str(e) or "Forbidden" in str(e):
                        logger.warning(f"Admin {admin_id} is unreachable (blocked bot or deleted chat): {e}")
                    else:
                        logger.error(f"Failed to send admin notification to {admin_id}: {e}", exc_info=True)
        
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        with open("files_30/start.mp4", "rb") as video:
            await update.message.reply_video(
                video=video,
                caption=(
                    "👋 Салют, мои вкусные!\n"
                    "Я — бот Стаса Голдман, я отведу тебя в мир стройности и эстетики🙌🏽\n\n"
                    "Хочешь похудеть без жёстких диет, но с удовольствием и результатом?\n"
                    "У нас есть план питания, который подойдёт именно тебе!\n\n👇 Выбери, что тебе ближе"
                ),
                reply_markup=reply_markup
            )
        

    except Exception as e:
        logger.error(f"Error sending start message: {e}", exc_info=True)
                
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks with enhanced tracking"""
    query = update.callback_query
    user = query.from_user
    await query.answer()
    
    
    # Initialize or get session ID
    if 'session_id' not in flask_session:
        flask_session['session_id'] = str(uuid.uuid4())
        flask_session.permanent = True
    
    session_id = flask_session['session_id']
    
    # Log the button click
    log_user_action(
        user_id=user.id,
        action=f'button_click_{query.data}',
        session_id=session_id,
        metadata={
            'message_id': query.message.message_id if query.message else None,
            'chat_id': query.message.chat_id if query.message else None,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'language_code': user.language_code
        }
    )
    
    try:
        if query.data == "plan_500":
            from config import is_test_mode, is_using_one_dollar_prices
            
            await query.message.delete()

            # Dynamic pricing text based on current mode
            if is_test_mode():
                plan_price_text = "🧪 ТЕСТОВЫЙ РЕЖИМ - $490 — с личным сопровождением Стаса"
            elif is_using_one_dollar_prices():
                plan_price_text = "🔥 ТЕСТ $1 - $1 для тестирования — сопровождение Стаса"
            else:
                plan_price_text = "$490 — с личным сопровождением Стаса"

            keyboard = [
                [
                    InlineKeyboardButton(
                        "🇪🇺🇺🇦🇧🇾 Оплата | Европа, Украина, Белорусь",
                        url=get_checkout_session_url(user, '500')
                    ),
                    InlineKeyboardButton(
                        "🇷🇺 Оплата | Россия",
                        callback_data='PAYMENT_RUSSIA_500'
                    )],
                [
                    InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)],
                [
                    InlineKeyboardButton("Назад", callback_data="back_to_start_from_plan_500")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await bot.send_message(
                chat_id=query.message.chat_id,
                text=(
                    "<b>«Плечом к плечу»</b>\n\n"
                    f"{plan_price_text}\n\n"
                    "Индивидуальный план питания от Стаса Голдман — под твою цель, предпочтения и здоровье.\n"
                    "Топовый вариант для максимального эффекта.\n\n"
                    "В эту сумму входит:\n"
                    "• Первая консультация\n"
                    "• Индивидуальный рацион с учётом ваших вкусов и пожеланий\n"
                    "• 4 созвона (один раз в неделю) со Стасом\n"
                    "• Внесение правок в меню\n"
                    "• Личная поддержка и мотивация на всём пути."
                ),
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        elif query.data in ['admin__toggle_stripe_mode', 'admin__refresh_stripe_status']:
            await handle_stripe_mode_actions(query, bot)
            
        elif query.data in ['admin__toggle_live_prices', 'admin__refresh_live_prices']:
            await handle_live_prices_actions(query, bot)
    
        elif query.data == "plan_30":
            from config import is_test_mode, is_using_one_dollar_prices
            
            await query.message.delete()

            # Dynamic pricing text based on current mode
            if is_test_mode():
                price_text = "<b>🧪 ТЕСТОВЫЙ РЕЖИМ - Обычная цена: $149. Сейчас — $29 для первых 100 клиентов.</b>\n\n"
            elif is_using_one_dollar_prices():
                price_text = "<b>🔥 ТЕСТ $1 - Обычная цена: $149. Сейчас — $1 для тестирования функций.</b>\n\n"
            else:
                price_text = "<b>Обычная цена: $149. Сейчас — $29 для первых 100 клиентов.</b>\n\n"

            keyboard = [
                [
                    InlineKeyboardButton("Подробнее", callback_data='more_about_plan_30'),
                    InlineKeyboardButton(
                        "🇪🇺🇺🇦🇧🇾 Оплата | Европа, Украина, Белорусь",
                        url=get_checkout_session_url(user, '30')
                    ),
                    InlineKeyboardButton(
                        "🇷🇺 Оплата | Россия",
                        callback_data='PAYMENT_RUSSIA_30'
                    )], 
                [
                    InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)
                    ],
                [InlineKeyboardButton("Назад", callback_data="back_to_start_from_plan_30")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await bot.send_message(
                chat_id=query.message.chat_id,
                text=(
                    price_text +
                    "План питания на 30 дней под все ваши потребности + курс из 5 модулей по похудению.\n"
                    "Без воды, без мотивации — только конкретика. Всё просто, понятно и самостоятельно."
                ),
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
                   
        elif query.data == "PAYMENT_RUSSIA_30":
            # Устанавливаем состояние пользователя
            user_states[user.id] = STATE_RUSSIA_PAYMENT_30
            
            # Show payment method selection
            keyboard = [
                [
                    InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)
                    ],
                [
                    InlineKeyboardButton("Назад", callback_data="back_to_plan_30_from_russia_payment")
                    ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text="29$ в рублях получается 2400руб.\n\nПосле оплаты , я вам вышлю анкету, её нужно будет как можно более подробно заполнить.\nИсходя из ваших ответов, будет составлен рацион.\n\n🇷🇺Реквизиты:\n\nНомер карты Тинькофф: 5536913810318853\n\nЛюбовь М\n\n<b>После оплаты, пожалуйста, отправьте скриншот успешной оплаты нашему менеджеру.</b>",
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        
        elif query.data == "PAYMENT_RUSSIA_500":
            # Устанавливаем состояние пользователя
            user_states[user.id] = STATE_RUSSIA_PAYMENT_500
            
            # Show payment method selection
            keyboard = [
                [
                    InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)
                    ],
                [
                    InlineKeyboardButton("Назад", callback_data="back_to_plan_500_from_russia_payment")
                    ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text="490$ в рублях получается 38500руб.\n\nПосле оплаты с вами лично свяжется Стас и вы назначите первую встречу.\n\n🇷🇺Реквизиты:\n\nНомер карты Тинькофф: 5536913810318853\n\nЛюбовь М\n\n<b>После оплаты, пожалуйста, отправьте отправьте скриншот успешной оплаты нашему менеджеру.</b>",
                reply_markup=reply_markup,
                parse_mode="HTML"
            )

        elif query.data == 'more_about_plan_30':
            
            keyboard = [
                [
                    InlineKeyboardButton("🇪🇺🇺🇦🇧🇾 Оплата | Европа, Украина, Белорусь", url=get_checkout_session_url(user, '30')),InlineKeyboardButton("🇷🇺 Оплата | Россия", callback_data='PAYMENT_RUSSIA_30'), ],
                [
                    InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK),
                    ],
                [
                    InlineKeyboardButton("Назад", callback_data="back_to_plan_30_from_details"),
                    ],
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = (
                "42 плана создано. 97% людей сказали: 'Это лучше, чем диета\n\n— Составляется по 30 вопросам (анкета)\n— Учитывает всё: вес, рост, цели, болезни (щитовидка, диабет, гастрит, давление и др.), аллергию, режим, вкусы, бюджет, стресс и даже город и ваши  магазины+цены.\n— Меню адаптировано под ваш день: готовка на 15–30 минут, без сложных продуктов\n— Можно оставить кофе, хлеб, сладкое — не убираем то, что вы любите\n— Список покупок + КБЖУ + недельный бюджет — всё готово  🙌\n\n📘 2. Курс из 5 модулей\n— Только суть: физиология, дефицит, частые ошибки, тарелка, самоконтроль\n— Без мотивации и болтовни. Всё, что должна знать женщина, чтобы понять, как худеет её тело\n— Можно пройти за пару вечеров, применять — сразу\n\n💸 И всё это — за $29\n(у других такие продукты стоят десятки тысяч, как консультации и курсы)\nА у нас — как поход в МакДак 🍔 но результат пожизненный!"
            )
            
            await query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        
        elif query.data == "back_to_start_from_plan_30":

            await query.message.delete()

            keyboard = [
                [InlineKeyboardButton("План питания за 29$", callback_data="plan_30")],
                [InlineKeyboardButton("Личное ведение за 490$", callback_data="plan_500")],
                [InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)],
            ]

            
            user_id = update.effective_user.id
            admin_ids = get_admin_ids()
            
            for admin_id in admin_ids:
                try:
                    if str(user_id) == str(admin_id):
                        keyboard.append([InlineKeyboardButton("⚙️ Админ панель", callback_data="admin")])
                    else:
                        pass
                except Exception as e:
                            # Handle common Telegram errors gracefully
                    if "Chat not found" in str(e) or "Forbidden" in str(e):
                        logger.warning(f"Admin {admin_id} is unreachable (blocked bot or deleted chat): {e}")
                    else:
                        logger.error(f"Failed to send admin notification to {admin_id}: {e}", exc_info=True)

            reply_markup = InlineKeyboardMarkup(keyboard)

            with open("files_30/start.mp4", "rb") as video:
                await bot.send_video(
                    chat_id=query.message.chat_id,
                    video=video,
                    caption=(
                        "👋 Салют, мои вкусные!\n"
                        "Я — бот Стаса Голдман, я отведу тебя в мир стройности и эстетики🙌🏽\n\n"
                        "Хочешь похудеть без жёстких диет, но с удовольствием и результатом?\n"
                        "У нас есть план питания, который подойдёт именно тебе!\n\n"
                        "👇 Выбери, что тебе ближе"
                    ),
                    reply_markup=reply_markup
                )
                
                

        elif query.data == "back_to_start_from_plan_500":

            await query.message.delete()

            keyboard = [
                [InlineKeyboardButton("План питания за 29$", callback_data="plan_30")],
                [InlineKeyboardButton("Личное ведение за 490$", callback_data="plan_500")],
                [InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)],
            ]

            user_id = update.effective_user.id
            admin_ids = get_admin_ids()
            
            for admin_id in admin_ids:
                try:
                    if str(user_id) == str(admin_id):
                        keyboard.append([InlineKeyboardButton("⚙️ Админ панель", callback_data="admin")])
                    else:
                        pass
                except Exception as e:
                            # Handle common Telegram errors gracefully
                    if "Chat not found" in str(e) or "Forbidden" in str(e):
                        logger.warning(f"Admin {admin_id} is unreachable (blocked bot or deleted chat): {e}")
                    else:
                        logger.error(f"Failed to send admin notification to {admin_id}: {e}", exc_info=True)

            reply_markup = InlineKeyboardMarkup(keyboard)

            with open("files_30/start.mp4", "rb") as video:
                await bot.send_video(
                    chat_id=query.message.chat_id,
                    video=video,
                    caption=(
                        "👋 Салют, мои вкусные!\n"
                        "Я — бот Стаса Голдман, я отведу тебя в мир стройности и эстетики🙌🏽\n\n"
                        "Хочешь похудеть без жёстких диет, но с удовольствием и результатом?\n"
                        "У нас есть план питания, который подойдёт именно тебе!\n\n"
                        "👇 Выбери, что тебе ближе"
                    ),
                    reply_markup=reply_markup
                )
                
                

        elif query.data == "back_to_plan_30_from_russia_payment":
            # Сбрасываем состояние пользователя
            user_states.pop(user.id, None)
            
            keyboard = [
                [
                    InlineKeyboardButton("Подробнее", callback_data='more_about_plan_30'),
                    InlineKeyboardButton("🇪🇺🇺🇦🇧🇾 Оплата | Европа, Украина, Белорусь", url=get_checkout_session_url(user, '30')),
                    InlineKeyboardButton("🇷🇺 Оплата | Россия", callback_data='PAYMENT_RUSSIA_30')
                ],
                [InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)],
                [InlineKeyboardButton("Назад", callback_data="back_to_start_from_plan_30")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.message.delete()
            await bot.send_message(
                chat_id=query.message.chat_id,
                text=(
                    "<b>Обычная цена: $149. Сейчас — $30 для первых 100 клиентов.</b>\n\n"
                    "План питания на 30 дней под все ваши потребности + курс из 5 модулей по похудению.\n"
                    "Без воды, без мотивации — только конкретика. Всё просто, понятно и самостоятельно."
                ),
                reply_markup=reply_markup,
                parse_mode="HTML"
            )

        elif query.data == "back_to_plan_30_from_details":

            keyboard = [
                [
                    InlineKeyboardButton("Подробнее", callback_data='more_about_plan_30'),
                    InlineKeyboardButton("🇪🇺🇺🇦🇧🇾 Оплата | Европа, Украина, Белорусь", url=get_checkout_session_url(user, '30')),
                    InlineKeyboardButton("🇷🇺 Оплата | Россия", callback_data='PAYMENT_RUSSIA_30')
                ],
                [InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)],
                [InlineKeyboardButton("Назад", callback_data="back_to_start_from_plan_30")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.message.delete()
            await bot.send_message(
                chat_id=query.message.chat_id,
                text=(
                    "<b>Обычная цена: $149. Сейчас — $30 для первых 100 клиентов.</b>\n\n"
                    "План питания на 30 дней под все ваши потребности + курс из 5 модулей по похудению.\n"
                    "Без воды, без мотивации — только конкретика. Всё просто, понятно и самостоятельно."
                ),
                reply_markup=reply_markup,
                parse_mode="HTML"
            )

        elif query.data == "back_to_plan_500_from_russia_payment":
            # Сбрасываем состояние пользователя
            user_states.pop(user.id, None)
            
            keyboard = [
                [
                    InlineKeyboardButton("🇪🇺🇺🇦🇧🇾 Оплата | Европа, Украина, Белорусь", url=get_checkout_session_url(user, '500')),
                    InlineKeyboardButton("🇷🇺 Оплата | Россия", callback_data='PAYMENT_RUSSIA_500')
                ],
                [InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)],
                [InlineKeyboardButton("Назад", callback_data="back_to_start_from_plan_500")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.message.delete()
            await bot.send_message(
                chat_id=query.message.chat_id,
                text=(
                    "<b>«Плечом к плечу»</b>\n\n"
                    "$490 — с личным сопровождением Стаса\n\n"
                    "Индивидуальный план питания от Стаса Голдман — под твою цель, предпочтения и здоровье.\n"
                    "Топовый вариант для максимального эффекта.\n\n"
                    "В эту сумму входит:\n"
                    "• Первая консультация\n"
                    "• Индивидуальный рацион с учётом ваших вкусов и пожеланий\n"
                    "• 4 созвона (один раз в неделю) со Стасом\n"
                    "• Внесение правок в меню\n"
                    "• Личная поддержка и мотивация на всём пути."
                ),
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            
        elif query.data == 'to_start_from_admin_panel':
            if 'session_id' not in flask_session:
                flask_session['session_id'] = generate_session_id()
                flask_session.permanent = True

            keyboard = [
                [InlineKeyboardButton("План питания за 29$", callback_data="plan_30")],
                [InlineKeyboardButton("Личное ведение за 490$", callback_data="plan_500")],
                [InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)],
            ]

            user_id = update.effective_user.id
            admin_ids = get_admin_ids()
            
            for admin_id in admin_ids:
                try:
                    if str(user_id) == str(admin_id):
                        keyboard.append([InlineKeyboardButton("⚙️ Админ панель", callback_data="admin")])
                    else:
                        pass
                except Exception as e:
                            # Handle common Telegram errors gracefully
                    if "Chat not found" in str(e) or "Forbidden" in str(e):
                        logger.warning(f"Admin {admin_id} is unreachable (blocked bot or deleted chat): {e}")
                    else:
                        logger.error(f"Failed to send admin notification to {admin_id}: {e}", exc_info=True)

            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.message.delete()

            try:
                with open("files_30/start.mp4", "rb") as video:
                    await bot.send_video(
                        chat_id=query.message.chat_id,
                        video=video,
                        caption=(
                            "👋 Салют, мои вкусные!\n"
                            "Я — бот Стаса Голдман, я отведу тебя в мир стройности и эстетики🙌🏽\n\n"
                            "Хочешь похудеть без жёстких диет, но с удовольствием и результатом?\n"
                            "У нас есть план питания, который подойдёт именно тебе!\n\n👇 Выбери, что тебе ближе"
                        ),
                        reply_markup=reply_markup
                    )
            except Exception as e:
                logger.error(f"Error sending start message: {e}", exc_info=True)
                
        elif query.data == 'admin':
            await handle_admin_panel(query, user, bot)
            
        elif query.data.startswith('premium_users_page_'):
            try:
                page = int(query.data.split('_')[-1])
                premium_users = await get_premium_users()
                users_per_page = 10
                total_pages = (len(premium_users) + users_per_page - 1) // users_per_page
                
                if 0 <= page < total_pages:
                    await show_premium_users_page(query, premium_users, page, users_per_page, total_pages)
                else:
                    await query.answer("Неверный номер страницы.", show_alert=True)
            except Exception as e:
                logger.error(f"Error handling premium users pagination: {str(e)}", exc_info=True)
                await query.answer("Произошла ошибка при загрузке страницы.", show_alert=True)

        elif query.data == 'admin__stats':
            await handle_admin_stats(query)
            
        elif query.data == 'admin__test_mode':
            await handle_admin_stripe_test_mode(query, bot)

        elif query.data == 'admin__live_prices':
            await handle_admin_live_prices(query, bot)
    except Exception as e:
        logger.error(f"Error handling button callback '{query.data}' for user {user.id}: {e}", exc_info=True)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик обычных сообщений от пользователей"""
    user = update.effective_user
    user_id = user.id
    
    
    # Проверяем, находится ли пользователь в состоянии оплаты России
    if user_id in user_states:
        current_state = user_states[user_id]
        
        # Создаем кнопку "Связаться с менеджером" 
        keyboard = [[InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if current_state in [STATE_RUSSIA_PAYMENT_30, STATE_RUSSIA_PAYMENT_500]:
            # Определяем кнопку "Назад" в зависимости от плана
            if current_state == STATE_RUSSIA_PAYMENT_30:
                back_callback = "back_to_plan_30_from_russia_payment"
            else:  # STATE_RUSSIA_PAYMENT_500
                back_callback = "back_to_plan_500_from_russia_payment"
            
            # Создаем клавиатуру с кнопками "Менеджер" и "Назад"
            keyboard = [
                [InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)],
                [InlineKeyboardButton("Назад", callback_data=back_callback)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Проверяем тип сообщения
            if update.message.text and not (update.message.photo or update.message.video or update.message.document):
                # Текстовое сообщение
                await update.message.reply_text(
                    "Спасибо за ваше сообщение! Пожалуйста, отправьте скриншот успешной оплаты нашему менеджеру для подтверждения.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)], [InlineKeyboardButton("Назад", callback_data=back_callback)]]),
                    parse_mode="HTML"
                )
                
            else:
                # Медиа-сообщение (фото, видео, документ)
                await update.message.reply_text(
                    "Спасибо за ваш файл! Но нужно отправить его именно нашему менеджеру, иначе вы не сможете получить ваши файлы. Пожалуйста, свяжитесь с менеджером нажав на кнопку под этим сообщением и отправьте скриншот вашего чека ему.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Связаться с менеджером", url=SUPPORT_LINK)], [InlineKeyboardButton("Назад", callback_data=back_callback)]]),
                    parse_mode="HTML"
                )
                
            
            # Логируем действие пользователя
            if 'session_id' not in flask_session:
                flask_session['session_id'] = str(uuid.uuid4())
                flask_session.permanent = True
            
            session_id = flask_session['session_id']
            action_type = "text_message" if update.message.text and not (update.message.photo or update.message.video or update.message.document) else "media_message"
            
            log_user_action(
                user_id=user.id,
                action=f'russia_payment_message_{action_type}_{current_state}',
                session_id=session_id,
                metadata={
                    'message_id': update.message.message_id,
                    'chat_id': update.message.chat_id,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'language_code': user.language_code,
                    'has_photo': bool(update.message.photo),
                    'has_video': bool(update.message.video),
                    'has_document': bool(update.message.document),
                    'message_text_preview': update.message.text[:100] if update.message.text else None
                }
            )

# Add command and callback handlers
telegram_app.add_handler(CommandHandler("start", start))

# Admin handlers now integrated directly in telegram_bot.py
# for handler in get_admin_handlers():
#     telegram_app.add_handler(handler)

telegram_app.add_handler(CallbackQueryHandler(button_handler))

# Add message handler (должен быть после всех остальных обработчиков)
telegram_app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL, message_handler))

def init_telegram_app(loop):
    try:
        # Create a new event loop for the background tasks
        background_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(background_loop)
        
        # Initialize the bot in the background loop
        background_loop.run_until_complete(telegram_app.initialize())
        background_loop.run_until_complete(telegram_app.start())
        
        # Start a background task to keep the loop running
        def run_loop():
            asyncio.set_event_loop(background_loop)
            background_loop.run_forever()
            
        import threading
        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()
        
        logger.info("Telegram app and bot initialized successfully")
        return background_loop
        
    except Exception as e:
        logger.error(f"Error initializing telegram app: {e}", exc_info=True)
        raise
