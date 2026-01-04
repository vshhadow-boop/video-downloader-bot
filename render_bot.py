#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram бот для Render с webhook
"""

import os
import asyncio
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Dict

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError

import yt_dlp
from flask import Flask, request
import threading

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Flask приложение для webhook
app = Flask(__name__)

class RenderVideoBot:
    def __init__(self, token: str, webhook_url: str):
        """
        Инициализация бота для Render
        
        Args:
            token: Токен бота от BotFather
            webhook_url: URL для webhook
        """
        self.token = token
        self.webhook_url = webhook_url
        self.application = Application.builder().token(token).build()
        
        # Настройки
        self.max_file_size = 50 * 1024 * 1024  # 50 МБ
        self.temp_dir = Path(tempfile.mkdtemp())
        
        # Настройки yt-dlp
        self.ydl_opts = {
            'outtmpl': str(self.temp_dir / '%(title)s.%(ext)s'),
            'format': 'best[height<=720]/best',
            'writeinfojson': False,
            'writethumbnail': True,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'ignoreerrors': True,
            'no_warnings': True,
            'extractflat': False,
            'noplaylist': True,
        }
        
        # Регистрируем обработчики
        self._register_handlers()
    
    def _register_handlers(self):
        """Регистрация обработчиков команд"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("download", self.download_command))
        self.application.add_handler(CommandHandler("ping", self.ping_command))
        
        # Обработка ссылок
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_url)
        )
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        welcome_text = """
🎬 Привет! Я бот для скачивания видео на Render!

🌟 Возможности:
• Скачивание с YouTube, VK, TikTok
• Работа 24/7 на сервере
• Максимум 50 МБ на файл

📱 Команды:
/help - справка
/download <ссылка> - скачать видео
/ping - проверка работы

🚀 Просто отправь ссылку на видео!
        """
        await update.message.reply_text(welcome_text)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /help"""
        help_text = """
🆘 Справка по командам:

📝 Команды:
• /start - начать работу
• /help - эта справка
• /download <ссылка> - скачать видео
• /ping - проверка работы

🔗 Поддерживаемые платформы:
• YouTube (включая Shorts)
• VKontakte
• TikTok
• Instagram
• Twitter/X

💡 Примеры:
• Просто отправь: https://youtu.be/dQw4w9WgXcQ
• Команда: /download https://youtu.be/dQw4w9WgXcQ

⚠️ Ограничения:
• Максимум: 50 МБ
• Качество: до 720p

🤖 Бот работает на Render 24/7!
        """
        await update.message.reply_text(help_text)
    
    async def ping_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /ping"""
        await update.message.reply_text(
            "🟢 Бот работает на Render!\n\n"
            f"📡 Сервер: Онлайн\n"
            f"⚡ Статус: Готов к работе"
        )
    
    async def download_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /download"""
        if not context.args:
            await update.message.reply_text(
                "❌ Укажите ссылку!\nПример: /download https://youtu.be/dQw4w9WgXcQ"
            )
            return
        
        url = context.args[0]
        await self._process_video_url(update, url)
    
    async def handle_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ссылок"""
        text = update.message.text
        
        if any(domain in text.lower() for domain in [
            'youtube.com', 'youtu.be', 'vk.com', 'vk.ru', 
            'tiktok.com', 'instagram.com', 'twitter.com', 'x.com'
        ]):
            await self._process_video_url(update, text)
        else:
            await update.message.reply_text(
                "🤔 Не вижу поддерживаемой ссылки на видео"
            )
    
    async def _process_video_url(self, update: Update, url: str):
        """Обработка ссылки на видео"""
        status_message = await update.message.reply_text("🔄 Обрабатываю...")
        
        try:
            # Получаем информацию
            video_info = self.get_video_info(url)
            
            if not video_info:
                await status_message.edit_text(
                    "❌ Не удалось получить информацию\n\n"
                    "Возможные причины:\n"
                    "• Региональные ограничения\n"
                    "• Возрастные ограничения\n"
                    "• Блокировка скачивания\n"
                    "• Приватное видео\n\n"
                    "Попробуйте другое видео"
                )
                return
            
            # Показываем информацию о видео
            title = video_info.get('title', 'Неизвестно')
            duration = video_info.get('duration', 0)
            uploader = video_info.get('uploader', 'Неизвестный канал')
            
            duration_str = f"{duration//60}:{duration%60:02d}" if duration else "неизвестно"
            
            await status_message.edit_text(
                f"📹 **{title}**\n"
                f"📺 Канал: {uploader}\n"
                f"⏱️ Длительность: {duration_str}\n\n"
                f"🔄 Проверяю размер..."
            )
            
            # Проверяем размер
            file_size = video_info.get('file_size', 0)
            if file_size > self.max_file_size:
                size_mb = file_size / (1024*1024)
                await status_message.edit_text(
                    f"❌ Файл слишком большой ({size_mb:.1f} МБ)\n"
                    f"Максимум: {self.max_file_size/(1024*1024):.0f} МБ\n\n"
                    f"📹 **{title}**\n"
                    f"📺 Канал: {uploader}"
                )
                return
            
            # Скачиваем
            await status_message.edit_text(
                f"⬇️ Скачиваю...\n\n"
                f"📹 **{title}**\n"
                f"📺 Канал: {uploader}\n"
                f"⏱️ Длительность: {duration_str}"
            )
            
            result = await self._download_video(url)
            
            if result and 'video' in result['files']:
                await self._send_video(update, result, status_message)
            else:
                await status_message.edit_text(
                    f"❌ Ошибка скачивания\n\n"
                    f"📹 **{title}**\n"
                    f"📺 Канал: {uploader}\n\n"
                    f"Возможно, видео защищено от скачивания"
                )
                
        except Exception as e:
            logger.error(f"Ошибка обработки: {e}")
            error_msg = str(e)
            if "age-gated" in error_msg.lower():
                await status_message.edit_text("❌ Видео имеет возрастные ограничения")
            elif "private" in error_msg.lower():
                await status_message.edit_text("❌ Видео приватное или удалено")
            elif "region" in error_msg.lower():
                await status_message.edit_text("❌ Видео недоступно в вашем регионе")
            else:
                await status_message.edit_text(f"❌ Ошибка: {error_msg[:100]}...")
    
    def get_video_info(self, url: str) -> Optional[Dict]:
        """Получение информации о видео"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'skip_download': True,
                'format': 'best[height<=720]/best',
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Получаем размер файла более точно
                formats = info.get('formats', [])
                file_size = 0
                
                for fmt in formats:
                    if fmt.get('height', 0) <= 720:
                        file_size = fmt.get('filesize') or fmt.get('filesize_approx', 0)
                        if file_size:
                            break
                
                if not file_size:
                    file_size = info.get('filesize', 0) or info.get('filesize_approx', 0)
                
                return {
                    'title': info.get('title', 'Неизвестно'),
                    'uploader': info.get('uploader', 'Неизвестный канал'),
                    'duration': info.get('duration', 0),
                    'file_size': file_size,
                    'view_count': info.get('view_count', 0),
                    'upload_date': info.get('upload_date', ''),
                }
                
        except Exception as e:
            logger.error(f"Ошибка получения информации: {e}")
            return None
    
    async def _download_video(self, url: str) -> Optional[Dict]:
        """Скачивание видео"""
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'video')
                
                # Скачиваем
                ydl.download([url])
                
                # Ищем файлы
                files = {}
                
                # Видео
                for ext in ['.mp4', '.webm', '.mkv']:
                    video_file = self.temp_dir / f"{title}{ext}"
                    if video_file.exists():
                        files['video'] = str(video_file)
                        break
                
                # Превью
                for ext in ['.jpg', '.jpeg', '.png', '.webp']:
                    thumb_file = self.temp_dir / f"{title}{ext}"
                    if thumb_file.exists():
                        files['thumbnail'] = str(thumb_file)
                        break
                
                return {
                    'title': title,
                    'info': info,
                    'files': files
                }
                
        except Exception as e:
            logger.error(f"Ошибка скачивания: {e}")
            return None
    
    async def _send_video(self, update: Update, result: Dict, status_message):
        """Отправка видео"""
        try:
            await status_message.edit_text("📤 Отправляю...")
            
            video_path = result['files']['video']
            title = result['title']
            
            with open(video_path, 'rb') as video_file:
                thumbnail = None
                if 'thumbnail' in result['files']:
                    thumbnail = open(result['files']['thumbnail'], 'rb')
                
                await update.message.reply_video(
                    video=video_file,
                    caption=f"🎬 {title}",
                    thumbnail=thumbnail,
                    supports_streaming=True
                )
                
                if thumbnail:
                    thumbnail.close()
            
            await status_message.delete()
            
            # Очищаем файлы
            for file_path in result['files'].values():
                try:
                    Path(file_path).unlink()
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            await status_message.edit_text(f"❌ Ошибка отправки: {str(e)}")
    
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
    return {'status': 'healthy', 'service': 'telegram-bot'}, 200

@app.route('/', methods=['GET'])
def index():
    """Главная страница"""
    return '''
    <h1>🤖 Telegram Video Bot</h1>
    <p>Бот работает на Render!</p>
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
    bot_instance = RenderVideoBot(token, webhook_url)
    
    # Инициализируем приложение
    await bot_instance.application.initialize()
    
    # Устанавливаем webhook
    await bot_instance.setup_webhook()
    
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    logger.info("🚀 Бот запущен на Render!")
    
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
