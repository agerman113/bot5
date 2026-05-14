# 🤖 Freelance Parser Bot — VK Bot

Парсер заказов и упоминаний для VK.  
Источники: **fl.ru, kwork.ru, freelance.ru, hh.ru, Upwork, Telegram-каналы, VK-группы, RSS-ленты** (Reddit, RemoteOK, WeWorkRemotely и др.)

---

## 📁 Структура проекта

```
freelance_parser_bot/
├── bot.py                  # Основная логика бота, роутинг сообщений
├── run.py                  # Точка запуска
├── config.json             # Твой токен и настройки
├── config.example.json     # Шаблон конфига
├── requirements.txt        # Зависимости
├── parsers/
│   ├── base.py             # Утилиты: uid, фильтрация, очистка HTML
│   ├── fl_ru.py            # fl.ru (RSS)
│   ├── kwork.py            # kwork.ru (scraping)
│   ├── freelance_ru.py     # freelance.ru (RSS)
│   ├── hh_ru.py            # hh.ru (открытое API)
│   ├── upwork.py           # Upwork (RSS)
│   ├── rss_parser.py       # Универсальный RSS для всех источников
│   ├── telegram_parser.py  # Telegram каналы (публичный t.me/s/)
│   └── vk_parser.py        # VK группы (VK API)
├── data/
│   ├── categories.py       # 30 RU + 20 EN категорий с ключевыми словами
│   ├── sources.py          # RSS-ленты, Telegram-каналы, VK-группы
│   ├── users.json          # Состояния пользователей (создаётся автоматически)
│   └── seen_ids.json       # ID просмотренных заявок (дедупликация)
└── logs/
    └── bot.log             # Логи
```

---

## ⚙️ Установка и настройка

### 1. Получи VK-токен для бота

1. Зайди на [vk.com/apps](https://vk.com/apps) → Создать приложение
2. Тип: **Standalone**
3. Получи токен с правами: `messages`, `wall`, `groups`, `offline`
4. Или используй токен сообщества (группы VK)

### 2. Заполни config.json

```json
{
  "vk_token": "vk1.a.ТВОЙ_ТОКЕН_ЗДЕСЬ",
  "admin_ids": [123456789],
  "parse_interval_minutes": 30
}
```

### 3. Установи зависимости

```bash
pip install -r requirements.txt
```

### 4. Запусти бота

```bash
python run.py
```

---

## 🚀 Деплой на bothost.ru

1. Зарегистрируйся на [bothost.ru](https://bothost.ru)
2. Создай новый проект → загрузи файлы через **Git** или **FTP**
3. В настройках укажи **Start file**: `run.py`
4. Python version: `3.10+`
5. Установи зависимости: **Requirements file**: `requirements.txt`
6. Заполни `config.json` своим токеном
7. Нажми **Deploy**

---

## 🐙 Деплой через GitHub

```bash
git init
git add .
git commit -m "Initial commit: Freelance Parser Bot"
git remote add origin https://github.com/USERNAME/freelance-parser-bot.git
git push -u origin main
```

> ⚠️ **Не забудь добавить `config.json` в `.gitignore`** (там твой токен!)

Создай `.gitignore`:
```
config.json
data/users.json
data/seen_ids.json
logs/
__pycache__/
*.pyc
.env
```

---

## 🇷🇺 Источники RU

| Источник | Тип | Требует авторизации |
|----------|-----|-------------------|
| fl.ru | RSS | ❌ |
| kwork.ru | HTML scraping | ❌ |
| freelance.ru | RSS | ❌ |
| freelancehunt.com | RSS | ❌ |
| hh.ru | Open API | ❌ |
| habr freelance | RSS | ❌ |
| profi.ru | RSS | ❌ |
| VK группы | VK API | только токен VK |
| Telegram каналы | t.me/s/ web | ❌ |
| Reddit r/forhire (RU) | RSS | ❌ |

## 🇺🇸 Источники EN

| Источник | Тип | Требует авторизации |
|----------|-----|-------------------|
| Upwork | RSS | ❌ |
| Freelancer.com | RSS | ❌ |
| PeoplePerHour | RSS | ❌ |
| RemoteOK | RSS | ❌ |
| WeWorkRemotely | RSS | ❌ |
| Remote.co | RSS | ❌ |
| Reddit r/forhire, /r/hiring | RSS | ❌ |
| HackerNews (Who's hiring) | RSS | ❌ |
| Telegram EN каналы | t.me/s/ web | ❌ |

---

## 📋 Категории

**🇷🇺 Русские (30 шт.):** WEB/IT, Дизайн, Копирайтинг, SEO/SMM, Бухгалтерия, Ремонт техники, Стройка, Медицина, Образование, Фото/Видео, Музыка, Транспорт, Недвижимость, Красота, Фитнес, Еда, Доставка, Животные, Туризм, HR, Переводчики, Авто, Психология, Праздники, Handmade, Флористика, Клининг, Юридические, Маркетплейсы, Вакансии

**🇺🇸 English (20 шт.):** Web Dev, Mobile Dev, Design, Writing, Marketing, SEO, Data Science, DevOps, QA, Video, Photo, Translation, Accounting, Legal, Customer Support, Admin/VA, eCommerce, Game Dev, Blockchain, Cybersecurity

---

## 🔧 Добавить свои источники

**RSS-ленты** — добавь в `data/sources.py`:
```python
RSS_SOURCES["ru"].append({
    "url": "https://example.com/rss.xml",
    "source": "Example Site",
    "lang": "ru"
})
```

**Telegram-каналы** — добавь username публичного канала:
```python
TELEGRAM_CHANNELS["ru"].append({
    "username": "my_freelance_channel",
    "title": "Мой Канал"
})
```

**VK-группы** — добавь domain группы:
```python
VK_GROUPS.append({
    "domain": "my_vk_group",
    "title": "Моя группа",
    "lang": "ru"
})
```

---

## ⏱ Автоматическое обновление

Бот проверяет новые заказы каждые **30 минут** (настраивается в `config.json`).  
Все уже отправленные заявки сохраняются в `data/seen_ids.json` — дубликатов не будет.

---

## 📞 Кнопки бота

| Кнопка | Действие |
|--------|---------|
| 🇷🇺 Русские заказы | Выбор категорий для RU-источников |
| 🇺🇸 English orders | Выбор категорий для EN-источников |
| 📋 Мои категории | Просмотр выбранных категорий |
| 🔔 Подписка вкл/выкл | Включить/отключить авто-уведомления |
| 🔄 Обновить сейчас | Немедленная проверка новых заказов |
| ℹ️ Помощь | Инструкция |
