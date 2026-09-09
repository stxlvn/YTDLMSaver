<img src="logo.png" alt="YTDLMSaver" width="120" />

# YTDLMSaver

**Telegram-бот, который скачивает медиа по ссылке и присылает файл обратно в чат.**

[![CI](https://github.com/stxlvn/YTDLMSaver/actions/workflows/ci.yml/badge.svg)](https://github.com/stxlvn/YTDLMSaver/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![aiogram](https://img.shields.io/badge/aiogram-3.31-blue)
![license](https://img.shields.io/badge/license-Apache--2.0-green)

---

## Что умеет

| | |
|---|---|
| 🎬 **Видео** | любое качество вплоть до 8K, video+audio склеиваются через FFmpeg |
| 🎵 **Аудио** | извлечение в MP3 192 kbps |
| 🖼️ **Превью и субтитры** | обложка видео, `.srt` (ru/en, вкл. авто-сабы) |
| ✨ **GIF** | из роликов до 30 секунд |
| 📸 **Фото из соцсетей** | посты и карусели Instagram, фото-слайды TikTok |
| 🌐 **Источники** | всё, что понимает `yt-dlp` (~1800 сайтов) + Instagram/TikTok через `gallery-dl` / tikwm |

**В личке** — бот распознаёт источник и предлагает форматы цветными кнопками.
**В группах и топиках форума** — молча берёт максимальное качество и присылает файл
в тот же топик, откуда пришла ссылка. Плейлисты ставятся в очередь целиком.

Ещё: фоновая очередь с прогресс-баром и ETA, статистика в SQLite, интерфейс на
русском и английском (`/lang`), панель администратора и рассылка.

---

## Как это работает

```
ссылка → определение источника → выбор формата (в личке кнопкой) →
фоновая загрузка → склейка FFmpeg → отправка файла в тот же чат/топик
```

Файлы уходят через **локальный `telegram-bot-api`** (до 2 ГБ). Без него бот
работает через облачный Bot API с лимитом ~50 МБ.

---

## Быстрый старт

```bash
git clone https://github.com/stxlvn/YTDLMSaver.git && cd YTDLMSaver
python3.12 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp .env.example .env          # впишите BOT_TOKEN и ADMIN_IDS
./venv/bin/python main.py
```

Нужны в системе: **FFmpeg** (склейка, аудио, GIF) и **Node.js ≥ 18** (провайдер
PO-токенов для YouTube, см. ниже).

Минимальный `.env` — облачный Bot API, файлы до ~50 МБ:

```env
BOT_TOKEN=токен_от_BotFather
ADMIN_IDS=123456789
```

---

## Cookies и обход блокировок

<details>
<summary><b>YouTube — cookies не нужны</b></summary>

От «Sign in to confirm you're not a bot» защищают Proof-of-Origin токены, а не
аккаунт. Их выдаёт локальный провайдер
[`bgutil-ytdlp-pot-provider`](https://github.com/Brainicism/bgutil-ytdlp-pot-provider)
— yt-dlp сам ходит к нему на `127.0.0.1:4416`.

```bash
git clone https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git ~/bgutil-ytdlp-pot-provider
cd ~/bgutil-ytdlp-pot-provider/server && npm ci && npx tsc
node build/main.js -p 4416        # проверка; в проде — systemd-юнит (см. deploy/)
```

</details>

<details>
<summary><b>Instagram — нужен залогиненный аккаунт</b></summary>

Instagram почти ничего не отдаёт анонимно. Экспортируйте cookies браузерным
расширением («Get cookies.txt LOCALLY») в файл **`cookies.txt`** рядом с `main.py`.

Сессию продлевает `scripts/refresh_cookies.py` (cron, раз в 6 ч, headless-Firefox
через Playwright). Полной автоматики не существует: примерно раз в месяц сессия
слетает — бот пишет админу в Telegram, нужно заново экспортировать `cookies.txt`
в `~/Downloads` (≈2 минуты), дальше подхватится само.

```bash
./venv/bin/pip install -r requirements-cookies.txt
./venv/bin/playwright install firefox
./venv/bin/python scripts/seed_cookie_profile.py     # засеять профиль keep-alive
```

</details>

<details>
<summary><b>Возрастные видео YouTube (18+) — опционально</b></summary>

Обойти age-gate без аккаунта уже нельзя. Заведите одноразовый age-verified
Google-аккаунт, экспортируйте его cookies в **`yt_cookies.txt`** (env
`YT_COOKIES_FILE`). Файл используется **только** как повторная попытка при
age-gate — на основной (cookie-free) путь YouTube не влияет. Без файла
возрастные видео отдают понятную ошибку, остальное работает.

</details>

<details>
<summary><b>Региональные блокировки</b></summary>

`GEO_BYPASS_COUNTRY=DE` — подменить регион. `PROXY_URL=socks5://…` — при
явной геоблокировке yt-dlp сам повторит запрос через прокси.

</details>

---

## Развёртывание (Linux, systemd)

**1. Локальный Bot API** (Docker) — для файлов больше 50 МБ. В `.env` добавьте
`TELEGRAM_API_ID` / `TELEGRAM_API_HASH` ([my.telegram.org/apps](https://my.telegram.org/apps))
и `BOT_API_BASE_URL=http://127.0.0.1:8082`, затем:

```bash
docker compose up -d telegram-bot-api
```

**2. Сервисы** — готовые юниты в `deploy/`:

```bash
sudo cp deploy/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bgutil-pot resave
```

| юнит | что делает |
|---|---|
| `bgutil-pot.service` | провайдер PO-токенов YouTube на `:4416` |
| `resave.service` | сам бот, стартует `After=bgutil-pot.service` |

**3. Cron** — keep-alive сессий и приём вручную экспортированных cookies:

```cron
0 */6 * * *  /root/YTDLMSaver/scripts/refresh_cookies.sh  >> /var/log/cookies_refresh.log 2>&1
*   *   * * *  /root/YTDLMSaver/scripts/deploy_cookies.sh
```

**Диагностика:**

```bash
journalctl -u resave -f
curl -s 127.0.0.1:4416/ping        # жив ли провайдер PO-токенов
```

> Файлы без Docker (бинарник `telegram-bot-api` в домашней папке) —
> см. `scripts/build_telegram_bot_api_linux_amd64.sh` и
> `scripts/run_alwaysdata_local_bot_api.sh`.

---

## Конфигурация

Всё через `.env` (полный список — в `.env.example`).

| Переменная | Назначение | По умолчанию |
|---|---|---|
| `BOT_TOKEN` | токен от @BotFather | — (обязательно) |
| `ADMIN_IDS` | ID админов через запятую | — |
| `BOT_API_BASE_URL`, `BOT_API_IS_LOCAL` | адрес локального Bot API | облачный |
| `MAX_FILE_SIZE`, `SEND_AS_DOC_LIMIT` | предел Bot API и порог отправки документом | 2 ГБ |
| `MAX_CONCURRENT_DOWNLOADS` | параллельных загрузок, остальные в очереди | `1` |
| `DOWNLOAD_RATE_LIMIT_BYTES` | лимит скорости загрузчика (защита от OOM/SIGKILL) | `4 МБ/с` |
| `DOWNLOAD_STALL_TIMEOUT_SECONDS` | сменить формат, если нет прогресса | `300` |
| `COOKIES_FILE`, `YT_COOKIES_FILE` | Instagram / YouTube-18+ cookies | рядом с `main.py` |
| `GEO_BYPASS_COUNTRY`, `PROXY_URL` | обход региональных блокировок | выкл. |
| `LOG_LEVEL` | `INFO` / `DEBUG` / … | `INFO` |

---

## Структура

```
main.py                  точка входа
config.py                чтение .env
src/
  handlers/              приём сообщений, кнопки, админ-команды
  core/                  очередь, загрузка (yt-dlp), отправка в Telegram
  utils/                 адаптер aiogram, i18n, шаблоны сообщений, ретраи
scripts/                 keep-alive cookies, деплой-хелперы
deploy/                  systemd-юниты
tests/                   pytest
```

Git-ignored в рантайме: `cookies.txt`, `yt_cookies.txt`, `database.db`
(статистика), `user_langs.json`, `telegram_file_cache.json`, `temp_downloads/`.

---

## Разработка

```bash
./venv/bin/python -m pytest tests/ -q
```

CI (`.github/workflows/ci.yml`) на каждый push и PR: компиляция, `pytest`,
`pip-audit`.

---

Форк [ReNothingg/ReSave](https://github.com/ReNothingg/ReSave). Лицензия — Apache-2.0.
