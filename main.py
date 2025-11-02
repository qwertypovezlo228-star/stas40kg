import os
import asyncio
from dotenv import load_dotenv
load_dotenv()
from flask import request, jsonify, Flask
from config import *
from telegram_bot import *
from stripe_handlers import *
from datetime import timedelta
import logging
import threading

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger(__name__)

# Создаем Flask приложение
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Создаем event loop
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Флаг для отслеживания инициализации бота
bot_initialized = False

async def init_telegram_app():
    """Initialize and start the Telegram application."""
    global bot_initialized
    try:
        logger.info("Initializing Telegram application...")
        await telegram_app.initialize()
        logger.info("Starting Telegram application...")
        await telegram_app.start()
        logger.info("Telegram application started successfully")
        bot_initialized = True
        return True
    except Exception as e:
        logger.error(f"Failed to start Telegram app: {e}", exc_info=True)
        bot_initialized = False
        raise

def run_async_loop():
    """Run the async event loop in a separate thread."""
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    except Exception as e:
        logger.error(f"Error in async loop: {e}", exc_info=True)
    finally:
        loop.close()

# Запускаем event loop в отдельном потоке
threading.Thread(target=run_async_loop, daemon=True).start()

# Запускаем инициализацию telegram_app в глобальном loop и ждем завершения
future = asyncio.run_coroutine_threadsafe(init_telegram_app(), loop)
try:
    future.result(timeout=30)  # Ждем максимум 30 секунд
    logger.info("Bot initialization completed successfully")
except Exception as e:
    logger.error(f"Bot initialization failed: {e}")
    raise

@app.route('/webhook/<token>', methods=['POST'])
def telegram_webhook_with_token(token=None):
    try:
        data = request.get_json(force=True)
        # Запускаем асинхронный обработчик в глобальном loop
        future = asyncio.run_coroutine_threadsafe(process_telegram_update(data), loop)
        # Не ждём, чтобы не блокировать Flask, просто запускаем
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Error in telegram_webhook: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    try:
        data = request.get_json(force=True)
        # Запускаем асинхронный обработчик в глобальном loop
        future = asyncio.run_coroutine_threadsafe(process_telegram_update(data), loop)
        # Не ждём, чтобы не блокировать Flask, просто запускаем
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Error in telegram_webhook: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    try:
        url = f"{WEBHOOK_URL.rstrip('/')}/webhook"
        # Ждём результат, чтобы точно знать что вебхук установлен
        asyncio.run_coroutine_threadsafe(telegram_app.bot.set_webhook(url=url), loop).result()
        logger.info(f"Webhook set to {url}")
        return jsonify({"status": "webhook set", "url": url})
    except Exception as e:
        logger.error(f"Error setting webhook: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/clear_webhook', methods=['GET'])
def clear_webhook():
    try:
        asyncio.run_coroutine_threadsafe(telegram_app.bot.delete_webhook(drop_pending_updates=True), loop).result()
        logger.info("Webhook deleted (pending updates dropped)")
    except Exception as e:
        logger.error(f"Error deleting webhook: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    return set_webhook()


@app.route('/stripe_webhook', methods=['POST'])
def stripe_webhook_route():
    try:
        # Не обрабатываем данные заранее, пусть stripe_handlers это делает
        logger.info("Received Stripe webhook")
        
        # Импортируем и вызываем обработчик
        from stripe_handlers import stripe_webhook as handle_stripe_webhook
        response = handle_stripe_webhook()
        
        # Log the response
        logger.info(f"Webhook processed successfully")
        return response
    except Exception as e:
        logger.error(f"Error in stripe_webhook: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500
   
@app.route('/webhook_info', methods=['GET'])
def webhook_info():
    try:
        webhook_info_data = asyncio.run_coroutine_threadsafe(telegram_app.bot.get_webhook_info(), loop).result()
        return jsonify({
            "url": webhook_info_data.url,
            "has_custom_certificate": webhook_info_data.has_custom_certificate,
            "pending_update_count": webhook_info_data.pending_update_count,
            "last_error_date": webhook_info_data.last_error_date.isoformat() if webhook_info_data.last_error_date else None,
            "last_error_message": webhook_info_data.last_error_message,
            "max_connections": webhook_info_data.max_connections,
            "allowed_updates": webhook_info_data.allowed_updates
        })
    except Exception as e:
        logger.error(f"Error getting webhook info: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/bot_status', methods=['GET'])
def bot_status():
    try:
        bot_info = asyncio.run_coroutine_threadsafe(telegram_app.bot.get_me(), loop).result()
        webhook_info_data = asyncio.run_coroutine_threadsafe(telegram_app.bot.get_webhook_info(), loop).result()
        
        return jsonify({
            "bot_initialized": bot_initialized,
            "bot_info": {
                "username": bot_info.username,
                "first_name": bot_info.first_name,
                "id": bot_info.id
            },
            "webhook": {
                "url": webhook_info_data.url,
                "pending_updates": webhook_info_data.pending_update_count,
                "last_error_message": webhook_info_data.last_error_message
            },
            "handlers_count": len(telegram_app.handlers),
            "expected_webhook_url": f"{WEBHOOK_URL.rstrip('/')}/webhook"
        })
    except Exception as e:
        logger.error(f"Error getting bot status: {e}", exc_info=True)
        return jsonify({"error": str(e), "bot_initialized": bot_initialized}), 500
