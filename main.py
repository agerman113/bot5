#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import logging
import feedparser
import yt_dlp
import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ----- НАСТРОЙКИ (можно менять через .env) -----
VK_TOKEN = os.getenv("VK_GROUP_TOKEN")
VK_GROUP_ID = os.getenv("VK_GROUP_ID")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 600))       # секунд между проверками каналов
MAX_DURATION = int(os.getenv("MAX_DURATION_SECONDS", 60))    # макс. длина видео в секундах
AD_TEXT = os.getenv("AD_TEXT", "Узнай, как зарабатывать на партнёрских программах → https://vk.me/1onesis")
CHANNEL_IDS = [ch.strip() for ch in os.getenv("CHANNEL_IDS", "").split(",") if ch.strip()]

# ----- НАСТРОЙКА ЛОГИРОВАНИЯ -----
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ----- ИНИЦИАЛИЗАЦИЯ КЛИЕНТОВ -----
openai_client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY) if OPENROUTER_KEY else None

# ----- ФУНКЦИИ -----
def load_processed():
    """Загружает список уже обработанных видео ID из файла"""
    if os.path.exists("processed.txt"):
        with open("processed.txt", "r") as f:
            return set(line.strip() for line in f)
    return set()

def save_processed(video_id):
    """Сохраняет ID обработанного видео"""
    with open("processed.txt", "a") as f:
        f.write(f"{video_id}\n")

def check_video_info(url):
    """Получает информацию о видео (длительность, ориентация) без скачивания"""
    ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        duration = info.get('duration', 0)
        width = info.get('width')
        height = info.get('height')
        # Если нет прямых размеров, ищем в форматах
        if not width or not height:
            for f in info.get('formats', []):
                if f.get('width') and f.get('height'):
                    width, height = f['width'], f['height']
                    break
        is_vertical = (height and width and height > width) or False
        return duration, is_vertical

def download_video(url, output="temp.mp4"):
    """Скачивает видео как готовый MP4 (не требует FFmpeg)"""
    ydl_opts = {
        'outtmpl': output,
        'format': 'best[ext=mp4]',
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return output

def generate_description(title, video_url):
    """Генерирует описание через OpenRouter (или fallback)"""
    if not openai_client:
        return f"😄 Смешное видео: {title}\n\n#юмор #shorts\n\n{AD_TEXT}"
    try:
        prompt = f"Напиши короткое описание (2-3 предложения) для смешного вертикального видео. Название: '{title}'. Добавь 3-5 хэштегов, эмодзи. Язык русский. Не упоминай рекламу."
        response = openai_client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200,
        )
        desc = response.choices[0].message.content.strip()
        return f"{desc}\n\n{AD_TEXT}"
    except Exception as e:
        log.warning(f"AI error: {e}")
        return f"😄 Смешное видео: {title}\n\n#юмор #shorts\n\n{AD_TEXT}"

def publish_to_vk(video_path, description):
    """Публикует видео на стену сообщества (сервисный ключ)"""
    # Импортируем vk_api только при необходимости
    import vk_api
    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()
    upload = vk_api.VkUpload(vk_session)
    try:
        video_data = upload.video(
            video_file=video_path,
            name=os.path.basename(video_path),
            description=description,
            group_id=int(VK_GROUP_ID),
            is_private=0,
            wallpost=1
        )
        video_url = f"https://vk.com/video{video_data['owner_id']}_{video_data['video_id']}"
        log.info(f"✅ Опубликовано: {video_url}")
        return True
    except Exception as e:
        log.error(f"Ошибка публикации: {e}")
        return False

def process_video(url, title=None, force=False):
    """Универсальная обработка видео: проверка, скачивание, описание, публикация"""
    if not title:
        title = url.split('/')[-1]  # заглушка
    log.info(f"Обработка: {title} ({url})")
    duration, is_vertical = check_video_info(url)
    log.info(f"Длительность: {duration} сек, вертикальное: {is_vertical}")
    if duration > MAX_DURATION:
        log.warning(f"Слишком длинное ({duration} > {MAX_DURATION}). Пропускаем.")
        return False
    if not is_vertical:
        log.warning("Видео не вертикальное. Пропускаем.")
        return False
    # Скачиваем
    video_file = download_video(url)
    # Генерируем описание
    desc = generate_description(title, url)
    # Публикуем
    success = publish_to_vk(video_file, desc)
    # Удаляем временный файл
    os.remove(video_file)
    return success

# ----- АВТОМАТИЧЕСКИЙ РЕЖИМ (мониторинг каналов) -----
def monitor_channels():
    processed = load_processed()
    while True:
        for channel_id in CHANNEL_IDS:
            try:
                rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
                feed = feedparser.parse(rss_url)
                if not feed.entries:
                    continue
                latest = feed.entries[0]
                video_id = latest.id.split(":")[-1]
                if video_id in processed:
                    continue
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                title = latest.title
                log.info(f"Новое видео на канале {channel_id}: {title}")
                if process_video(video_url, title):
                    save_processed(video_id)
                    processed.add(video_id)
            except Exception as e:
                log.error(f"Ошибка при проверке канала {channel_id}: {e}")
        time.sleep(CHECK_INTERVAL)

# ----- РУЧНОЙ РЕЖИМ (по ссылке) -----
def manual_process(url):
    success = process_video(url, title="Ручная заливка")
    if success:
        log.info("Видео успешно опубликовано!")
    else:
        log.error("Не удалось опубликовать видео.")
    return success

# ----- ТОЧКА ВХОДА -----
if __name__ == "__main__":
    # Если передан аргумент --url, обрабатываем одну ссылку и выходим
    if len(sys.argv) >= 3 and sys.argv[1] == "--url":
        manual_process(sys.argv[2])
        sys.exit(0)
    # Если передан --test-url (для совместимости со старыми командами)
    elif len(sys.argv) >= 3 and sys.argv[1] == "--test-url":
        manual_process(sys.argv[2])
        sys.exit(0)
    # Иначе запускаем автоматический режим (только если заданы каналы)
    else:
        if not CHANNEL_IDS:
            log.error("CHANNEL_IDS не заданы в .env. Бот остановлен.")
            sys.exit(1)
        if not VK_TOKEN or not VK_GROUP_ID:
            log.error("VK_GROUP_TOKEN или VK_GROUP_ID не заданы.")
            sys.exit(1)
        log.info(f"Запущен автоматический режим. Каналы: {CHANNEL_IDS}, интервал: {CHECK_INTERVAL} сек")
        monitor_channels()
