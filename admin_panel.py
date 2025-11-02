import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler

from database_postgres import (
    get_user_actions, 
    get_admin_dashboard_stats,
    get_recent_users,
    get_payment_stats,
    get_payments_by_user
)
from config import ADMIN_ID

logger = logging.getLogger(__name__)

def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return str(user_id) == str(ADMIN_ID)

def get_admin_keyboard():
    """Admin panel keyboard"""
    keyboard = [
        [InlineKeyboardButton("📊 Общая статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("👥 Пользователи", callback_data='admin_users')],
        [InlineKeyboardButton("💳 Платежи", callback_data='admin_payments')],
        [InlineKeyboardButton("📈 Воронка продаж", callback_data='admin_funnel')],
        [InlineKeyboardButton("📋 Действия пользователей", callback_data='admin_user_actions')],
        [InlineKeyboardButton("🔄 Обновить", callback_data='admin_refresh')],
        [InlineKeyboardButton("🔙 Назад", callback_data='back')]
    ]
    return InlineKeyboardMarkup(keyboard)

def format_stats_for_display(stats: Dict[str, Any]) -> str:
    """Format statistics for display in the admin panel"""
    message = "📊 *Панель администратора*\n\n"
    
    # User statistics
    message += "👥 *Пользователи*\n"
    message += f"• Всего пользователей: *{stats['users']['total']}*\n"
    message += f"• Активных за 7 дней: *{stats['active_users_7d']}*\n\n"
    
    # Payment statistics
    payment_stats = stats.get('payment_stats', {})
    message += "💳 *Платежи*\n"
    message += f"• Всего платежей: *{payment_stats.get('total_payments', 0)}*\n"
    message += f"• Общий доход: *${payment_stats.get('total_revenue', 0):.2f}*\n"
    
    # Revenue by plan
    revenue_by_plan = payment_stats.get('revenue_by_plan', {})
    if revenue_by_plan:
        message += "\n*Доход по тарифам:*\n"
        for plan, amount in revenue_by_plan.items():
            message += f"• Тариф {plan}: *${amount:.2f}*\n"
    
    # Recent payments
    recent_payments = payment_stats.get('recent_payments', [])[:5]
    if recent_payments:
        message += "\n*Последние платежи:*\n"
        for payment in recent_payments:
            amount = payment.get('amount', 0)
            plan = payment.get('plan', 'N/A')
            email = payment.get('email', 'N/A')
            paid_at = payment.get('paid_at', '')
            
            # Format the date
            try:
                dt = datetime.fromisoformat(paid_at.replace('Z', '+00:00'))
                date_str = dt.strftime('%d.%m.%Y %H:%M')
            except (ValueError, AttributeError):
                date_str = 'N/A'
                
            message += f"• {email} - ${amount:.2f} (тариф {plan}) - {date_str}\n"
    
    return message
    message += "\n*Последние действия:*\n"
    for action in actions[:10]:  # Show last 10 actions
        timestamp = action.get('timestamp', '')
        user_id = action.get('user_id', 'N/A')
        action_type = action.get('action', 'unknown')
        
        # Format timestamp if it exists
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                timestamp_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, AttributeError):
                timestamp_str = timestamp
        else:
            timestamp_str = 'N/A'
            
        message += f"`{timestamp_str}` {action_type} (user: {user_id})\n"
    
    return message

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin command - show admin panel"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        if update.callback_query:
            await update.callback_query.answer("🚫 У вас нет прав доступа к этой панели.", show_alert=True)
        elif update.message:
            await update.message.reply_text("🚫 У вас нет прав доступа к этой команде.")
        return
    
    reply_text = "👨‍💻 Панель администратора"
    reply_markup = get_admin_keyboard()
    
    if update.callback_query:
        await update.callback_query.edit_message_text(reply_text, reply_markup=reply_markup)
    elif update.message:
        await update.message.reply_text(reply_text, reply_markup=reply_markup)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin panel button clicks"""
    query = update.callback_query
    await query.answer()
    
    if not is_admin(query.from_user.id):
        await query.message.reply_text("У вас нет прав доступа к панели администратора.")
        return
    
    action = query.data
    
    try:
        if action == 'admin_stats':
            # Get comprehensive statistics
            stats = get_admin_dashboard_stats()
            message = format_stats_for_display(stats)
            
            await query.edit_message_text(
                message,
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
        
        elif action == 'admin_users':
            # Show recent users
            users = get_recent_users(10)
            message = "👥 *Последние пользователи*\n\n"
            
            for user in users:
                username = f"@{user['username']}" if user.get('username') else "(нет username)"
                name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                created_at = user.get('created_at', '')
                if created_at and len(created_at) >= 10:
                    created_date = created_at[:10]
                else:
                    created_date = 'N/A'
                
                message += f"• {name} {username} - {created_date}\n"
            
            await query.edit_message_text(
                message,
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif action == 'admin_payments':
            # Show payment statistics
            payment_stats = get_payment_stats()
            
            message = "💳 *Статистика платежей*\n\n"
            message += f"• Всего платежей: *{payment_stats.get('total_payments', 0)}*\n"
            message += f"• Общий доход: *${payment_stats.get('total_revenue', 0):.2f}*\n\n"
            
            # Revenue by plan
            revenue_by_plan = payment_stats.get('revenue_by_plan', {})
            if revenue_by_plan:
                message += "*Доход по тарифам:*\n"
                for plan, amount in revenue_by_plan.items():
                    message += f"• Тариф {plan}: *${amount:.2f}*\n"
            
            # Recent payments
            recent_payments = payment_stats.get('recent_payments', [])[:10]
            if recent_payments:
                message += "\n*Последние платежи:*\n"
                for payment in recent_payments:
                    amount = payment.get('amount', 0)
                    plan = payment.get('plan', 'N/A')
                    email = payment.get('email', 'N/A')
                    paid_at = payment.get('paid_at', '')
                    
                    # Format the date
                    try:
                        dt = datetime.fromisoformat(paid_at.replace('Z', '+00:00'))
                        date_str = dt.strftime('%d.%m.%Y %H:%M')
                    except (ValueError, AttributeError):
                        date_str = 'N/A'
                        
                    message += f"• {email} - ${amount:.2f} (тариф {plan}) - {date_str}\n"
            
            await query.edit_message_text(
                message,
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
        
        elif action == 'admin_funnel':
            # Show sales funnel
            message = "📈 *Воронка продаж*\n\n"
            message += "В разработке..."
            
            await query.edit_message_text(
                message,
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif action == 'admin_refresh':
            # Refresh the admin panel
            await admin_command(update, context)
        
        elif action == 'admin_user_actions':
            # Show recent user actions
            actions = get_user_actions(limit=20)
            if not actions:
                message = "Нет данных о действиях пользователей."
            else:
                # Group actions by type and count occurrences
                action_counts = {}
                for action in actions:
                    action_type = action.get('action', 'unknown')
                    action_counts[action_type] = action_counts.get(action_type, 0) + 1
                
                # Format the message
                message = "📋 *Статистика действий пользователей*\n\n"
                
                # Add summary by action type
                message += "*Количество действий по типам:*\n"
                for action_type, count in sorted(action_counts.items(), key=lambda x: x[1], reverse=True):
                    message += f"• {action_type}: *{count}*\n"
                
                # Add recent actions
                message += "\n*Последние действия:*\n"
                for action in actions[:10]:
                    user_id = action.get('user_id', 'N/A')
                    action_type = action.get('action', 'N/A')
                    timestamp = action.get('timestamp', '')
                    
                    # Format the date
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        date_str = dt.strftime('%d.%m %H:%M')
                    except (ValueError, AttributeError):
                        date_str = 'N/A'
                    
                    message += f"• {date_str} - {user_id}: {action_type}\n"
            
            await query.edit_message_text(
                message,
                reply_markup=get_admin_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
    
    except Exception as e:
        logger.error(f"Error in admin_callback: {str(e)}", exc_info=True)
        await query.edit_message_text(
            f"❌ Произошла ошибка при обработке запроса.\n\n{str(e)}",
            reply_markup=get_admin_keyboard()
        )

def main():
    # Токен из переменных окружения
    TOKEN = os.getenv('BOT_TOKEN')
    if not TOKEN:
        logger.error(f"Ошибка: не задан BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern='^admin_'))

    logger.info(f"Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()