#!/usr/bin/env python3
"""
Temporary script to clear webhook and reset it.
Run this once to clear pending updates.
"""
import os
import asyncio
from telegram import Bot
import logging

logger = logging.getLogger(__name__)

async def clear_and_reset_webhook():
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        logger.error("TELEGRAM_TOKEN not found")
        return
    
    bot = Bot(token=token)
    
    # Delete webhook to clear pending updates
    logger.info("Deleting webhook...")
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Set new webhook
    webhook_url = f"https://minys40kg-tg-bot-90475322074f.herokuapp.com/webhook/{token}"
    logger.info(f"Setting webhook to: {webhook_url}")
    await bot.set_webhook(url=webhook_url)
    
    logger.info("Webhook reset successfully!")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    asyncio.run(clear_and_reset_webhook())
