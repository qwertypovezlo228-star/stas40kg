import os
import asyncio
import logging
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram_bot import bot
from config import SUPABASE_URL, JOIN_GROUP_LINK
from telegram_bot import fetch_from_supabase
from datetime import timezone
import aiohttp
import json
from database_postgres import ADMIN_HEADERS

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def get_payments_for_30d_followup():
    """
    Получаем платежи за plan 30/basic, оплаченные >30 дней назад,
    для которых ещё не отправляли уведомление (notified_after_30d = false)
    """
    try:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=30)

        payments = await fetch_from_supabase(
            "payments",
            {
                "select": "id, telegram_user_id, created_at, metadata, notified_after_30d",
                "status": "eq.paid",
                "payment_method": "eq.card",
                "notified_after_30d": "eq.false"
            }
        )

        result = []
        for payment in payments:
            try:
                telegram_user_id = payment.get("telegram_user_id")
                created_at_str = payment.get("created_at")
                metadata = payment.get("metadata")
                notified_flag = payment.get("notified_after_30d")

                if not telegram_user_id or not created_at_str:
                    continue

                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                if created_at > cutoff:
                    continue  # платеж моложе 30 дней

                metadata_dict = json.loads(metadata) if metadata else {}

                plan = metadata_dict.get("plan")
                if plan not in ("30", "basic"):
                    continue

                if notified_flag:
                    continue  # уже уведомляли

                result.append({
                    "payment_id": payment.get("id"),
                    "user_id": telegram_user_id,
                    "metadata": json.dumps(metadata_dict),
                })

            except Exception as e:
                logger.warning(f"⚠️ Ошибка при обработке платежа: {e}")

        logger.info(f"📦 Найдено платежей для follow-up: {len(result)}")
        return result

    except Exception as e:
        logger.error(f"❌ Ошибка при получении платежей для 30-дневного follow-up: {e}")
        return []

async def send_30d_followup(payment_data: dict):
    user_id = payment_data["user_id"]
    existing_metadata = {}

    if payment_data["metadata"]:
        try:
            existing_metadata = json.loads(payment_data["metadata"])
        except Exception:
            pass

    try:
        message = (
            "<b>🌿 Прошёл месяц с момента получения вашего плана питания</b>\n\n"
            "Надеемся, он был для вас полезным и помог сделать шаг навстречу себе.\n"
            "Нам очень важно услышать ваше мнение — что получилось, что хотелось бы улучшить.\n\n"
            "<b>Поделитесь коротким отзывом</b> — это поможет нам расти и делать планы ещё лучше:\n🔘 Оставить отзыв\n\n"
            "А если вы хотите продолжить —\nмы с радостью подготовим новый план с учётом ваших изменений и прогресса.\n\n"
            "🔁 Заказать ещё один план\n\n"
            "Благодарим вас за доверие.\n"
            "Мы рядом, если нужно сопровождение, поддержка или обновлённый маршрут 🌸"
        )

        keyboard = [
            [InlineKeyboardButton("Оставить отзыв", url=JOIN_GROUP_LINK)],
            [InlineKeyboardButton("Заказать ещё один план", callback_data="plan_30")],
        ]
        markup = InlineKeyboardMarkup(keyboard)

        await bot.send_message(
            chat_id=user_id,
            text=message,
            reply_markup=markup,
            parse_mode='HTML'
        )

        logger.info(f"✅ Follow-up отправлен пользователю {user_id} для payment_id {payment_data['payment_id']}")

        # Обновляем в БД флаг уведомления по конкретному платежу
        await mark_payment_notified(payment_data["payment_id"])

    except Exception as e:
        logger.warning(f"⚠️ Не удалось отправить follow-up пользователю {user_id}: {e}")


async def mark_payment_notified(payment_id: str):
    try:
        url = f"{SUPABASE_URL}/rest/v1/payments?id=eq.{payment_id}"
        headers = dict(ADMIN_HEADERS)
        headers["Prefer"] = "return=minimal"

        payload = {
            "notified_after_30d": True
        }

        async with aiohttp.ClientSession() as session:
            async with session.patch(
                url,
                headers=headers,
                json=payload
            ) as response:
                if response.status == 204:
                    logger.info(f"✅ Обновлен флаг notified_after_30d для payment_id {payment_id}")
                else:
                    text = await response.text()
                    logger.warning(f"⚠️ Не удалось обновить флаг notified_after_30d: Status {response.status}, Response: {text}")
    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении флага notified_after_30d: {e}")



async def get_unpaid_inactive_users():
    try:
        if not SUPABASE_URL or not os.getenv('SUPABASE_SERVICE_ROLE'):
            logger.error("❌ Missing Supabase configuration")
            return []

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


async def send_reminder(user_id: int):
    try:
        keyboard = [
            [InlineKeyboardButton("План питания за 29$", callback_data="plan_30")],
            [InlineKeyboardButton("Личное ведение за 490$", callback_data="plan_500")],
        ]
        markup = InlineKeyboardMarkup(keyboard)

        message = (
            "<b>📊 Уже 42 плана создано. А ваш — ещё нет.</b>\n\n"
            "97% клиентов, заказавших план, сказали:\n<b>«Это легче, чем диета. И работает.»</b>\n\n"
            "А вы всё ещё думаете?\n\n"
            "Каждый день промедления — это день без энергии,\n"
            "без лёгкости, без настоящей версии себя.\n\n"
            "<b>Пора сделать шаг.\nПока вы думаете — другие меняются.</b>"
        )

        await bot.send_message(
            chat_id=user_id,
            text=message,
            reply_markup=markup,
            parse_mode='HTML'
        )

        logger.info(f"✅ Уведомление через сутки для неоплативших юзеров: Отправлено напоминание пользователю {user_id}")

        await update_user_field(user_id, {"did_user_get_notification_after_24h_without_payment": True})

    except Exception as e:
        logger.warning(f"⚠️ Уведомление через сутки для неоплативших юзеров: Не удалось отправить сообщение пользователю {user_id}: {e}")

async def update_user_field(user_id: int, fields: dict):
    """
    Обновляет конкретные поля пользователя по user_id
    """
    try:
        url = f"{SUPABASE_URL}/rest/v1/users?user_id=eq.{user_id}"
        async with aiohttp.ClientSession() as session:
            response = await session.patch(
                url,
                headers=ADMIN_HEADERS,
                json=fields
            )
            if response.status == 204:
                logger.info(f"✅ Обновлён пользователь {user_id}: {fields}")
            else:
                logger.warning(f"⚠️ Ошибка при обновлении {user_id} — Status {response.status}")
    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении пользователя {user_id}: {e}")


async def main():
    # Логика для уведомления по неоплаченным (оставляем без изменений)
    user_ids = await get_unpaid_inactive_users()
    logger.info(f"🔍 Найдено неоплативших пользователей: {len(user_ids)}")
    tasks = [send_reminder(uid) for uid in user_ids]

    # Логика для follow-up спустя 30 дней после оплаты плана за 30
    payments_to_notify = await get_payments_for_30d_followup()
    logger.info(f"📅 Платежей для follow-up после 30 дней: {len(payments_to_notify)}")
    tasks += [send_30d_followup(payment) for payment in payments_to_notify]

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    print("🚀 Starting reminder_bot...")
    asyncio.run(main())