#!/usr/bin/env python3
"""
Изолированный тест для функции get_unpaid_inactive_users
"""

import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta, timezone
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

ADMIN_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json"
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fetch_from_supabase(table, params=None):
    """Простая функция для получения данных из Supabase"""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=ADMIN_HEADERS, params=params) as response:
            if response.status == 200:
                return await response.json()
            else:
                logger.error(f"Ошибка получения данных: {response.status}")
                return []

async def get_unpaid_inactive_users():
    """Копия функции из reminder_bot.py"""
    try:
        users = await fetch_from_supabase(
            "users",
            {
                "select": "user_id, payment_status, last_activity, did_user_get_notification_after_24h_without_payment",
                "payment_status": "eq.unpaid"
            }
        )

        if not users:
            logger.info("ℹ️ Уведомление через сутки для неоплативших юзеров: Нет пользователей со статусом 'unpaid'")
            return []

        inactive_users = []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=1)
        
        logger.info(f"🕐 Текущее время: {now}")
        logger.info(f"🕐 Граница cutoff (24ч назад): {cutoff}")

        for user in users:
            user_id = user.get("user_id")
            last_activity_str = user.get("last_activity")
            already_notified = user.get("did_user_get_notification_after_24h_without_payment", False)
            
            logger.info(f"👤 Проверяем пользователя {user_id}: last_activity={last_activity_str}, уже уведомлен={already_notified}")
            
            if not last_activity_str:
                logger.warning(f"⚠️ У пользователя {user_id} отсутствует last_activity")
                continue

            try:
                last_activity = datetime.fromisoformat(last_activity_str.replace("Z", "+00:00"))
                logger.info(f"👤 Пользователь {user_id}: last_activity={last_activity}, старше cutoff={last_activity < cutoff}")
                
                if last_activity < cutoff and not already_notified:
                    logger.info(f"✅ Пользователь {user_id} подходит для уведомления")
                    inactive_users.append(user_id)
                elif already_notified:
                    logger.info(f"⏭️ Пользователь {user_id} уже получал уведомление")
                else:
                    logger.info(f"⏭️ Пользователь {user_id} еще слишком активен")
                    
            except Exception as parse_err:
                logger.warning(f"⚠️ Уведомление через сутки для неоплативших юзеров: Не удалось обработать дату: {last_activity_str} — {parse_err}")

        return inactive_users

    except Exception as e:
        logger.error(f"❌ Уведомление через сутки для неоплативших юзеров: Ошибка при получении пользователей: {e}", exc_info=True)
        return []

async def main():
    print("Тестирование поиска неоплативших неактивных пользователей...")
    user_ids = await get_unpaid_inactive_users()
    print(f"Найдено пользователей для уведомления: {len(user_ids)}")
    if user_ids:
        print(f"ID пользователей: {user_ids}")
    else:
        print("Никто не подходит для уведомлений")

if __name__ == "__main__":
    asyncio.run(main())