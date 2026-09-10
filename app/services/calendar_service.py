import os
import json
import time
from pathlib import Path
import httpx
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

load_dotenv()

CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
TOKEN_FILE = "calendar_tokens.json"


def get_access_token() -> str:
    """Load token from file, refresh it, and return a valid access token."""
    tokens = json.loads(Path(TOKEN_FILE).read_text())

    resp = httpx.post("https://oauth2.googleapis.com/token", data={
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": tokens["refresh_token"],
        "grant_type":    "refresh_token",
    })

    new_tokens = resp.json()

    if "access_token" not in new_tokens:
        raise Exception(f"Token refresh failed: {new_tokens}")

    tokens["access_token"] = new_tokens["access_token"]
    Path(TOKEN_FILE).write_text(json.dumps(tokens))

    return tokens["access_token"]


def get_calendar_service():
    """Return a Google Calendar API service using the stored token."""
    tokens = json.loads(Path(TOKEN_FILE).read_text())

    access_token = get_access_token()
    tokens["access_token"] = access_token

    creds = Credentials(
        token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )

    return build("calendar", "v3", credentials=creds)