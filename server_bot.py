#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Облегченная версия Telegram бота для хостинга на сервере
Оптимизирована для работы на бесплатных хостингах
"""

import os
import asyncio
import logging
import math
import tempfile
import shutil
from typing import Optional, Dict, List
from pathlib import Path

from telegram import Update, InputMediaVideo, InputMediaDocument
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError

import yt_dlp
import requests

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class ServerVideoBot:
    def __init__(self, token: str):
        """
        Инициализация бота для сервера
        
        Args:
            token: Токен бота от BotFather
        """
        self.token = token
        self.application = Application.builder().token(token).build()
        
        # Настройки для сервера
        self.max_file_size_regular = 50 * 1024 * 1024  # 50 МБ
        self.max_file_size_premium = 2 * 1024 * 1024 * 1024  # 2 ГБ
        self.chunk_size = 45 * 1024 * 1024  # 45 МБ на часть
        
        # Временная папка (автоочистка)
        self.temp_dir = Path(tempfile.mkdtemp())
        
        # Настройки yt-dlp для сервера
        self.ydl_opts = {
            'outtmpl': str(self.temp_dir / '%(title)s.%(ext)s'),
            'format': 'best[height<=720]/best',  # Максимум 720p
            'writeinfojson': False,  # Не сохраняем JSON на сервере
            'writethumbnail': True,  # Превью нужны
            'writesubtitles': False,
            'writeautomaticsub': False,
            'ignoreerrors': True,
            'no_warnings': True,
            'extractflat': False,
            'noplaylist': True,  # Только одно видео
        }
        
        # Регистрируем обработчики
        self._register_handlers()
        
        # Пользователи Premium (в реальном проекте - база данных)
        self.premium_users = set()
    
    def _register_handlers(self):
        """Регистрация обработчиков команд"""
        # Основные команды
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("download", self.download_command))
        self.application.add_handler(CommandHandler("info", self.info_command))
        self.application.add_handler(CommandHandler("premium", self.premium_command))
        self.application.add_handler(CommandHandler("ping", self.ping_command))
        
        # Обработка ссылок
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_url)
        )
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        welcome_text = """
🎬 Привет! Я серверный бот для скачивания видео!

🌟 Возможности:
• Скачивание с YouTube, VK, TikTok и других
• Работа 24/7 на сервере
• Поддержка больших файлов (Premium)
• Автоматическая разбивка на части

📱 Команды:
/help - справка
/download <ссылка> - скачать видео
/info <ссылка> - информация
/premium - режим Premium
/ping - проверка работы

🚀 Просто отправь ссылку на видео!
        """
        await update.message.reply_text(welcome_text)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /help"""
        help_text = """
🆘 Справка по командам:

📝 Основные команды:
• /start - начать работу
• /help - эта справка
• /download <ссылка> - скачать видео
• /info <ссылка> - информация о видео
• /premium - режим Premium (2 ГБ)
• /ping - проверка работы бота

🔗 Поддерживаемые платформы:
• YouTube (включая Shorts)
• VKontakte
• TikTok
• Instagram
• Twitter/X
• И многие другие!

💡 Примеры:
• Просто отправь: https://youtu.be/dQw4w9WgXcQ
• Команда: /download https://youtu.be/dQw4w9WgXcQ

⚠️ Ограничения:
• Обычный режим: 50 МБ
• Premium режим: 2 ГБ (с разбивкой)
• Качество: до 720p

🤖 Бот работает на сервере 24/7!
        """
        await update.message.reply_text(help_text)
    
    async def ping_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /ping - проверка работы"""
        await update.message.reply_text(
            "🟢 Бот работает!\n\n"
            f"📡 Сервер: Онлайн\n"
            f"⚡ Статус: Готов к работе\n"
            f"🕐 Время отклика: < 1 сек"
        )
    
    async def premium_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /premium"""
        user_id = update.effective_user.id
        
        if user_id in self.premium_users:
            self.premium_users.remove(user_id)
            mode = "обычный"
            limit = "50 МБ"
        else:
            self.premium_users.add(user_id)
            mode = "Premium"
            limit = "2 ГБ с разбивкой"
        
        await update.message.reply_text(
            f"✅ Режим изменен на: {mode}\n"
            f"📦 Лимит: {limit}\n\n"
            f"💡 Большие файлы разбиваются автоматически"
        )
    
    async def download_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /download"""
        if not context.args:
            await update.message.reply_text(
                "❌ Укажите ссылку!\nПример: /download https://youtu.be/dQw4w9WgXcQ"
            )
            return
        
        url = context.args[0]
        await self._process_video_url(update, url, download=True)
    
    async def info_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /info"""
        if not context.args:
            await update.message.reply_text(
                "❌ Укажите ссылку!\nПример: /info https://youtu.be/dQw4w9WgXcQ"
            )
            return
        
        url = context.args[0]
        await self._process_video_url(update, url, download=False)
    
    async def handle_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ссылок"""
        text = update.message.text
        
        if any(domain in text.lower() for domain in [
            'youtube.com', 'youtu.be', 'vk.com', 'vk.ru', 
            'tiktok.com', 'instagram.com', 'twitter.com', 'x.com'
        ]):
            await self._process_video_url(update, text, download=True)
        else:
            await update.message.reply_text(
                "🤔 Не вижу поддерживаемой ссылки на видео"
            )
    
    def get_video_info(self, url: str) -> Optional[Dict]:
        """Получение информации о видео"""
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                
                return {
                    'title': info.get('title', 'Неизвестно'),
                    'uploader': info.get('uploader', 'Неизвестный канал'),
                    'duration': info.get('duration', 0),
                    'view_count': info.get('view_count', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'webpage_url': info.get('webpage_url', url),
                    'platform': self._detect_platform(url),
                    'file_size': info.get('filesize', 0) or info.get('filesize_approx', 0)
                }
                
        except Exception as e:
            logger.error(f"Ошибка получения информации: {e}")
            return None
    
    def _detect_platform(self, url: str) -> str:
        """Определение платформы"""
        if 'youtube.com' in url or 'youtu.be' in url:
            return 'YouTube'
        elif 'vk.com' in url or 'vk.ru' in url:
            return 'VKontakte'
        elif 'tiktok.com' in url:
            return 'TikTok'
        elif 'instagram.com' in url:
            return 'Instagram'
        elif 'twitter.com' in url or 'x.com' in url:
            return 'Twitter/X'
        else:
            return 'Другая платформа'
    
    async def _process_video_url(self, update: Update, url: str, download: bool = True):
        """Обработка ссылки на видео"""
        status_message = await update.message.reply_text("🔄 Обрабатываю...")
        
        try:
            # Получаем информацию
            video_info = self.get_video_info(url)
            
            if not video_info:
                await status_message.edit_text("❌ Не удалось получить информацию")
                return
            
            info_text = self._format_video_info(video_info)
            
            if not download:
                await status_message.edit_text(info_text, parse_mode='HTML')
                return
            
            # Проверяем размер и права пользователя
            user_id = update.effective_user.id
            is_premium = user_id in self.premium_users
            max_size = self.max_file_size_premium if is_premium else self.max_file_size_regular
            
            file_size = video_info.get('file_size', 0)
            
            if file_size > max_size and not is_premium:
                size_mb = file_size / (1024*1024)
                await status_message.edit_text(
                    f"❌ Файл слишком большой ({size_mb:.1f} МБ)\n"
                    f"Используйте /premium для увеличения лимита\n\n{info_text}",
                    parse_mode='HTML'
                )
                return
            
            # Скачиваем
            await status_message.edit_text("⬇️ Скачиваю...")
            
            result = await self._download_video(url)
            
            if result:
                await self._send_video_to_chat(update, result, status_message, is_premium)
            else:
                await status_message.edit_text("❌ Ошибка скачивания")
                
        except Exception as e:
            logger.error(f"Ошибка обработки: {e}")
            await status_message.edit_text(f"❌ Ошибка: {str(e)}")
    
    async def _download_video(self, url: str) -> Optional[Dict]:
        """Скачивание видео"""
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                # Получаем информацию
                info = ydl.extract_info(url, download=False)
                
                # Скачиваем
                ydl.download([url])
                
                # Ищем скачанные файлы
                title = info.get('title', 'video')
                files = self._find_downloaded_files(title)
                
                return {
                    'title': title,
                    'info': info,
                    'files': files
                }
                
        except Exception as e:
            logger.error(f"Ошибка скачивания: {e}")
            return None
    
    def _find_downloaded_files(self, title: str) -> Dict[str, str]:
        """Поиск скачанных файлов"""
        files = {}
        
        # Ищем видео
        for ext in ['.mp4', '.webm', '.mkv']:
            video_file = self.temp_dir / f"{title}{ext}"
            if video_file.exists():
                files['video'] = str(video_file)
                break
        
        # Ищем превью
        for ext in ['.jpg', '.jpeg', '.png', '.webp']:
            thumb_file = self.temp_dir / f"{title}{ext}"
            if thumb_file.exists():
                files['thumbnail'] = str(thumb_file)
                break
        
        return files
    
    def _format_video_info(self, info: Dict) -> str:
        """Форматирование информации"""
        duration = self._format_duration(info['duration'])
        views = f"{info['view_count']:,}" if info['view_count'] else "Неизвестно"
        
        text = f"""
🎬 <b>{info['title']}</b>

👤 <b>Канал:</b> {info['uploader']}
🌐 <b>Платформа:</b> {info['platform']}
⏱️ <b>Длительность:</b> {duration}
👀 <b>Просмотры:</b> {views}
"""
        
        if info.get('file_size'):
            size_mb = info['file_size'] / (1024 * 1024)
            text += f"📦 <b>Размер:</b> {size_mb:.1f} МБ\n"
        
        return text.strip()
    
    def _format_duration(self, seconds: int) -> str:
        """Форматирование длительности"""
        if seconds == 0:
            return "Неизвестно"
        
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"
    
    async def _send_video_to_chat(self, update: Update, result: Dict, status_message, is_premium: bool):
        """Отправка видео в чат"""
        try:
            files = result['files']
            
            if 'video' not in files:
                await status_message.edit_text("❌ Видео файл не найден")
                return
            
            video_path = Path(files['video'])
            file_size = video_path.stat().st_size
            
            # Проверяем нужно ли разбивать
            if is_premium and file_size > self.chunk_size:
                await self._send_large_video_parts(update, video_path, status_message)
            else:
                await self._send_single_video(update, video_path, files, status_message)
            
            # Очищаем временные файлы
            self._cleanup_temp_files(files)
            
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            await status_message.edit_text(f"❌ Ошибка отправки: {str(e)}")
    
    async def _send_single_video(self, update: Update, video_path: Path, files: Dict, status_message):
        """Отправка одного видео"""
        await status_message.edit_text("📤 Отправляю...")
        
        with open(video_path, 'rb') as video_file:
            thumbnail = None
            if 'thumbnail' in files:
                thumb_path = Path(files['thumbnail'])
                if thumb_path.exists():
                    thumbnail = open(thumb_path, 'rb')
            
            await update.message.reply_video(
                video=video_file,
                caption=f"🎬 {video_path.stem}",
                thumbnail=thumbnail,
                supports_streaming=True
            )
            
            if thumbnail:
                thumbnail.close()
        
        await status_message.delete()
    
    async def _send_large_video_parts(self, update: Update, video_path: Path, status_message):
        """Отправка большого видео частями"""
        file_size = video_path.stat().st_size
        parts_count = math.ceil(file_size / self.chunk_size)
        
        await status_message.edit_text(f"📦 Разбиваю на {parts_count} частей...")
        
        # Разбиваем файл
        parts = await self._split_file(video_path)
        
        if not parts:
            await status_message.edit_text("❌ Ошибка разбивки")
            return
        
        # Отправляем информацию
        await update.message.reply_text(
            f"📦 Файл разбит на {len(parts)} частей\n"
            f"📁 {video_path.name}\n"
            f"💡 Используйте программы для объединения"
        )
        
        # Отправляем части
        for i, part_path in enumerate(parts, 1):
            try:
                await status_message.edit_text(f"📤 Часть {i}/{len(parts)}")
                
                with open(part_path, 'rb') as part_file:
                    await update.message.reply_document(
                        document=part_file,
                        caption=f"📦 Часть {i}/{len(parts)}",
                        filename=f"{video_path.stem}_part{i:02d}.bin"
                    )
                
                # Удаляем часть сразу
                part_path.unlink()
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Ошибка отправки части {i}: {e}")
        
        await status_message.delete()
    
    async def _split_file(self, file_path: Path) -> List[Path]:
        """Разбивка файла на части"""
        parts = []
        part_num = 1
        
        try:
            with open(file_path, 'rb') as input_file:
                while True:
                    chunk = input_file.read(self.chunk_size)
                    if not chunk:
                        break
                    
                    part_path = self.temp_dir / f"{file_path.stem}_part{part_num:02d}.bin"
                    
                    with open(part_path, 'wb') as part_file:
                        part_file.write(chunk)
                    
                    parts.append(part_path)
                    part_num += 1
            
            return parts
            
        except Exception as e:
            logger.error(f"Ошибка разбивки: {e}")
            return []
    
    def _cleanup_temp_files(self, files: Dict[str, str]):
        """Очистка временных файлов"""
        for file_path in files.values():
            try:
                Path(file_path).unlink()
            except:
                pass
    
    def run(self):
        """Запуск бота"""
        logger.info("🤖 Запуск серверного бота...")
        
        try:
            self.application.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
        except KeyboardInterrupt:
            logger.info("👋 Бот остановлен")
        finally:
            # Очищаем временную папку
            shutil.rmtree(self.temp_dir, ignore_errors=True)


def main():
    """Основная функция"""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not token:
        logger.error("❌ Не найден токен бота!")
        logger.error("Установите переменную окружения TELEGRAM_BOT_TOKEN")
        return
    
    bot = ServerVideoBot(token)
    bot.run()


if __name__ == "__main__":
    main()