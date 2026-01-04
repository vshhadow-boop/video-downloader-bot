#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовая версия бота для диагностики проблем
"""

import os
import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional, Dict

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import yt_dlp
from flask import Flask, request
import threading

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG  # Включаем подробные логи
)
logger = logging.getLogger(__name__)

# Flask приложение для webhook
app = Flask(__name__)

class TestVideoBot:
    def __init__(self, token: str, webhook_url: str):
        self.token = token
        self.webhook_url = webhook_url
        self.application = Application.builder().token(token).build()
        self.temp_dir = Path(tempfile.mkdtemp())
        
        # Регистрируем обработчики
        self._register_handlers()
    
    def _register_handlers(self):
        """Регистрация обработчиков команд"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("test", self.test_command))
        self.application.add_handler(CommandHandler("ping", self.ping_command))
        
        # Обработка ссылок
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_url)
        )
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        await update.message.reply_text(
            "🧪 **ТЕСТОВЫЙ БОТ**\n\n"
            "Команды:\n"
            "• /test <ссылка> - тест видео\n"
            "• /ping - проверка\n\n"
            "Или просто отправьте ссылку"
        )
    
    async def ping_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /ping"""
        await update.message.reply_text("🟢 Тестовый бот работает!")
    
    async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /test"""
        if not context.args:
            await update.message.reply_text("❌ Укажите ссылку для теста!")
            return
        
        url = context.args[0]
        await self._test_video(update, url)
    
    async def handle_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ссылок"""
        text = update.message.text
        
        if 'youtube.com' in text.lower() or 'youtu.be' in text.lower():
            await self._test_video(update, text)
        else:
            await update.message.reply_text("🤔 Отправьте YouTube ссылку")
    
    async def _test_video(self, update: Update, url: str):
        """Тестирование видео"""
        status_message = await update.message.reply_text("🧪 Тестирую...")
        
        try:
            # Очищаем URL
            clean_url = url.split('?')[0] if '?' in url else url
            
            await status_message.edit_text(f"🔍 Тестирую: {clean_url}")
            
            # Тест 1: Базовая информация
            await status_message.edit_text("🔍 Тест 1: Получение информации...")
            
            basic_info = await self._get_basic_info(clean_url)
            
            if not basic_info:
                await status_message.edit_text("❌ Тест 1 ПРОВАЛЕН: Не удалось получить базовую информацию")
                return
            
            # Тест 2: Детальная информация
            await status_message.edit_text("🔍 Тест 2: Детальная информация...")
            
            detailed_info = await self._get_detailed_info(clean_url)
            
            # Результаты
            title = basic_info.get('title', 'Неизвестно')[:50]
            uploader = basic_info.get('uploader', 'Неизвестно')[:30]
            duration = basic_info.get('duration', 0)
            
            result_text = (
                f"✅ **РЕЗУЛЬТАТЫ ТЕСТА**\n\n"
                f"📹 {title}...\n"
                f"📺 {uploader}\n"
                f"⏱️ {duration//60}:{duration%60:02d}\n\n"
            )
            
            if detailed_info:
                formats_count = len(detailed_info.get('formats', []))
                result_text += f"📊 Форматов: {formats_count}\n"
                
                if 'error_details' in detailed_info:
                    result_text += f"⚠️ Проблемы: {detailed_info['error_details']}\n"
            
            result_text += f"\n🔗 URL: {clean_url}"
            
            await status_message.edit_text(result_text)
            
        except Exception as e:
            logger.error(f"Ошибка теста: {e}")
            await status_message.edit_text(
                f"❌ **ОШИБКА ТЕСТА**\n\n"
                f"Детали: {str(e)[:200]}...\n\n"
                f"🔗 URL: {clean_url}"
            )
    
    async def _get_basic_info(self, url: str) -> Optional[Dict]:
        """Получение базовой информации"""
        try:
            opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,  # Только базовая информация
                'skip_download': True,
            }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
                
        except Exception as e:
            logger.error(f"Ошибка базовой информации: {e}")
            return None
    
    async def _get_detailed_info(self, url: str) -> Optional[Dict]:
        """Получение детальной информации"""
        try:
            opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,  # Полная информация
                'skip_download': True,
                'format': 'best[height<=720]/best',
            }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
                
        except Exception as e:
            logger.error(f"Ошибка детальной информации: {e}")
            return {'error_details': str(e)}
    
    async def setup_webhook(self):
        """Настройка webhook"""
        try:
            await self.application.bot.set_webhook(
                url=f"{self.webhook_url}/webhook",
                allowed_updates=["message"]
            )
            logger.info(f"✅ Webhook установлен: {self.webhook_url}/webhook")
        except Exception as e:
            logger.error(f"❌ Ошибка установки webhook: {e}")


# Глобальная переменная для бота
bot_instance = None

@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработка webhook"""
    try:
        if bot_instance:
            update = Update.de_json(request.get_json(), bot_instance.application.bot)
            asyncio.create_task(bot_instance.application.process_update(update))
        return 'OK'
    except Exception as e:
        logger.error(f"Ошибка webhook: {e}")
        return 'Error', 500

@app.route('/health', methods=['GET'])
def health():
    """Проверка здоровья сервиса"""
    return {'status': 'healthy', 'service': 'test-bot'}, 200

@app.route('/', methods=['GET'])
def index():
    """Главная страница"""
    return '''
    <h1>🧪 Test Telegram Bot</h1>
    <p>Тестовый бот для диагностики!</p>
    <p>Статус: <span style="color: green;">Онлайн</span></p>
    '''

def run_flask():
    """Запуск Flask в отдельном потоке"""
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)

async def main():
    """Основная функция"""
    global bot_instance
    
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    webhook_url = os.getenv('RENDER_EXTERNAL_URL')
    
    if not token:
        logger.error("❌ Не найден TELEGRAM_BOT_TOKEN")
        return
    
    if not webhook_url:
        logger.error("❌ Не найден RENDER_EXTERNAL_URL")
        return
    
    # Создаем бота
    bot_instance = TestVideoBot(token, webhook_url)
    
    # Инициализируем приложение
    await bot_instance.application.initialize()
    
    # Устанавливаем webhook
    await bot_instance.setup_webhook()
    
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    logger.info("🧪 Тестовый бот запущен!")
    
    # Держим приложение живым
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("👋 Остановка бота...")
    finally:
        await bot_instance.application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())