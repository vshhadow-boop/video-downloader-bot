#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Минимальная рабочая версия для Render
"""

import os
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask, request
import threading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class MinimalBot:
    def __init__(self, token: str, webhook_url: str):
        self.token = token
        self.webhook_url = webhook_url
        self.application = Application.builder().token(token).build()
        
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("ping", self.ping_command))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🎬 Минимальный бот работает!\n\n"
            "📱 Команды:\n"
            "/start - начать\n"
            "/ping - проверка\n\n"
            "🚀 Бот восстановлен!"
        )
    
    async def ping_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🟢 Бот работает на Render!")
    
    async def setup_webhook(self):
        try:
            await self.application.bot.set_webhook(f"{self.webhook_url}/webhook")
            logger.info("✅ Webhook установлен")
        except Exception as e:
            logger.error(f"❌ Ошибка webhook: {e}")

bot_instance = None

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        if bot_instance:
            update = Update.de_json(request.get_json(), bot_instance.application.bot)
            asyncio.create_task(bot_instance.application.process_update(update))
        return 'OK'
    except Exception as e:
        logger.error(f"Ошибка webhook: {e}")
        return 'Error', 500

@app.route('/', methods=['GET'])
def index():
    return '<h1>🤖 Минимальный бот работает!</h1>'

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)

async def main():
    global bot_instance
    
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    webhook_url = os.getenv('RENDER_EXTERNAL_URL')
    
    if not token or not webhook_url:
        logger.error("❌ Нет токена или URL")
        return
    
    bot_instance = MinimalBot(token, webhook_url)
    await bot_instance.application.initialize()
    await bot_instance.setup_webhook()
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    logger.info("🚀 Минимальный бот запущен!")
    
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await bot_instance.application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
