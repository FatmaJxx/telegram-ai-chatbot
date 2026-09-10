import asyncio
import base64
import logging
import hmac
import mimetypes
from typing import Any, Dict, Optional
import httpx
from app.services.webhooks.base import WebhookHandler, WebhookMessage
from app.services.document_ingest import ingest_document

logger = logging.getLogger(__name__)

class TelegramWebhook(WebhookHandler):
    platform = "telegram"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.bot_token = config.get("BOT_TOKEN", "")
        self.webhook_secret = config.get("WEBHOOK_SECRET", "")
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"
        self._client = httpx.AsyncClient(timeout=30)
        self._background_tasks: set[asyncio.Task] = set()

    def _fire_and_forget(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
 
    async def aclose(self):
        """Call this on app shutdown to close the underlying connections."""
        await self._client.aclose()

    def verify_request(self, headers: Dict[str, str], body: bytes) -> bool:
        """Verify Telegram webhook via secret_token header."""
        if not self.webhook_secret:
            return True
        token = headers.get("x-telegram-bot-api-secret-token")

        if not token:
            return False

        return hmac.compare_digest(token, self.webhook_secret)

    async def parse_message(self, data: Dict[str, Any]) -> Optional[WebhookMessage]:
        """Parse Telegram update object."""
        message = data.get("message") or data.get("edited_message")
        if not message:
            return None

        chat = message.get("chat", {})
        sender = message.get("from", {})

        message_content = []

        text = message.get("text", "")
        caption = message.get("caption", "")

        if text:
            message_content.append({"type": "text", "text": text})

        doc = message.get("document")
        if doc:
            self._fire_and_forget(
                self._ingest_and_notify(doc=doc, sender=sender, chat=chat)
            )


        image = message.get('photo')
        if image:
            image_id = image[-1]["file_id"]
            image_bytes = await self.download_file(image_id)
            b64_image = base64.b64encode(image_bytes).decode("utf-8")

            if not message_content:
                prompt_text = caption if caption else "Describe what is in this photo."
                message_content.append(
    {"type": "text", "text": prompt_text})

                
            message_content.append( {
        "type": "image",
        "source_type": "base64",
        "data": b64_image,
        "mime_type": "image/jpeg"
    })

        if not message_content:
            return None

        return WebhookMessage(
            platform=self.platform,
            content=message_content,
            sender_id=str(sender.get("id", "")),
            chat_id=str(chat.get("id", "")),
            raw=data,
            metadata={
                "username": sender.get("username", ""),
                "first_name": sender.get("first_name", ""),
                "chat_type": chat.get("type", "private"),
                "message_id": message.get("message_id"),
            }
        )

    async def _ingest_and_notify(self, doc: Dict[str, Any], sender: Dict[str, Any], chat: Dict[str, Any]) -> None:
        """Runs in the background. Downloads + ingests the document, then
        sends a follow-up Telegram message with the outcome — success or
        failure — since the original webhook response already went out
        without waiting for this."""
        chat_id = str(chat.get("id", ""))
        file_name = doc.get("file_name", "your document")
        mime_type = doc.get("mime_type") or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        try:
            file_bytes = await self.download_file(doc["file_id"])
 
            n_chunks = await ingest_document(
                file_bytes=file_bytes,
                file_name=file_name,
                mime_type=mime_type,
                user_id=str(sender.get("id", ""))
            )
 
            await self.send_reply(
                chat_id,
                f"✅ Finished processing '{file_name}' — {n_chunks} chunks indexed. You can ask me about it now."
            )
 
        except Exception:
            logger.exception("Background document ingestion failed for '%s'", file_name)
            await self.send_reply(
                chat_id,
                f"⚠️ Sorry, I couldn't process '{file_name}'. Please try again."
            )


    async def send_reply(self, chat_id: str, text: str) -> bool:
        """Send message via Telegram Bot API."""
        if not self.bot_token:
            logger.error("Telegram BOT_TOKEN not configured")
            return False

        chunks = [text[i:i+4096] for i in range(0, len(text), 4096)]

        try:
            for chunk in chunks:
                    resp = await self._client.post(
                      f"{self.api_base}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": chunk,
                        }
                    )
                    if resp.status_code != 200:
                        logger.error(
                            f"Telegram send failed: {resp.status_code} {resp.text}"
                        )
                        return False
            return True
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    async def download_file(self, file_id: str) -> bytes:
        """Resolve Telegram file_id -> actual file bytes."""
        
        response = await self._client.get(
                f"{self.api_base}/getFile",
                params={"file_id": file_id},
            )

        file_path = response.json()["result"]["file_path"]

        file_resp = await self._client.get(
               f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
            )

        return file_resp.content
