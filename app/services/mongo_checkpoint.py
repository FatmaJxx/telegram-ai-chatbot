
import logging
import os
from typing import Optional
from dotenv import load_dotenv
from langchain_mongodb import MongoDBAtlasVectorSearch
from langgraph.store.mongodb import MongoDBStore, create_vector_index_config
from langmem import create_memory_store_manager
from pydantic import BaseModel
from pymongo import MongoClient
from langgraph.checkpoint.mongodb import MongoDBSaver
from langchain_google_genai import GoogleGenerativeAIEmbeddings

class UserProfile(BaseModel):
    """Stable, long-lived facts about the user (not conversation content)."""
    name: Optional[str] = None
    language: Optional[str] = None
    timezone: Optional[str] = None
    preferences: Optional[str] = None
    profession_or_interests: Optional[str] = None

# -----------------------------
# Setup Logging Configuration
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# -----------------------------
# Load Environment Variables
# -----------------------------
load_dotenv()
mongodb_uri = os.getenv("MONGODB_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL_NAME", "gemini-3.5-flash-lite")

if not mongodb_uri:
    logger.error("MONGODB_URI not found in environment variables.")
    raise ValueError("Missing MongoDB URI in .env file")

# -----------------------------
# Define MongoDB Checkpoint Configuration
# -----------------------------
DB_NAME = 'DB'
CHECKPOINT_COLLECTION_NAME = 'Blog_Chekpoint'
CHECKPOINT_WRITE_COLLECTION_NAME = 'Blog_Chekpoint_Write'
TTL_SECONDS = 300  # Time-to-live for checkpoint entries in seconds

# -----------------------------
# Define MongoDB Store Configuration (long-term memory)
# -----------------------------
STORE_COLLECTION_NAME = 'User_Profiles'
EMBEDDING_DIMS = 3072

# -----------------------------
# Define MongoDB Atlas vector search
# -----------------------------
DOCS_COLLECTION_NAME = "Documents"
DOCS_INDEX_NAME = "vector_index"

# -----------------------------
# Initialize MongoDB Client (shared by both checkpointer and store)
# -----------------------------
try:
    mongodb_client = MongoClient(mongodb_uri)
    logger.info("MongoDB client initialized successfully.")
except Exception as e:
    logger.exception("Failed to initialize MongoDB client.")
    raise

# -----------------------------
# Create MongoDBSaver Instance (short-term / per-thread memory)
# -----------------------------
try:
    mongodb_memory = MongoDBSaver(
        client=mongodb_client,
        db_name=DB_NAME,
        checkpoint_collection_name=CHECKPOINT_COLLECTION_NAME,
        writes_collection_name=CHECKPOINT_WRITE_COLLECTION_NAME,
        ttl=TTL_SECONDS
    )
    logger.info("MongoDBSaver instance created successfully.")
except Exception as e:
    logger.exception("Failed to create MongoDBSaver instance.")
    raise

# -----------------------------
# Create MongoDBStore Instance (long-term / per-user memory)
# -----------------------------

try:
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=GEMINI_API_KEY,
    )

    profile_index_config = create_vector_index_config(
        dims=EMBEDDING_DIMS,
        embed=embeddings,
    )


    user_profile_store = MongoDBStore(
        collection=mongodb_client[DB_NAME][STORE_COLLECTION_NAME],
        index_config=profile_index_config,
        auto_index_timeout=60,  # Atlas index creation can take a bit
    )


    doc_vector_store = MongoDBAtlasVectorSearch(
        collection=mongodb_client[DB_NAME][DOCS_COLLECTION_NAME],
        embedding=embeddings,
        index_name=DOCS_INDEX_NAME
    )

    profile_manager = create_memory_store_manager(
    f"google_genai:{GEMINI_MODEL}",
    namespace=("users","{user_id}","profile"),
    schemas=[UserProfile],
    enable_inserts=False,
        instructions=(
        "Extract ONLY stable, long-lived facts about the user's identity — "
        "name, preferred language, timezone, and general durable preferences "
        "(hobbies, profession, communication style). "
        "Do NOT record one-off actions, transient events, tool calls, "
        "calendar bookings, weather lookups, or anything conversational "
        "or time-bound. If nothing stable was mentioned, make no changes."
    ),
)
    logger.info("MongoDBStore instance created successfully.")
except Exception as e:
    logger.exception("Failed to create MongoDBStore instance.")
    raise