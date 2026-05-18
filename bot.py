#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import gc
import logging
import feedparser
import yt_dlp
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError
import vk_api
import requests

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)

class VKYouTubeReposter:
    def __init__(self):
        self.vk_token = os.getenv("VK_GROUP_TOKEN")
        self.vk_group_id = os.getenv("VK_GROUP_ID")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        self.model = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
        self.check_interval = int(os.getenv("CHECK_INTERVAL", 600))
        self.channel_ids = [ch.strip() for ch in os.getenv("CHANNEL_IDS", "").split(",") if ch.strip()]
        self.ad_text = os.getenv("AD_TEXT", "Узнай, как зарабатывать на партнёрских программах → https://vk.me/1onesis")
        self.max_duration = int(os.getenv("MAX_DURATION_SECONDS", 60))

        if not self.channel_ids:
            raise ValueError("CHANNEL_IDS is empty")

        self.vk_session = vk_api.VkApi(token=self.vk_token)
        self.vk = self.vk_session.get_api()

        self.openai_client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.openrouter_api_key,
        )
        self.processed_videos = self.load_processed_videos()

    def load_processed_videos(self):
        if os.path.exists("processed.txt"):
            with open("processed.txt", "r") as f:
                return set(line.strip() for line in f)
        return set()

    def save_processed_video(self, video_id):
        with open("processed.txt", "a") as f:
            f.write(f"{video_id}\n")
        self.processed_videos.add(video_id)

    def get_latest_video_from_channel(self, channel_id):
        try:
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            feed = feedparser.parse(rss_url)
            if not feed.entries:
                return None
            latest = feed.entries[0]
            video_id = latest.id.split(":")[-1]
            return {"id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}", "title": latest.title}
        except Exception as e:
            logging.error(f"RSS error: {e}")
            return None

    def is_vertical_video(self, url):
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                duration = info.get('duration', 0)
                if duration > self.max_duration:
                    logging.info(f"Too long: {duration}s")
                    return False
                width = info.get('width')
                height = info.get('height')
                if width and height:
                    return height > width
                for f in info.get('formats', []):
                    if f.get('width') and f.get('height'):
                        return f['height'] > f['width']
                return False
        except Exception as e:
            logging.error(f"Check error: {e}")
            return False

    def download_video(self, url, output_path="temp_video.mp4", retries=3):
        ydl_opts = {
            'outtmpl': output_path,
            'format': 'best[ext=mp4]',
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 30,
        }
        for attempt in range(retries):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                logging.info(f"Downloaded: {url}")
                return output_path
            except Exception as e:
                logging.warning(f"Download attempt {attempt+1} failed: {e}")
                time.sleep(10)
        logging.error(f"Download error after {retries} attempts")
        return None

    def generate_description(self, video_title, video_url):
        prompt = f"""
        Напиши короткое привлекательное описание для смешного вертикального видео (YouTube Shorts) для VK.
        Название: "{video_title}"
        Требования: русский язык, 2-3 предложения, 3-5 хэштегов (#юмор #shorts), эмодзи.
        Не упоминай рекламу.
        """
        for attempt in range(3):
            try:
                response = self.openai_client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=200,
                )
                ai_text = response.choices[0].message.content
                if ai_text is None or not ai_text.strip():
                    raise ValueError("Empty AI response")
                ai_text = ai_text.strip()
                return f"{ai_text}\n\n{self.ad_text}"
            except (RateLimitError, Exception) as e:
                logging.warning(f"AI attempt {attempt+1} failed: {e}")
                time.sleep(10 * (attempt + 1))
        return f"😄 Смешное видео: {video_title}\n\n#юмор #shorts\n\n{self.ad_text}"

    def post_to_vk(self, video_path, description):
        try:
            # 1. Получаем URL для загрузки через метод video.save (работает с сервисным ключом)
            save_data = self.vk.video.save(
                name=os.path.basename(video_path),
                description=description,
                group_id=int(self.vk_group_id),
                is_private=0,
                wallpost=1
            )
            upload_url = save_data['upload_url']
            video_id = save_data['video_id']
            owner_id = save_data['owner_id']

            # 2. Загружаем файл
            with open(video_path, 'rb') as f:
                files = {'video_file': f}
                response = requests.post(upload_url, files=files, timeout=60)
            if response.status_code != 200:
                raise Exception(f"Upload failed with status {response.status_code}")

            video_url = f"https://vk.com/video{owner_id}_{video_id}"
            logging.info(f"Published: {video_url}")
            return True
        except Exception as e:
            logging.error(f"VK upload error: {e}")
            return False

    def process_new_video(self, channel_id, video_info):
        logging.info(f"New video: {video_info['title']} ({video_info['url']})")
        if not self.is_vertical_video(video_info["url"]):
            logging.info("Not vertical or too long, skip")
            self.save_processed_video(video_info["id"])
            return False

        video_file = self.download_video(video_info["url"])
        if not video_file:
            return False

        gc.collect()
        time.sleep(1)
        description = self.generate_description(video_info["title"], video_info["url"])
        success = self.post_to_vk(video_file, description)
        if os.path.exists(video_file):
            os.remove(video_file)
        gc.collect()

        if success:
            self.save_processed_video(video_info["id"])
            logging.info("Successfully published")
        return success

    def run(self):
        logging.info(f"Bot started. Channels: {', '.join(self.channel_ids)}")
        while True:
            try:
                for ch in self.channel_ids:
                    latest = self.get_latest_video_from_channel(ch)
                    if latest and latest["id"] not in self.processed_videos:
                        self.process_new_video(ch, latest)
                time.sleep(self.check_interval)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logging.error(f"Main loop error: {e}")
                time.sleep(60)

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--test-url":
        test_url = sys.argv[2]
        logging.info(f"TEST MODE: {test_url}")
        bot = VKYouTubeReposter()
        if bot.is_vertical_video(test_url):
            logging.info("Video is vertical and short. Downloading...")
            video_file = bot.download_video(test_url)
            if video_file:
                desc = bot.generate_description("Test video", test_url)
                bot.post_to_vk(video_file, desc)
                os.remove(video_file)
                logging.info("Test finished")
            else:
                logging.error("Download failed")
        else:
            logging.info("Not vertical or too long")
        sys.exit(0)
    bot = VKYouTubeReposter()
    bot.run()
