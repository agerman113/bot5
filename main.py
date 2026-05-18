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
from openai import OpenAI, RateLimitError

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)


class VKYouTubeReposter:
    def __init__(self):
        # Сервисный ключ приоритетнее токена группы
        self.vk_token    = os.getenv("VK_SERVICE_KEY") or os.getenv("VK_GROUP_TOKEN")
        self.vk_group_id = int(os.getenv("VK_GROUP_ID"))
        self.model          = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")
        self.check_interval = int(os.getenv("CHECK_INTERVAL", 600))
        self.channel_ids    = [c.strip() for c in os.getenv("CHANNEL_IDS", "").split(",") if c.strip()]
        self.ad_text        = os.getenv("AD_TEXT", "")
        self.max_duration   = int(os.getenv("MAX_DURATION_SECONDS", 180))

        if not self.vk_token:
            raise ValueError("Нужен VK_SERVICE_KEY или VK_GROUP_TOKEN в .env")

        self.ai = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY")
        )
        self.processed = self._load_processed()

    # ── VK API ────────────────────────────────────────────────────────────────

    def _vk(self, method, params):
        params.update({"access_token": self.vk_token, "v": "5.199"})
        r = requests.post(f"https://api.vk.com/method/{method}", data=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise Exception(f"VK {data['error']['error_code']}: {data['error']['error_msg']}")
        return data["response"]

    # ── Processed list ────────────────────────────────────────────────────────

    def _load_processed(self):
        if os.path.exists("processed.txt"):
            with open("processed.txt") as f:
                return set(l.strip() for l in f if l.strip())
        return set()

    def _mark_processed(self, video_id):
        with open("processed.txt", "a") as f:
            f.write(f"{video_id}\n")
        self.processed.add(video_id)

    # ── YouTube ───────────────────────────────────────────────────────────────

    def get_latest_video(self, channel_id):
        try:
            feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
            if not feed.entries:
                return None
            e = feed.entries[0]
            vid = e.id.split(":")[-1]
            return {"id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "title": e.title}
        except Exception as ex:
            logging.error(f"RSS [{channel_id}]: {ex}")
            return None

    def check_video(self, url):
        """Проверяет длину и вертикальность. Возвращает (ok, title)."""
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        duration = info.get("duration", 0)
        if duration > self.max_duration:
            logging.info(f"Слишком длинное: {duration}с > {self.max_duration}с")
            return False, ""
        w = info.get("width") or 0
        h = info.get("height") or 0
        if not (w and h):
            for fmt in info.get("formats", []):
                if fmt.get("width") and fmt.get("height"):
                    w, h = fmt["width"], fmt["height"]
                    break
        if w and h and w >= h:
            logging.info(f"Не вертикальное: {w}x{h}")
            return False, ""
        return True, info.get("title", "Видео")

    def download_video(self, url, path="temp_video.mp4"):
        opts = {
            "outtmpl": path,
            # Берём лучший формат, где видео и аудио уже в одном файле — ffmpeg не нужен
            "format": "best[ext=mp4]/best[ext=webm]/best",
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
        }
        for attempt in range(3):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
                return path
            except Exception as ex:
                logging.warning(f"Скачивание попытка {attempt+1}: {ex}")
                time.sleep(10)
        logging.error("Не удалось скачать видео")
        return None

    # ── AI description ────────────────────────────────────────────────────────

    def generate_description(self, title):
        prompt = (
            f'Напиши короткое привлекательное описание для смешного вертикального видео для VK.\n'
            f'Название: "{title}"\n'
            f'Требования: русский язык, 2-3 предложения, 3-5 хэштегов (#юмор #shorts), эмодзи.'
        )
        for attempt in range(3):
            try:
                resp = self.ai.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=200,
                )
                text = (resp.choices[0].message.content or "").strip()
                if text:
                    return f"{text}\n\n{self.ad_text}".strip()
            except (RateLimitError, Exception) as ex:
                logging.warning(f"AI попытка {attempt+1}: {ex}")
                time.sleep(10 * (attempt + 1))
        return f"😄 {title}\n\n#юмор #shorts\n\n{self.ad_text}".strip()

    # ── VK publish ────────────────────────────────────────────────────────────

    def post_to_vk(self, video_path, title, description):
        # 1. Получаем upload_url
        save = self._vk("video.save", {
            "name": title[:128],
            "description": description[:5000],
            "group_id": self.vk_group_id,
            "is_private": 0,
            "wallpost": 0,
        })
        upload_url = save["upload_url"]
        video_id   = save["video_id"]
        owner_id   = save["owner_id"]

        # 2. Загружаем файл
        with open(video_path, "rb") as fh:
            resp = requests.post(upload_url, files={"video_file": fh}, timeout=120)
        resp.raise_for_status()

        # 3. Публикуем на стену
        self._vk("wall.post", {
            "owner_id": -self.vk_group_id,
            "from_group": 1,
            "message": description,
            "attachments": f"video{owner_id}_{video_id}",
        })
        logging.info(f"Опубликовано: https://vk.com/video{owner_id}_{video_id}")
        return True

    # ── Main actions ──────────────────────────────────────────────────────────

    def process(self, url):
        """Полный цикл: проверить → скачать → сгенерировать → залить."""
        try:
            ok, title = self.check_video(url)
            if not ok:
                return False
            path = self.download_video(url)
            if not path:
                return False
            desc = self.generate_description(title)
            return self.post_to_vk(path, title, desc)
        except Exception as ex:
            logging.error(f"Ошибка обработки {url}: {ex}")
            return False
        finally:
            if os.path.exists("temp_video.mp4"):
                os.remove("temp_video.mp4")

    def run_forever(self):
        if not self.channel_ids:
            logging.warning("CHANNEL_IDS не заданы — мониторинг отключён")
            return
        logging.info(f"Мониторинг каналов: {', '.join(self.channel_ids)}")
        while True:
            try:
                for ch in self.channel_ids:
                    vid = self.get_latest_video(ch)
                    if not vid or vid["id"] in self.processed:
                        continue
                    logging.info(f"Новое видео: {vid['title']}")
                    self.process(vid["url"])
                    self._mark_processed(vid["id"])
                time.sleep(self.check_interval)
            except KeyboardInterrupt:
                logging.info("Остановка")
                break
            except Exception as ex:
                logging.error(f"Ошибка цикла: {ex}")
                time.sleep(60)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot = VKYouTubeReposter()

    # Режим 1: FORCE_UPLOAD_URL в .env → залить и выйти
    force_url = os.getenv("FORCE_UPLOAD_URL", "").strip()
    if force_url:
        logging.info(f"=== РУЧНАЯ ЗАЛИВКА: {force_url} ===")
        ok = bot.process(force_url)
        sys.exit(0 if ok else 1)

    # Режим 2: аргумент командной строки → python main.py https://...
    if len(sys.argv) == 2 and sys.argv[1].startswith("http"):
        logging.info(f"=== РУЧНАЯ ЗАЛИВКА (аргумент): {sys.argv[1]} ===")
        ok = bot.process(sys.argv[1])
        sys.exit(0 if ok else 1)

    # Режим 3: автоматический мониторинг каналов
    bot.run_forever()
