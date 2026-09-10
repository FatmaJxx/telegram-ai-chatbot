from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class WebhookMessage:
    """Parsed message from any IM platform."""
    platform: str
    content: List[Dict[str, Any]]
    sender_id: str
    chat_id: str
    raw: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

class WebhookHandler:
    """Base class for platform webhook handlers."""
    platform: str = "unknown"

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def verify_request(self, headers: Dict[str, str], body: bytes) -> bool:
        """Verify that an incoming request is authentic."""
        return True

    async def parse_message(self, data: Dict[str, Any]) -> Optional[WebhookMessage]:
        """Parse incoming webhook payload into a WebhookMessage."""
        raise NotImplementedError

    async def send_reply(self, chat_id: str, text: str) -> bool:
        """Send a reply back to the platform."""
        raise NotImplementedError