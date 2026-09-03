# YTDLMSaver

<div align="center">
  <img src="logo.png" alt="YTDLMSaver logo" width="180" />

  <h3>Telegram-бот для скачивания медиаконтента</h3>

## Что умеет бот

- Скачивает видео по ссылке с популярных платформ через `yt-dlp`.
- Поддерживает работу в группах.
- Грузит видео в фоне и отправляет результат по готовности.
- Показывает все доступные разрешения YouTube, включая 1080p, 1440p, 4K и 8K.
- Автоматически скачивает и объединяет лучшие video+audio потоки через FFmpeg.
- Использует общую очередь без пользовательских лимитов.
- Хранит статистику в SQLite и автоматически мигрирует старый `user_stats.json`.
- Поддерживает админ-команды и базовую статистику.

## Быстрый старт

### Установка зависимостей

```bash
pip install -r requirements.txt
```

### Настройка `.env`

Скопируйте `.env.example` в `.env` и заполните нужные значения:

```env
BOT_TOKEN=ваш_токен_бота
ADMIN_IDS=123456789
```

Для отправки файлов больше стандартного лимита Bot API поднимите локальный
`telegram-bot-api` и укажите его адрес. `TELEGRAM_API_ID` и
`TELEGRAM_API_HASH` создаются на https://my.telegram.org/apps.

```env
BOT_API_BASE_URL=http://127.0.0.1:8081
BOT_API_IS_LOCAL=true
MAX_FILE_SIZE=2097152000
SEND_AS_DOC_LIMIT=2097152000
DOWNLOAD_RATE_LIMIT_BYTES=4194304
DOWNLOAD_STALL_TIMEOUT_SECONDS=300
TELEGRAM_API_ID=ваш_api_id
TELEGRAM_API_HASH=ваш_api_hash
```

Запуск локального Bot API через Docker:

```bash
docker compose up -d telegram-bot-api
docker compose logs -f telegram-bot-api
```

После этого запускайте бота обычной командой:

```bash
python main.py
```

### Запуск без локального Bot API на alwaysdata

Docker не обязателен для работы бота. Но для отправки файлов больше облачного
лимита Telegram нужен локальный `telegram-bot-api`. Если на сервере нет
локального `telegram-bot-api`, оставьте `BOT_API_BASE_URL` пустым или удалите
эту переменную из `.env`.

Минимальный `.env` для Python-only запуска:

```env
BOT_TOKEN=ваш_токен_бота
ADMIN_IDS=123456789
MAX_FILE_SIZE=52428800
SEND_AS_DOC_LIMIT=52428800
```

Команда для вкладки Service на alwaysdata:

```bash
bash -c 'export PATH=$HOME/.local/bin:$HOME/ffmpeg/ffmpeg-7.0.2-amd64-static:$PATH && cd /home/renothing/YTDLMSaver && python main.py'
```

В таком режиме бот работает через облачный Telegram Bot API. Это полностью
Python-запуск, но отправка файлов ограничена примерно 50 MB. Собственный
FastAPI/Flask API можно добавить для внешних запросов к вашему сервису, но он
не заменит локальный `telegram-bot-api` и не снимет лимит Telegram на загрузку
больших файлов.

### Локальный Bot API без Docker на alwaysdata

Чтобы отправлять файлы до 2000 MB без Docker, установите бинарник
`telegram-bot-api` в домашнюю директорию, например в
`$HOME/.local/bin/telegram-bot-api`, и запускайте его вместе с ботом одним
Service-процессом.

Собрать Linux-бинарник на Mac можно через Docker:

```bash
bash scripts/build_telegram_bot_api_linux_amd64.sh
```

Готовый файл появится здесь:

```bash
dist/telegram-bot-api-linux-amd64
```

Загрузите его на сервер:

```bash
scp dist/telegram-bot-api-linux-amd64 renothing@ssh-renothing.alwaysdata.net:/home/renothing/.local/bin/telegram-bot-api
ssh renothing@ssh-renothing.alwaysdata.net 'chmod +x /home/renothing/.local/bin/telegram-bot-api'
```

В `.env` нужны:

```env
BOT_TOKEN=ваш_токен_бота
ADMIN_IDS=123456789
TELEGRAM_API_ID=ваш_api_id
TELEGRAM_API_HASH=ваш_api_hash
MAX_FILE_SIZE=2097152000
SEND_AS_DOC_LIMIT=2097152000
DOWNLOAD_RATE_LIMIT_BYTES=4194304
DOWNLOAD_STALL_TIMEOUT_SECONDS=300
MAX_CONCURRENT_DOWNLOADS=1
```

Команда для вкладки Service:

```bash
bash /home/renothing/YTDLMSaver/scripts/run_alwaysdata_local_bot_api.sh
```

По умолчанию скрипт ожидает бинарник здесь:

```bash
/home/renothing/.local/bin/telegram-bot-api
```

Если путь другой, задайте его перед запуском:

```bash
bash -c 'export BOT_API_BIN=$HOME/telegram-bot-api/bin/telegram-bot-api && bash /home/renothing/YTDLMSaver/scripts/run_alwaysdata_local_bot_api.sh'
```

Скрипт поднимает Bot API на `127.0.0.1:8081`, поэтому он доступен только боту внутри этого же Service-процесса. Это безопаснее, чем открывать порт сервиса наружу.

### Cookies и обход блокировок

**YouTube — cookies не нужны.** Токены Proof-of-Origin (PO tokens), которыми
YouTube защищается от «Sign in to confirm you're not a bot», выдаёт локальный
провайдер `bgutil-ytdlp-pot-provider`. Он ставится вместе с зависимостями
(`pip install -r requirements.txt`) и поднимается как отдельный сервис:

```bash
git clone https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git ~/bgutil-ytdlp-pot-provider
cd ~/bgutil-ytdlp-pot-provider/server && npm ci && npx tsc
node build/main.js -p 4416   # проверка вручную; в проде — systemd-юнит bgutil-pot.service
```

yt-dlp находит провайдер на `http://127.0.0.1:4416` автоматически.

**Instagram — нужен залогиненный аккаунт.** Instagram почти ничего не отдаёт
без входа. Экспортируйте cookies браузерным расширением («Get cookies.txt»)
в файл `cookies.txt` рядом с `main.py`. Дальше сессию продлевает
`scripts/refresh_cookies.py` (cron, раз в 6 ч, headless-Firefox через
Playwright). 100%-й автоматики для Instagram не существует — примерно раз в
месяц сессия слетает и бот присылает админу уведомление: нужно заново
экспортировать `cookies.txt` в `~/Downloads` (≈2 минуты), остальное
автоматически.

Установка Playwright для keep-alive:

```bash
./venv/bin/pip install -r requirements-cookies.txt
./venv/bin/playwright install firefox
./venv/bin/python scripts/seed_cookie_profile.py   # засеять профиль из cookies.txt
```

**Возрастные видео YouTube (18+) — отдельный опциональный файл.** Обойти
age-gate без входа в аккаунт больше нельзя. Заведите одноразовый Google-аккаунт,
подтвердите в нём возраст, экспортируйте его cookies в `yt_cookies.txt` (env
`YT_COOKIES_FILE`). Этот файл используется **только** как повторная попытка,
когда обычная (без cookies) упёрлась в age-gate — на основной путь YouTube он
не влияет. `refresh_cookies.py` продлевает и эту сессию (отдельный профиль,
отдельное уведомление). Без `yt_cookies.txt` возрастные видео просто отдают
понятную ошибку, всё остальное работает.

### Запуск

```bash
python main.py
```

## Конфигурация

Основные параметры находятся в `config.py`:

| Параметр | Назначение |
|---|---|
| `BOT_TOKEN` | Токен Telegram-бота (читается из `.env`) |
| `ADMIN_IDS` | ID администраторов |
| `TEMP_DIR` | Временная директория для загрузок |
| `STATS_DB_PATH` | SQLite-файл со статистикой |
| `MAX_CONCURRENT_DOWNLOADS` | Число одновременно работающих загрузчиков; остальные задачи ждут в общей очереди |
| `MAX_FILE_SIZE`, `SEND_AS_DOC_LIMIT` | Технический предел Telegram Bot API и порог отправки как документа |
| `DOWNLOAD_RATE_LIMIT_BYTES` | Техническое ограничение скорости загрузчика для защиты Service от SIGKILL; `4194304` по умолчанию |
| `DOWNLOAD_STALL_TIMEOUT_SECONDS` | Перезапуск формата, если загрузчик не показывает прогресс; `300` секунд по умолчанию |
| `BOT_API_BASE_URL`, `BOT_API_IS_LOCAL` | Адрес локального Bot API для отправки файлов до 2000 MB |
| `LOG_LEVEL` | Уровень логирования (`INFO`, `DEBUG`, ...) |

## Структура проекта

- `main.py` - точка входа.
- `src/` - основная логика приложения.
- `tests/` - автоматические тесты.
- `temp_downloads/` - временные загруженные файлы.
- `cookies.txt` - cookies Instagram (для gallery-dl и yt-dlp).
- `yt_cookies.txt` - опционально, cookies одноразового Google-аккаунта для видео 18+.
- `scripts/refresh_cookies.py` - keep-alive сессий (cron).
- `database.db` - SQLite-база со статистикой.
- `bot.log` - локальные логи.

## Проверка проекта

```bash
python -m pytest tests/ -q
```

В репозитории настроен GitHub Actions workflow `CI` (`.github/workflows/ci.yml`):
компиляция исходников, `pytest` и `pip-audit` на каждый push и pull request.

## Запуск как systemd-сервис (Linux)

```bash
sudo systemctl start ytdlmsaver
sudo systemctl status ytdlmsaver
```

Полезные команды:

```bash
sudo systemctl restart ytdlmsaver
journalctl -u ytdlmsaver -f
sudo systemctl enable ytdlmsaver
```

## Примечания

- Если `ffmpeg` не установлен, часть медиавозможностей может быть недоступна.
- Бот больше не устанавливает зависимости на лету: перед запуском нужно явно выполнить `pip install -r requirements.txt`.
- Обычные плейлисты ставятся в очередь автоматически в максимальном доступном качестве.
