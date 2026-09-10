import logging
from app.services.mongo_checkpoint import profile_manager

logger = logging.getLogger(__name__)

_profile_cache: dict[str, str] = {}

async def get_profile_text(store, user_id: str) -> str:
    """Fetch the stored profile for a user as a plain string, or '' if none."""
    if user_id in _profile_cache:
        return _profile_cache[user_id]
    try:
        result = await store.asearch(("users", user_id,"profile"))
    except Exception:
        logger.exception("Failed to fetch user profile for user_id=%s", user_id)
        return ""

    if not result:
        return ""

    text = str(result[0].value) if result else ""
    _profile_cache[user_id] = text
    return text


async def update_profile(store, user_id: str, messages: list) -> None:
    """Run profile extraction/update, then refresh the cache so future reads stay in sync."""
    try:
        await profile_manager.ainvoke(
            {"messages": messages},
            config={"configurable": {"user_id": user_id, "store": store}}
        )
        results = await store.asearch(("users", user_id, "profile"))
        _profile_cache[user_id] = str(results[0].value) if results else ""
    except Exception:
        logger.exception("Failed to update user profile for user_id=%s", user_id)