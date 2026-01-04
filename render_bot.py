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
        
        # Настройки yt-dlp с обходом блокировок
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
            # Обход блокировок YouTube
            'geo_bypass': True,
            'geo_bypass_country': 'US',
            'extractor_retries': 3,
            'fragment_retries': 3,
            'retries': 3,
            'sleep_interval': 1,
            'max_sleep_interval': 5,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        }
        
        # Регистрируем обработчики
        self._register_handlers()
    
    def _register_handlers(self):
        """Регистрация обработчиков команд"""
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("download", self.download_command))
        self.application.add_handler(CommandHandler("ping", self.ping_command))
        self.application.add_handler(CommandHandler("check", self.check_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        
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
/check <ссылка> - проверить видео
/status - проверить YouTube
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
• /check <ссылка> - проверить видео (без скачивания)
• /status - проверить доступность YouTube
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
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /status - проверка доступности YouTube"""
        status_message = await update.message.reply_text("🔍 Проверяю доступность YouTube...")
        
        try:
            # Тестируем на популярном видео
            test_url = "https://youtu.be/dQw4w9WgXcQ"  # Rick Roll - всегда доступно
            
            test_info = self.get_video_info(test_url)
            
            if test_info and 'error_type' not in test_info:
                attempt = test_info.get('attempt', 1)
                await status_message.edit_text(
                    f"✅ **YouTube доступен**\n\n"
                    f"🔄 Успешно с попытки: {attempt}\n"
                    f"🌍 Сервер Render может скачивать\n"
                    f"⚡ Статус: Готов к работе\n\n"
                    f"💡 Можете пробовать скачивать видео!"
                )
            elif test_info and test_info.get('error_type') == 'rate_limited':
                await status_message.edit_text(
                    f"🚫 **YouTube блокирует Render**\n\n"
                    f"❌ Ошибка 429: Слишком много запросов\n"
                    f"⏰ Блокировка временная\n\n"
                    f"💡 **Попробуйте:**\n"
                    f"• Подождать 10-15 минут\n"
                    f"• Использовать локальные программы"
                )
            else:
                await status_message.edit_text(
                    f"⚠️ **Проблемы с YouTube**\n\n"
                    f"❌ Не удалось подключиться\n"
                    f"🔧 Возможны технические работы\n\n"
                    f"💡 Попробуйте позже"
                )
                
        except Exception as e:
            logger.error(f"Ошибка проверки статуса: {e}")
            await status_message.edit_text(
                f"❌ **Ошибка проверки**\n\n"
                f"Детали: {str(e)[:100]}..."
            )
    
    async def check_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /check - проверка видео без скачивания"""
        if not context.args:
            await update.message.reply_text(
                "❌ Укажите ссылку для проверки!\nПример: /check https://youtu.be/dQw4w9WgXcQ"
            )
            return
        
        url = context.args[0]
        status_message = await update.message.reply_text("🔍 Проверяю видео...")
        
        try:
            clean_url = url.split('?')[0] if '?' in url else url
            video_info = self.get_video_info(clean_url)
            
            if not video_info:
                await status_message.edit_text("❌ Не удалось получить информацию о видео")
                return
            
            if isinstance(video_info, dict) and 'error_type' in video_info:
                error_type = video_info['error_type']
                
                if error_type == 'age_restricted':
                    await status_message.edit_text(
                        "🔞 **ВОЗРАСТНЫЕ ОГРАНИЧЕНИЯ**\n\n"
                        "❌ Это видео нельзя скачать через бота\n"
                        "YouTube требует авторизацию для 18+ контента"
                    )
                elif error_type == 'live_content':
                    await status_message.edit_text(
                        "📺 **СТРИМ/ПРЯМОЙ ЭФИР**\n\n"
                        "⚠️ Сложности со скачиванием стримов\n"
                        "Попробуйте после окончания эфира"
                    )
                else:
                    await status_message.edit_text(f"❌ Проблема: {error_type}")
                return
            
            # Показываем детальную информацию
            title = video_info.get('title', 'Неизвестно')
            uploader = video_info.get('uploader', 'Неизвестный канал')
            duration = video_info.get('duration', 0)
            file_size = video_info.get('file_size', 0)
            age_restricted = video_info.get('age_restricted', False)
            is_live = video_info.get('is_live', False)
            was_live = video_info.get('was_live', False)
            
            duration_str = f"{duration//60}:{duration%60:02d}" if duration else "неизвестно"
            size_str = f"{file_size/(1024*1024):.1f} МБ" if file_size else "неизвестно"
            
            # Определяем возможность скачивания
            can_download = True
            issues = []
            
            if age_restricted:
                can_download = False
                issues.append("🔞 Возрастные ограничения")
            
            if is_live:
                can_download = False
                issues.append("🔴 Прямой эфир")
            
            if was_live:
                issues.append("📺 Сохраненный стрим")
            
            if file_size > self.max_file_size:
                can_download = False
                issues.append(f"📏 Слишком большой ({size_str})")
            
            status_icon = "✅" if can_download else "❌"
            status_text = "Можно скачать" if can_download else "Нельзя скачать"
            
            issues_text = f"\n⚠️ Проблемы: {', '.join(issues)}" if issues else ""
            
            await status_message.edit_text(
                f"🔍 **ПРОВЕРКА ВИДЕО**\n\n"
                f"📹 **{title}**\n"
                f"📺 Канал: {uploader}\n"
                f"⏱️ Длительность: {duration_str}\n"
                f"📏 Размер: {size_str}\n\n"
                f"{status_icon} **{status_text}**{issues_text}"
            )
            
        except Exception as e:
            logger.error(f"Ошибка проверки: {e}")
            await status_message.edit_text(f"❌ Ошибка проверки: {str(e)[:100]}...")
    
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
            # Очищаем URL от параметров
            clean_url = url.split('?')[0] if '?' in url else url
            
            # Получаем информацию
            video_info = self.get_video_info(clean_url)
            
            if not video_info:
                # Пробуем альтернативные методы
                await status_message.edit_text("🔄 Пробую альтернативный метод...")
                
                video_info = await self._try_alternative_extraction(clean_url)
                
                if not video_info:
                    await status_message.edit_text(
                        "❌ Не удалось получить информацию\n\n"
                        "🔍 **Возможные причины:**\n"
                        "• Региональные ограничения\n"
                        "• Возрастные ограничения (18+)\n"
                        "• Блокировка скачивания автором\n"
                        "• Приватное/удаленное видео\n"
                        "• Проблемы с сервером YouTube\n\n"
                        "💡 **Попробуйте:**\n"
                        "• Другое видео с того же канала\n"
                        "• Видео без возрастных ограничений\n"
                        "• Публичные видео"
                    )
                    return
            
            # Проверяем на специальные ошибки
            if isinstance(video_info, dict) and 'error_type' in video_info:
                error_type = video_info['error_type']
                
                if error_type == 'rate_limited':
                    await status_message.edit_text(
                        "🚫 **YouTube блокирует сервер Render**\n\n"
                        "❌ Ошибка 429: Слишком много запросов\n"
                        "🤖 Render использует общие IP-адреса\n\n"
                        "💡 **Решения:**\n"
                        "• Попробуйте через 10-15 минут\n"
                        "• Используйте другой хостинг\n"
                        "• Скачайте локально через программу"
                    )
                elif error_type == 'age_restricted':
                    await status_message.edit_text(
                        "🔞 **Видео имеет возрастные ограничения**\n\n"
                        "❌ YouTube требует авторизацию для просмотра\n"
                        "🤖 Бот не может пройти проверку возраста\n\n"
                        "💡 **Решения:**\n"
                        "• Найдите версию без ограничений\n"
                        "• Используйте другой источник\n"
                        "• Скачайте через браузер с авторизацией"
                    )
                elif error_type == 'live_content':
                    await status_message.edit_text(
                        "📺 **Проблема с прямым эфиром/стримом**\n\n"
                        "❌ Стримы и премьеры сложно скачивать\n"
                        "🤖 Требуется специальная обработка\n\n"
                        "💡 **Попробуйте:**\n"
                        "• Дождитесь окончания стрима\n"
                        "• Найдите обычную запись\n"
                        "• Используйте другое видео"
                    )
                elif error_type == 'geo_blocked':
                    await status_message.edit_text(
                        "🌍 **Географические ограничения**\n\n"
                        "❌ Видео недоступно в вашем регионе\n"
                        "🤖 Сервер находится в другой стране\n\n"
                        "💡 **Попробуйте другое видео**"
                    )
                elif error_type == 'unavailable':
                    await status_message.edit_text(
                        "📹 **Видео недоступно**\n\n"
                        "❌ Видео приватное, удалено или заблокировано\n\n"
                        "💡 **Попробуйте другое видео**"
                    )
                return
            
            # Показываем информацию о видео
            title = video_info.get('title', 'Неизвестно')
            duration = video_info.get('duration', 0)
            uploader = video_info.get('uploader', 'Неизвестный канал')
            age_restricted = video_info.get('age_restricted', False)
            is_live = video_info.get('is_live', False)
            was_live = video_info.get('was_live', False)
            
            duration_str = f"{duration//60}:{duration%60:02d}" if duration else "неизвестно"
            
            # Добавляем предупреждения
            warnings = []
            if age_restricted:
                warnings.append("🔞 Возрастные ограничения")
            if is_live:
                warnings.append("🔴 Прямой эфир")
            if was_live:
                warnings.append("📺 Сохраненный стрим")
            
            warning_text = f"\n⚠️ {', '.join(warnings)}" if warnings else ""
            
            await status_message.edit_text(
                f"📹 **{title}**\n"
                f"📺 Канал: {uploader}\n"
                f"⏱️ Длительность: {duration_str}{warning_text}\n\n"
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
            
            result = await self._download_video(clean_url)
            
            if result and 'video' in result['files']:
                await self._send_video(update, result, status_message)
            else:
                # Пробуем скачать только аудио
                await status_message.edit_text(
                    f"🎵 Пробую скачать только аудио...\n\n"
                    f"� **{ti:tle}**\n"
                    f"📺 Канал: {uploader}"
                )
                
                audio_result = await self._download_audio_only(clean_url)
                
                if audio_result and 'audio' in audio_result['files']:
                    await self._send_audio(update, audio_result, status_message)
                else:
                    await status_message.edit_text(
                        f"❌ Не удалось скачать\n\n"
                        f"📹 **{title}**\n"
                        f"📺 Канал: {uploader}\n\n"
                        f"🔒 **Видео защищено от скачивания**\n"
                        f"Автор канала заблокировал загрузку"
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
    
    async def _try_alternative_extraction(self, url: str) -> Optional[Dict]:
        """Альтернативный метод извлечения информации"""
        try:
            # Пробуем с другими настройками
            alt_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'skip_download': True,
                'format': 'worst[height<=480]/worst',  # Пробуем худшее качество
                'age_limit': 99,  # Игнорируем возрастные ограничения
                'geo_bypass': True,  # Обход географических ограничений
            }
            
            with yt_dlp.YoutubeDL(alt_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                return {
                    'title': info.get('title', 'Неизвестно'),
                    'uploader': info.get('uploader', 'Неизвестный канал'),
                    'duration': info.get('duration', 0),
                    'file_size': 0,  # Размер неизвестен
                    'view_count': info.get('view_count', 0),
                    'upload_date': info.get('upload_date', ''),
                }
                
        except Exception as e:
            logger.error(f"Альтернативное извлечение не удалось: {e}")
            return None
    
    def get_video_info(self, url: str) -> Optional[Dict]:
        """Получение информации о видео с обходом блокировок"""
        
        # Список разных настроек для обхода блокировок
        attempts = [
            # Попытка 1: Базовые настройки
            {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'skip_download': True,
                'format': 'best[height<=720]/best',
                'geo_bypass': True,
                'geo_bypass_country': 'US',
            },
            # Попытка 2: С другой страной
            {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'skip_download': True,
                'format': 'worst[height<=480]/worst',
                'geo_bypass': True,
                'geo_bypass_country': 'GB',
                'extractor_retries': 1,
            },
            # Попытка 3: Минимальные настройки
            {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,  # Только базовая информация
                'skip_download': True,
                'geo_bypass': True,
            }
        ]
        
        for i, opts in enumerate(attempts, 1):
            try:
                logger.info(f"Попытка {i} получения информации о видео")
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                    # Получаем размер файла
                    formats = info.get('formats', [])
                    file_size = 0
                    
                    for fmt in formats:
                        if fmt.get('height', 0) <= 720:
                            file_size = fmt.get('filesize') or fmt.get('filesize_approx', 0)
                            if file_size:
                                break
                    
                    if not file_size:
                        file_size = info.get('filesize', 0) or info.get('filesize_approx', 0)
                    
                    logger.info(f"Успешно получена информация (попытка {i})")
                    
                    return {
                        'title': info.get('title', 'Неизвестно'),
                        'uploader': info.get('uploader', 'Неизвестный канал'),
                        'duration': info.get('duration', 0),
                        'file_size': file_size,
                        'view_count': info.get('view_count', 0),
                        'upload_date': info.get('upload_date', ''),
                        'attempt': i
                    }
                    
            except Exception as e:
                error_msg = str(e).lower()
                logger.warning(f"Попытка {i} не удалась: {e}")
                
                # Анализируем ошибку
                if '429' in error_msg or 'too many requests' in error_msg:
                    logger.error("YouTube блокирует запросы (429)")
                    if i < len(attempts):
                        continue  # Пробуем следующий метод
                    return {'error_type': 'rate_limited', 'error_msg': str(e)}
                
                elif any(keyword in error_msg for keyword in ['sign in', 'age', 'restricted', 'login']):
                    return {'error_type': 'age_restricted', 'error_msg': str(e)}
                elif any(keyword in error_msg for keyword in ['live', 'stream', 'premiere']):
                    return {'error_type': 'live_content', 'error_msg': str(e)}
                elif any(keyword in error_msg for keyword in ['private', 'unavailable', 'deleted']):
                    return {'error_type': 'unavailable', 'error_msg': str(e)}
                elif any(keyword in error_msg for keyword in ['region', 'country', 'location']):
                    return {'error_type': 'geo_blocked', 'error_msg': str(e)}
        
        logger.error("Все попытки получения информации не удались")
        return None
    
    async def _download_audio_only(self, url: str) -> Optional[Dict]:
        """Скачивание только аудио"""
        try:
            audio_opts = {
                'outtmpl': str(self.temp_dir / '%(title)s.%(ext)s'),
                'format': 'bestaudio/best',
                'writeinfojson': False,
                'writethumbnail': False,
                'writesubtitles': False,
                'writeautomaticsub': False,
                'ignoreerrors': True,
                'no_warnings': True,
                'extractflat': False,
                'noplaylist': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
            
            with yt_dlp.YoutubeDL(audio_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'audio')
                
                # Скачиваем
                ydl.download([url])
                
                # Ищем аудио файл
                for ext in ['.mp3', '.m4a', '.webm', '.ogg']:
                    audio_file = self.temp_dir / f"{title}{ext}"
                    if audio_file.exists():
                        return {
                            'title': title,
                            'info': info,
                            'files': {'audio': str(audio_file)}
                        }
                
                return None
                
        except Exception as e:
            logger.error(f"Ошибка скачивания аудио: {e}")
            return None
    
    async def _send_audio(self, update: Update, result: Dict, status_message):
        """Отправка аудио"""
        try:
            await status_message.edit_text("📤 Отправляю аудио...")
            
            audio_path = result['files']['audio']
            title = result['title']
            
            with open(audio_path, 'rb') as audio_file:
                await update.message.reply_audio(
                    audio=audio_file,
                    caption=f"🎵 {title}",
                    title=title
                )
            
            await status_message.delete()
            
            # Очищаем файл
            try:
                Path(audio_path).unlink()
            except:
                pass
                
        except Exception as e:
            logger.error(f"Ошибка отправки аудио: {e}")
            await status_message.edit_text(f"❌ Ошибка отправки аудио: {str(e)}")
    
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
