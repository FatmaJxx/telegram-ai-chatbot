import base64
import logging
import os
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import HumanMessage
from app.services.webhooks.telegram import TelegramWebhook
from app.services.agent import chat_agent


logger = logging.getLogger(__name__)

load_dotenv()

telegram_config = {
    "BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN"),
    "WEBHOOK_SECRET": os.getenv("TELEGRAM_WEBHOOK_SECRET"),
}

telegram_handler = TelegramWebhook(telegram_config)

router = APIRouter(on_shutdown=[telegram_handler.aclose])


def get_agent_config(chat_id: str, user_id: str):
    return {
        "configurable": {
            "thread_id": str(chat_id),
            "user_id": str(user_id)
        }
    }

@router.post("/api/webhook/telegram")
async def webhook_telegram(request: Request):
    """Telegram Bot webhook endpoint."""
    
    raw_body = await request.body()
    data = await request.json()
    headers = dict(request.headers)
    
    if not telegram_handler.verify_request(headers, raw_body):
        raise HTTPException(status_code=403, detail="Invalid signature")


    message = await telegram_handler.parse_message(data)
    if not message:
            return {"status": "ok"}


    chat_id = message.chat_id
    user_id = message.sender_id
    user_input = message.content

    try:
        result = await chat_agent.ainvoke(
            {
                "messages": [
                    HumanMessage(content=user_input)
                ]
            }, config = get_agent_config(chat_id, user_id)
        )


        last_msg = result["messages"][-1]
        content = last_msg.content

        if isinstance(content, list):
            ai_response = next(
        (block["text"] for block in content if isinstance(block, dict) and block.get("type") == "text"),
        ""
         )
        else:
            ai_response = content

    except Exception as e:
        logger.error(f"LLM error: {e}")
        ai_response = "Sorry, something went wrong. Please try again later."

    sent = await telegram_handler.send_reply(chat_id, ai_response)
    logger.info(f"AI Response sent to chat {chat_id}: {ai_response}")

    if not sent:
        logger.warning(f"Failed to send reply to chat {chat_id}")

    return {"status": "ok"}

