import asyncio
import logging
import os
import time
from typing import Annotated, TypedDict
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph, add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from app.services.mongo_checkpoint import mongodb_memory, user_profile_store
from app.services.tools import all_tools
from langgraph.store.base import BaseStore
from langchain_core.messages import SystemMessage, trim_messages
from langchain_core.runnables import RunnableConfig
from app.services.user_profile_summary import get_profile_text, update_profile

logger = logging.getLogger(__name__)

load_dotenv()


class BasicChatState(TypedDict):
    messages: Annotated[list, add_messages]


SYSTEM_PROMPT = """
You are a helpful AI assistant available via Telegram.

Keep responses concise and under 200 words when possible.

You have access to tools including:
- calculator
- current date and time
- word counter
- weather lookup
- Wikipedia search
- Google Calendar event listing
- Google Calendar event creation
- Google Calendar event deletion
- meeting scheduling
- document search (semantic search over the user's uploaded documents)

IMPORTANT:
When a user asks about:
- their schedule
- upcoming events
- meetings
- calendar entries
- availability
- creating or deleting events

ALWAYS use the appropriate calendar tool instead of claiming you cannot access the calendar.

When a user asks something that requires looking up content from their
uploaded documents, notes, or files, ALWAYS use the document search tool
instead of saying you don't have access to their documents.

You have the abitility to read text in images

If you receive a document len as input tell user you proccessed file correctly
"""


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL_NAME", "gemini-3.5-flash-lite")
MAX_HISTORY_MESSAGES = int(os.getenv("MAX_HISTORY_MESSAGES", "5"))


llm = ChatGoogleGenerativeAI(
    model=GEMINI_MODEL,
    google_api_key=GEMINI_API_KEY,
)


llm_with_tools = llm.bind_tools(all_tools)


_background_tasks: set[asyncio.Task] = set()

def _fire_and_forget(coro):
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _update_profile_background(store: BaseStore, user_id: str, messages: list):
    try:
        await update_profile(store, user_id, messages)
    except:
        logger.exception("Background profile update failed for user_id=%s", user_id)


async def chatbot(state: BasicChatState, config: RunnableConfig, store: BaseStore):

    chat_id = config["configurable"]["thread_id"]
    user_id = config["configurable"].get("user_id", chat_id)

 
    trimmed = trim_messages(
        state["messages"],
        strategy="last",
        token_counter=len, # count by number of messages, not tokens
        max_tokens=MAX_HISTORY_MESSAGES,
        start_on="human",
        allow_partial=False,
        include_system=False
    )


    profile_text = await get_profile_text(store, user_id)

    system_content = SYSTEM_PROMPT

    if profile_text:
        system_content += f"\n\n<User Profile>\n{profile_text}\n</User Profile>"

    messages = [SystemMessage(content=system_content)] + trimmed

    response = await llm_with_tools.ainvoke(messages)
    logger.info(f"tool_calls={getattr(response, 'tool_calls', None)} | content={response.content!r}")
    
    _fire_and_forget(_update_profile_background(store, user_id, trimmed + [response]))

    return {
        "messages": [response]
    }


tool_node = ToolNode(all_tools)

# -------------------- Build LangGraph --------------------
logger.info("Creating LangGraph...")
graph = StateGraph(BasicChatState)


graph.add_node("chatbot", chatbot)
logger.info("Node 'chatbot' added to the graph.")


graph.add_node("tools", tool_node)
logger.info("Node 'tools' added to the graph.")


graph.set_entry_point("chatbot")
logger.info("Entry point set to 'chatbot'.")


graph.add_conditional_edges(
    "chatbot",        # 1. WHERE to come FROM
    tools_condition,  # 2. WHO decides the direction
    {                 # 3. WHAT the decision maps to
        "tools": "tools",
        "__end__": END
    },
)


graph.add_edge("tools", "chatbot")


chat_agent = graph.compile(
    checkpointer= mongodb_memory, 
    store=user_profile_store)

logger.info("LangGraph compiled with MongoDB checkpointing.")