#!/usr/bin/env python3
"""
Скрипт для исправления payment_status = null на 'unpaid' для существующих пользователей
"""

import asyncio
import aiohttp
import os
from dotenv import load_dotenv
import logging
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

load_dotenv()

# Используем значения из Heroku (можно заменить на os.getenv если нужно)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADMIN_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json"
}

async def fix_payment_status():
    """
    Обновляет всех пользователей с payment_status = null на 'unpaid'
    """
    try:
        async with aiohttp.ClientSession() as session:
            # Обновляем всех пользователей где payment_status is null
            update_url = f"{SUPABASE_URL}/rest/v1/users?payment_status=is.null"
            
            payload = {
                "payment_status": "unpaid"
            }
            
            logger.info("🔄 Обновляем пользователей с payment_status = null на 'unpaid'...")
            
            async with session.patch(
                update_url,
                headers=ADMIN_HEADERS,
                json=payload
            ) as response:
                if response.status == 204:
                    logger.info("✅ Пользователи успешно обновлены!")
                else:
                    text = await response.text()
                    logger.error(f"❌ Ошибка обновления: Status {response.status}, Response: {text}")
                    return False
            
            # Проверим результат
            check_url = f"{SUPABASE_URL}/rest/v1/users?select=user_id,payment_status&payment_status=eq.unpaid"
            async with session.get(check_url, headers=ADMIN_HEADERS) as check_response:
                if check_response.status == 200:
                    users = await check_response.json()
                    logger.info(f"📊 Найдено {len(users)} пользователей со статусом 'unpaid'")
                    return True
                else:
                    logger.error(f"❌ Ошибка проверки: {check_response.status}")
                    return False
                    
    except Exception as e:
        logger.error(f"❌ Ошибка в fix_payment_status: {e}")
        return False

if __name__ == "__main__":
    print("Запуск исправления payment_status...")
    success = asyncio.run(fix_payment_status())
    if success:
        print("Исправление завершено успешно!")
    else:
        print("Произошла ошибка при исправлении!")