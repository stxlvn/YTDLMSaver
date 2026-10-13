import logging
import re

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_rich_html(html_content: str) -> str:
    return _HTML_TAG_RE.sub("", html_content)


class TelegramBotWrapper:
    def __init__(self, bot):
        self.bot = bot
        self._original_send_message = bot.send_message
        self._original_edit_message_text = bot.edit_message_text
        self._original_reply_to = bot.reply_to
        self._original_send_photo = bot.send_photo
        self._original_send_video = bot.send_video
        self._original_send_document = bot.send_document
        self._original_send_audio = bot.send_audio
        self._original_send_animation = bot.send_animation
        self._original_send_rich_message = bot.send_rich_message
        self._original_edit_rich_message_text = bot.edit_rich_message_text

        self._wrap_methods()

    def _wrap_methods(self):
        self.bot.send_message = self._wrapped_send_message
        self.bot.edit_message_text = self._wrapped_edit_message_text
        self.bot.reply_to = self._wrapped_reply_to
        self.bot.send_photo = self._wrapped_send_photo
        self.bot.send_video = self._wrapped_send_video
        self.bot.send_document = self._wrapped_send_document
        self.bot.send_audio = self._wrapped_send_audio
        self.bot.send_animation = self._wrapped_send_animation
        self.bot.send_rich_message = self._wrapped_send_rich_message
        self.bot.edit_rich_message_text = self._wrapped_edit_rich_message_text

    def _wrapped_send_rich_message(self, chat_id, html, **kwargs):
        # Rich Messages has no parse_mode to drop on a parse failure the way
        # plain sendMessage does - the only fallback is plain text with the
        # markup tags stripped, so a bad/unescaped dynamic value (error text,
        # a title) still reaches the user instead of silently vanishing.
        try:
            return self._original_send_rich_message(chat_id, html, **kwargs)
        except Exception as exc:
            logger.warning("sendRichMessage упал (%s), повтор как обычный текст", exc)
            retry_kwargs = kwargs.copy()
            retry_kwargs.pop("parse_mode", None)
            return self._original_send_message(chat_id, _strip_rich_html(html), **retry_kwargs)

    def _wrapped_edit_rich_message_text(self, html, chat_id, message_id, **kwargs):
        try:
            return self._original_edit_rich_message_text(html, chat_id, message_id, **kwargs)
        except Exception as exc:
            logger.warning("editMessageText(rich_message=...) упал (%s), повтор как обычный текст", exc)
            retry_kwargs = kwargs.copy()
            retry_kwargs.pop("parse_mode", None)
            return self._original_edit_message_text(
                _strip_rich_html(html), chat_id, message_id, **retry_kwargs
            )

    @staticmethod
    def _handle_parse_error(error, text):
        error_message = str(error).lower()
        if "can't parse entities" in error_message or "parse entities" in error_message:
            logger.warning("Telegram parse error detected, retrying without parse_mode")
            return True, text

        return False, text

    def _wrapped_send_message(self, chat_id, text, **kwargs):
        try:
            return self._original_send_message(chat_id, text, **kwargs)
        except Exception as exc:
            is_parse_error, escaped_text = self._handle_parse_error(exc, text)
            if not is_parse_error:
                raise

            retry_kwargs = kwargs.copy()
            retry_kwargs.pop("parse_mode", None)
            return self._original_send_message(chat_id, escaped_text, **retry_kwargs)

    def _wrapped_edit_message_text(self, text, chat_id, message_id, **kwargs):
        try:
            return self._original_edit_message_text(text, chat_id, message_id, **kwargs)
        except Exception as exc:
            is_parse_error, escaped_text = self._handle_parse_error(exc, text)
            if not is_parse_error:
                raise

            retry_kwargs = kwargs.copy()
            retry_kwargs.pop("parse_mode", None)
            return self._original_edit_message_text(
                escaped_text,
                chat_id,
                message_id,
                **retry_kwargs,
            )

    def _wrapped_reply_to(self, message, text, **kwargs):
        try:
            return self._original_reply_to(message, text, **kwargs)
        except Exception as exc:
            is_parse_error, escaped_text = self._handle_parse_error(exc, text)
            if not is_parse_error:
                raise

            retry_kwargs = kwargs.copy()
            retry_kwargs.pop("parse_mode", None)
            return self._original_reply_to(message, escaped_text, **retry_kwargs)

    def _wrapped_send_photo(self, chat_id, photo, **kwargs):
        try:
            return self._original_send_photo(chat_id, photo, **kwargs)
        except Exception as exc:
            caption = kwargs.get("caption")
            if not caption:
                raise

            is_parse_error, escaped_caption = self._handle_parse_error(exc, caption)
            if not is_parse_error:
                raise

            retry_kwargs = kwargs.copy()
            retry_kwargs["caption"] = escaped_caption
            retry_kwargs.pop("parse_mode", None)
            return self._original_send_photo(chat_id, photo, **retry_kwargs)

    def _wrapped_send_video(self, chat_id, video, **kwargs):
        try:
            return self._original_send_video(chat_id, video, **kwargs)
        except Exception as exc:
            caption = kwargs.get("caption")
            if not caption:
                raise

            is_parse_error, escaped_caption = self._handle_parse_error(exc, caption)
            if not is_parse_error:
                raise

            retry_kwargs = kwargs.copy()
            retry_kwargs["caption"] = escaped_caption
            retry_kwargs.pop("parse_mode", None)
            return self._original_send_video(chat_id, video, **retry_kwargs)

    def _retry_caption_call(self, original_method, *args, **kwargs):
        try:
            return original_method(*args, **kwargs)
        except Exception as exc:
            caption = kwargs.get("caption")
            if not caption:
                raise

            is_parse_error, escaped_caption = self._handle_parse_error(exc, caption)
            if not is_parse_error:
                raise

            retry_kwargs = kwargs.copy()
            retry_kwargs["caption"] = escaped_caption
            retry_kwargs.pop("parse_mode", None)
            return original_method(*args, **retry_kwargs)

    def _wrapped_send_document(self, chat_id, document, **kwargs):
        return self._retry_caption_call(
            self._original_send_document,
            chat_id,
            document,
            **kwargs,
        )

    def _wrapped_send_audio(self, chat_id, audio, **kwargs):
        return self._retry_caption_call(
            self._original_send_audio,
            chat_id,
            audio,
            **kwargs,
        )

    def _wrapped_send_animation(self, chat_id, animation, **kwargs):
        return self._retry_caption_call(
            self._original_send_animation,
            chat_id,
            animation,
            **kwargs,
        )

    def __getattr__(self, name):
        return getattr(self.bot, name)
