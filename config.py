from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

CLOUD_BOT_API_UPLOAD_LIMIT = 50 * 1024 * 1024
LOCAL_BOT_API_UPLOAD_LIMIT = 2000 * 1024 * 1024


def _get_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _get_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw_value = os.getenv(name)
    if raw_value in {None, ""}:
        value = default
    else:
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer, got: {raw_value!r}") from exc

    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got: {value}")

    return value


def _get_bool(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value in {None, ""}:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ValueError(f"{name} must be a boolean, got: {raw_value!r}")


def _get_id_list(name: str) -> tuple[int, ...]:
    raw_value = os.getenv(name, "")
    if not raw_value.strip():
        return ()

    values: list[int] = []
    for item in raw_value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            values.append(int(item))
        except ValueError as exc:
            raise ValueError(f"{name} must contain comma-separated integers, got: {raw_value!r}") from exc
    return tuple(values)


def _resolve_path(value: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path.resolve())


@dataclass(frozen=True)
class Settings:
    bot_token: str
    temp_dir: str
    max_concurrent_downloads: int
    max_file_size: int
    send_as_doc_limit: int
    bot_api_base_url: str
    bot_api_is_local: bool
    bot_api_upload_limit: int
    cookies_file: str
    yt_cookies_file: str
    stats_db_path: str
    admin_ids: tuple[int, ...]
    log_level: str
    download_timeout_seconds: int
    download_stall_timeout_seconds: int
    download_rate_limit_bytes: int
    geo_bypass_country: str
    proxy_url: str


def build_settings() -> Settings:
    temp_dir = _resolve_path(_get_str("TEMP_DIR", "temp_downloads"))
    cookies_file = _resolve_path(_get_str("COOKIES_FILE", str(BASE_DIR / "cookies.txt")))
    yt_cookies_file = _resolve_path(_get_str("YT_COOKIES_FILE", str(BASE_DIR / "yt_cookies.txt")))
    stats_db_path = _resolve_path(_get_str("STATS_DB_PATH", _get_str("DB_NAME", "database.db")))
    bot_api_base_url = _get_str("BOT_API_BASE_URL")
    bot_api_is_local = _get_bool("BOT_API_IS_LOCAL", bool(bot_api_base_url))
    bot_api_upload_limit = (
        LOCAL_BOT_API_UPLOAD_LIMIT if bot_api_is_local else CLOUD_BOT_API_UPLOAD_LIMIT
    )

    return Settings(
        bot_token=_get_str("BOT_TOKEN"),
        temp_dir=temp_dir,
        max_concurrent_downloads=_get_int("MAX_CONCURRENT_DOWNLOADS", 1, minimum=1),
        max_file_size=_get_int("MAX_FILE_SIZE", 2 * 1024 * 1024 * 1024, minimum=1),
        send_as_doc_limit=_get_int("SEND_AS_DOC_LIMIT", bot_api_upload_limit, minimum=1),
        bot_api_base_url=bot_api_base_url,
        bot_api_is_local=bot_api_is_local,
        bot_api_upload_limit=bot_api_upload_limit,
        cookies_file=cookies_file,
        yt_cookies_file=yt_cookies_file,
        stats_db_path=stats_db_path,
        admin_ids=_get_id_list("ADMIN_IDS"),
        log_level=_get_str("LOG_LEVEL", "INFO").upper() or "INFO",
        download_timeout_seconds=_get_int("DOWNLOAD_TIMEOUT_SECONDS", 1800, minimum=30),
        download_stall_timeout_seconds=_get_int(
            "DOWNLOAD_STALL_TIMEOUT_SECONDS",
            300,
            minimum=30,
        ),
        download_rate_limit_bytes=_get_int(
            "DOWNLOAD_RATE_LIMIT_BYTES",
            4 * 1024 * 1024,
            minimum=0,
        ),
        geo_bypass_country=_get_str("GEO_BYPASS_COUNTRY", "").upper(),
        proxy_url=_get_str("PROXY_URL", ""),
    )


def validate_settings(settings: Settings | None = None) -> Settings:
    resolved = settings or SETTINGS
    if not resolved.bot_token:
        raise RuntimeError("BOT_TOKEN is required. Add it to the environment or .env file.")

    log_level_name = resolved.log_level.upper()
    if log_level_name not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
        raise RuntimeError(
            "LOG_LEVEL must be one of CRITICAL, ERROR, WARNING, INFO, DEBUG."
        )

    if resolved.send_as_doc_limit > resolved.max_file_size:
        raise RuntimeError("SEND_AS_DOC_LIMIT cannot be greater than MAX_FILE_SIZE.")

    return resolved


SETTINGS = build_settings()

BOT_TOKEN = SETTINGS.bot_token
TEMP_DIR = SETTINGS.temp_dir
MAX_CONCURRENT_DOWNLOADS = SETTINGS.max_concurrent_downloads
MAX_FILE_SIZE = SETTINGS.max_file_size
SEND_AS_DOC_LIMIT = SETTINGS.send_as_doc_limit
BOT_API_BASE_URL = SETTINGS.bot_api_base_url
BOT_API_IS_LOCAL = SETTINGS.bot_api_is_local
BOT_API_UPLOAD_LIMIT = SETTINGS.bot_api_upload_limit
COOKIES_FILE = SETTINGS.cookies_file
YT_COOKIES_FILE = SETTINGS.yt_cookies_file
DB_NAME = SETTINGS.stats_db_path
STATS_DB_PATH = SETTINGS.stats_db_path
ADMIN_IDS = SETTINGS.admin_ids
LOG_LEVEL = SETTINGS.log_level
DOWNLOAD_TIMEOUT_SECONDS = SETTINGS.download_timeout_seconds
DOWNLOAD_STALL_TIMEOUT_SECONDS = SETTINGS.download_stall_timeout_seconds
DOWNLOAD_RATE_LIMIT_BYTES = SETTINGS.download_rate_limit_bytes
GEO_BYPASS_COUNTRY = SETTINGS.geo_bypass_country
PROXY_URL = SETTINGS.proxy_url

# Конфиг для повторных попыток отправки
UPLOAD_RETRY_CONFIG = {
    "max_attempts": 5,
    "base_delay": 3,
    "max_delay": 30,
    "backoff_factor": 2,
    "jitter": 1,
}
UPLOAD_TIMEOUT = 300


def _cookiefile_opts(path_str: str) -> dict:
    path = Path(path_str)
    try:
        if path.is_file() and path.stat().st_size > 0:
            return {"cookiefile": str(path)}
    except OSError:
        pass
    return {}


def cookie_ydl_opts() -> dict:
    """Pass cookies.txt to yt-dlp only when it exists and is non-empty.

    YouTube runs cookie-free (PO tokens via bgutil provider); Instagram/other
    authenticated sources still pick up cookies.txt when it is present.
    """
    return _cookiefile_opts(COOKIES_FILE)


def yt_cookie_ydl_opts() -> dict:
    """Cookies for the age-restricted-YouTube fallback only.

    Populate ``yt_cookies.txt`` (env ``YT_COOKIES_FILE``) with a throwaway,
    age-verified Google account exported from a browser. It is used ONLY when a
    normal (cookie-free) attempt fails with an age-gate — never on the main
    path — so the throwaway account sees almost no traffic and rarely locks.
    """
    return _cookiefile_opts(YT_COOKIES_FILE)


def has_yt_cookies() -> bool:
    return bool(yt_cookie_ydl_opts())


def common_ydl_opts() -> dict:
    """yt-dlp knobs we want on every call.

    - ``source_address``: force IPv4. VPS/shared hosts often advertise IPv6 with
      an unstable route, which yt-dlp surfaces as spurious HTTP 403s.
    - YouTube client selection: the bgutil PO-token provider supplies the tokens
      the ``tv`` / ``web_safari`` clients need, so no account cookies are
      required. ``tv_embedded`` / ``web_embedded`` are kept in the list because
      they still serve a few otherwise-restricted videos; true age-gated ones
      need the yt_cookies.txt fallback. The forced ``mweb`` client used before
      needed its own cookies + PO token (and the option key was misspelled
      ``player-client``, so yt-dlp ignored it anyway).
    """
    return {
        "source_address": "0.0.0.0",
        "extractor_args": {
            "youtube": ["player_client=default,tv,tv_embedded,web_embedded,web_safari"]
        },
    }


AGE_RESTRICTION_MARKERS = (
    "sign in to confirm your age",
    "confirm your age",
    "age-restricted",
    "age restricted",
    "inappropriate for some users",
    "this video may be inappropriate",
)


def is_age_restricted_error(error_text: str) -> bool:
    lowered = (error_text or "").lower()
    return any(marker in lowered for marker in AGE_RESTRICTION_MARKERS)


def geo_ydl_opts() -> dict:
    """yt-dlp options to spoof the region for geo-restricted videos, if configured."""
    opts: dict = {"geo_bypass": True}
    if GEO_BYPASS_COUNTRY:
        opts["geo_bypass_country"] = GEO_BYPASS_COUNTRY
    return opts


def proxy_ydl_opts() -> dict:
    """yt-dlp options routing the request through PROXY_URL, if configured."""
    return {"proxy": PROXY_URL} if PROXY_URL else {}


# "video unavailable" is intentionally included even though it also covers
# deleted/private videos: yt-dlp doesn't always say "your country" for a real
# geo-block, and retrying once through the proxy costs a few seconds but
# correctly recovers the actually-region-locked cases mixed in with it.
GEO_BLOCK_MARKERS = (
    "not available in your country",
    "not available from your location",
    "blocked it in your country",
    "geo restrict",
    "content isn't available",
    "content is not available",
    "this video is not available",
    "video unavailable",
)


def is_geo_blocked_error(error_text: str) -> bool:
    lowered = (error_text or "").lower()
    return any(marker in lowered for marker in GEO_BLOCK_MARKERS)
