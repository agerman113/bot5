"""
Точка входа — инициализирует VK-токен в парсере и запускает бот.
"""
import json
from parsers.vk_parser import set_vk_token

with open("config.json", encoding="utf-8") as f:
    cfg = json.load(f)

set_vk_token(cfg.get("vk_token", ""))

from bot import main
main()
