from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from html.parser import HTMLParser

import requests


logger = logging.getLogger(__name__)
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096


@dataclass
class SendResult:
    success: bool
    photo_message_id: str | None = None
    text_message_id: str | None = None


def should_split_caption(message: str) -> bool:
    return telegram_text_length(message) > CAPTION_LIMIT


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def telegram_text_length(message: str) -> int:
    """Count visible UTF-16 code units, matching Telegram's post-entity limits."""
    parser = _VisibleTextParser()
    parser.feed(message)
    visible = "".join(parser.parts)
    return len(visible.encode("utf-16-le")) // 2


class TelegramSender:
    def __init__(self, session: requests.Session | None = None, dry_run: bool = False):
        self.session = session or requests.Session()
        self.dry_run = dry_run
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.channel_id = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()

    def _endpoint(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def _message_id(self, response: requests.Response) -> str | None:
        try:
            return str(response.json()["result"]["message_id"])
        except (ValueError, KeyError, TypeError):
            return None

    def send(self, message: str, image: bytes | None, keyboard: dict | None = None) -> SendResult:
        if self.dry_run:
            logger.info("telegram_skipped reason=dry_run message_chars=%s image=%s", len(message), bool(image))
            return SendResult(True)
        if not self.token or not self.channel_id:
            logger.error("telegram_failed reason=credentials_missing")
            return SendResult(False)
        photo_id: str | None = None
        if image:
            data: dict[str, object] = {"chat_id": self.channel_id}
            if not should_split_caption(message):
                data.update({"caption": message, "parse_mode": "HTML"})
                if keyboard:
                    import json
                    data["reply_markup"] = json.dumps(keyboard, ensure_ascii=False)
            try:
                response = self.session.post(
                    self._endpoint("sendPhoto"),
                    data=data,
                    files={"photo": ("notice.png", image, "image/png")},
                    timeout=30,
                )
                response.raise_for_status()
                photo_id = self._message_id(response)
                if not should_split_caption(message):
                    logger.info("telegram_photo_sent message_id=%s", photo_id)
                    return SendResult(True, photo_message_id=photo_id)
            except requests.RequestException as exc:
                logger.exception("telegram_photo_failed error=%s; falling_back_to_text", exc)
        visible_length = telegram_text_length(message)
        if visible_length > MESSAGE_LIMIT:
            logger.error("telegram_text_failed reason=message_too_long visible_chars=%s", visible_length)
            return SendResult(False, photo_message_id=photo_id)
        payload: dict[str, object] = {
            "chat_id": self.channel_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if keyboard:
            payload["reply_markup"] = keyboard
        try:
            response = self.session.post(self._endpoint("sendMessage"), json=payload, timeout=30)
            response.raise_for_status()
            text_id = self._message_id(response)
            logger.info("telegram_text_sent message_id=%s", text_id)
            return SendResult(True, photo_message_id=photo_id, text_message_id=text_id)
        except requests.RequestException as exc:
            logger.exception("telegram_text_failed error=%s", exc)
            return SendResult(False, photo_message_id=photo_id)

    def send_review(self, text: str) -> bool:
        chat_id = os.getenv("TELEGRAM_REVIEW_CHAT_ID", "").strip()
        if self.dry_run or not chat_id or not self.token:
            return False
        try:
            response = self.session.post(
                self._endpoint("sendMessage"),
                json={"chat_id": chat_id, "text": text[:4096], "disable_web_page_preview": True},
                timeout=20,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.warning("review_notification_failed error=%s", exc)
            return False
