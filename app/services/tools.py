import asyncio
import datetime
import math

import httpx
from langchain.tools import tool
from langchain_community.utilities import WikipediaAPIWrapper
from app.services.mongo_checkpoint import doc_vector_store
from app.services.calendar_service import get_calendar_service
from langchain_core.runnables import RunnableConfig
# ================================================================== #
#  search Documents TOOL
# ================================================================== #

@tool
def search_documents(query: str, k: int = 4, config: RunnableConfig = None) -> str:
    """Search the user's uploaded documents for information relevant to the query.
    Use this whenever the user asks something that could be answered from
    their documents, notes, or files."""
    user_id = None
    if config:
        user_id = config.get("configurable", {}).get("user_id")

    filter_dict = {"user_id": str(user_id)} if user_id else {}

    res = doc_vector_store.similarity_search(query=query, k=k, pre_filter=filter_dict)
    print(f"resresresres ${res}")
    if not res:
        return "No relevant documents found."

    return "\n\n---\n\n".join(
        f"[Source: {r.metadata.get('source', 'unknown')}]\n{r.page_content}"
        for r in res
    )

# ================================================================== #
#  Google Calendar TOOL
# ================================================================== #
@tool
def list_calendar_events(days_ahead: int = 7) -> str:
    """
    List the user's upcoming Google Calendar events including their unique Event IDs.
    ALWAYS use this tool first before deleting or cancelling an event to obtain the event_id.
    """
    try:
        service = get_calendar_service()

        now = datetime.datetime.utcnow().isoformat() + "Z"
        end = (datetime.datetime.utcnow() + datetime.timedelta(days=days_ahead)).isoformat() + "Z"

        result = service.events().list(
            calendarId="primary",
            timeMin=now,
            timeMax=end,
            maxResults=10,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = result.get("items", [])

        if not events:
            return "No upcoming events found."

        lines = []
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date"))
            event_id = e.get("id")
            lines.append(f"📌 {e['summary']} — {start} (Event ID: {event_id})")

        return "\n".join(lines)

    except Exception as e:
        return f"Failed to list events: {e}"


@tool
def create_calendar_event(title: str, start_time: str, end_time: str, description: str = "") -> str:
    """
    Create a new event on the user's Google Calendar.
    Use when the user says 'schedule', 'add a meeting', or 'put on my calendar'.
    start_time and end_time must be ISO 8601 format e.g. '2025-07-01T14:00:00Z'.
    """
    try:
        service = get_calendar_service()
        event_body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_time},
            "end": {"dateTime": end_time},
        }
        
        event = service.events().insert(calendarId="primary", body=event_body).execute()
        return f"Event created successfully: '{event.get('summary')}' (ID: {event.get('id')})"
    
    except Exception as e:
        return f"Failed to create event: {e}"


@tool
def delete_calendar_event(event_id: str, calendar_id: str = "primary") -> str:
    """
    Delete a Google Calendar event by its event ID.
    Use when the user says 'cancel' or 'delete' an event.
    REQUIRES an event_id retrieved from list_calendar_events.
    """
    try:
        clean_event_id = str(event_id).strip().strip("'\"")
        service = get_calendar_service()
        
        service.events().delete(
            calendarId=calendar_id, 
            eventId=clean_event_id
        ).execute()
        
        return f"Event with ID '{clean_event_id}' was deleted successfully."
    
    except Exception as e:
        return f"Failed to delete event: {e}"


@tool
def suggest_meeting_time(duration_minutes: int = 60, days_ahead: int = 5) -> str:
    """
    Suggest a free time slot on the user's calendar for a meeting.
    Use when the user asks 'when am I free?' or 'find a slot for a meeting'.
    """
    try:
        service = get_calendar_service()
        
        # Calculate evaluation window (working hours are treated roughly as 9 AM - 5 PM UTC for safety, or absolute open slots)
        now_dt = datetime.datetime.utcnow()
        end_dt = now_dt + datetime.timedelta(days=days_ahead)
        
        time_min = now_dt.isoformat() + "Z"
        time_max = end_dt.isoformat() + "Z"
        
        # Query freebusy endpoint
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": "primary"}]
        }
        freebusy_query = service.freebusy().query(body=body).execute()
        busy_slots = freebusy_query.get("calendars", {}).get("primary", {}).get("busy", [])
        
        busy_intervals = []
        for slot in busy_slots:
            s_dt = datetime.datetime.fromisoformat(slot["start"].replace("Z", "+00:00")).replace(tzinfo=None)
            e_dt = datetime.datetime.fromisoformat(slot["end"].replace("Z", "+00:00")).replace(tzinfo=None)
            busy_intervals.append((s_dt, e_dt))
            
        # Find first available slot of requested duration between now and time_max
        possible_start = now_dt
        duration = datetime.timedelta(minutes=duration_minutes)
        
        while possible_start + duration <= end_dt:
            possible_end = possible_start + duration
            overlap = False
            
            for b_start, b_end in busy_intervals:
                if max(possible_start, b_start) < min(possible_end, b_end):
                    overlap = True
                    possible_start = b_end 
                    break
            
            if not overlap:
                return f"Suggested free slot: {possible_start.isoformat()}Z to {possible_end.isoformat()}Z"
                
        return "No free time slots found within the specified period."
        
    except Exception as e:
        return f"Failed to suggest meeting time: {e}"
    
# ================================================================== #
#  WEATHER TOOL
#  Uses Open-Meteo API — free, no API key required.
#  Works in two steps:
#    1. Geocoding API  → convert city name to lat/lon coordinates
#    2. Forecast API   → fetch current weather for those coordinates
# ================================================================== #

# WMO Weather Interpretation Codes → human-readable descriptions
# Full list: https://open-meteo.com/en/docs#weathervariables
WMO_CODES = {
    0:  "Clear sky ☀️",
    1:  "Mainly clear 🌤️",
    2:  "Partly cloudy ⛅",
    3:  "Overcast ☁️",
    45: "Foggy 🌫️",
    48: "Icy fog 🌫️",
    51: "Light drizzle 🌦️",
    53: "Moderate drizzle 🌦️",
    55: "Heavy drizzle 🌧️",
    61: "Slight rain 🌧️",
    63: "Moderate rain 🌧️",
    65: "Heavy rain 🌧️",
    71: "Slight snow 🌨️",
    73: "Moderate snow 🌨️",
    75: "Heavy snow ❄️",
    77: "Snow grains 🌨️",
    80: "Slight showers 🌦️",
    81: "Moderate showers 🌧️",
    82: "Heavy showers 🌧️",
    85: "Slight snow showers 🌨️",
    86: "Heavy snow showers ❄️",
    95: "Thunderstorm ⛈️",
    96: "Thunderstorm with hail ⛈️",
    99: "Thunderstorm with heavy hail ⛈️",
}


async def _get_coordinates(city: str) -> tuple[float, float, str]:
    """
    Step 1: Convert a city name to (latitude, longitude, display_name).
    Uses Open-Meteo's geocoding API.
    Raises ValueError if the city is not found.
    """
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": city,
        "count": 1,
        "language": "en",
        "format": "json"
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    results = data.get("results")
    if not results:
        raise ValueError(f"City '{city}' not found. Try a different spelling.")

    top = results[0]
    lat = top["latitude"]
    lon = top["longitude"]

    name    = top.get("name", city)
    country = top.get("country", "")
    display = f"{name}, {country}".strip(", ")

    return lat, lon, display


async def _get_weather(lat: float, lon: float) -> dict:
    """
    Step 2: Fetch current weather for given coordinates.
    Returns the 'current' block from Open-Meteo's forecast API.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":  lat,
        "longitude": lon,
        "current": [
            "temperature_2m",        # temp in °C
            "relative_humidity_2m",  # humidity %
            "apparent_temperature",  # feels-like °C
            "weather_code",          # WMO code → human-readable description
            "wind_speed_10m",        # wind speed in km/h
        ],
        "wind_speed_unit": "kmh",
        "timezone": "auto",          # auto-detect timezone from coordinates
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()["current"]


@tool
async def get_weather(city: str) -> str:
    """
    Get the current weather for any city in the world.
    Use this whenever the user asks about weather, temperature, or conditions
    in a specific city or location.
    Examples: 'Kuwait City', 'London', 'New York', 'Tokyo'
    """
    try:
        lat, lon, display_name = await _get_coordinates(city)

        current = await _get_weather(lat, lon)

        temp       = current.get("temperature_2m")
        feels_like = current.get("apparent_temperature")
        humidity   = current.get("relative_humidity_2m")
        wind       = current.get("wind_speed_10m")
        code       = current.get("weather_code", 0)

        condition = WMO_CODES.get(code, "Unknown")

        return (
            f"📍 {display_name}\n"
            f"{condition}\n"
            f"🌡️  Temperature : {temp}°C (feels like {feels_like}°C)\n"
            f"💧 Humidity    : {humidity}%\n"
            f"💨 Wind        : {wind} km/h"
        )

    except ValueError as e:
        return str(e)

    except httpx.HTTPError as e:
        return f"Weather service unavailable. Please try again later. ({e})"

    except Exception as e:
        return f"Unexpected error fetching weather: {e}"


# ================================================================== #
#  CALCULATOR TOOL
#  Safe math evaluator using a restricted namespace.
#  Never uses raw eval() — builtins are stripped to prevent
#  any possibility of code injection from user input.
# ================================================================== #

@tool
def calculator(expression: str) -> str:
    """
    Evaluate a mathematical expression and return the result.
    Use this for any arithmetic, percentage, or basic math question.
    Examples: '2 + 2', '15% of 200', 'sqrt(144)', '2 ** 10'
    """
    try:
        allowed_names = {
            "sqrt": math.sqrt,
            "pi":   math.pi,
            "e":    math.e,
            "abs":  abs,
            "round": round,
            "pow":  pow
        }
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return f"Result: {result}"

    except Exception as ex:
        return f"Could not evaluate expression: {ex}"


# ================================================================== #
#  DATETIME TOOL
#  Returns current UTC date and time.
#  Simple but useful — LLMs have no real-time clock.
# ================================================================== #

@tool
def get_current_datetime(timezone: str = "UTC") -> str:
    """
    Return the current date and time.
    Use this whenever the user asks what time or date it is.
    The timezone parameter is ignored for now — always returns UTC.
    """
    now = datetime.datetime.utcnow()
    return now.strftime("Current UTC date/time: %A, %B %d %Y — %H:%M:%S")


# ================================================================== #
#  WORD COUNTER TOOL
#  Counts words, characters, and sentences in a given text.
#  Useful for proofreading or text analysis requests.
# ================================================================== #

@tool
def word_counter(text: str) -> str:
    """
    Count the number of words, characters, and sentences in a given text.
    Use this when the user asks to analyse or count something in a piece of text.
    """
    words     = len(text.split())
    chars     = len(text)
    sentences = text.count('.') + text.count('!') + text.count('?')
    return (
        f"Words: {words} | Characters: {chars} | "
        f"Estimated sentences: {max(sentences, 1)}"
    )


# ================================================================== #
#  WIKIPEDIA TOOL
#  Searches Wikipedia and returns a summary of the top result.
#  Use for facts, history, biographies, science, and general knowledge.
#  Client is created once at module load and reused across calls.
# ================================================================== #

wikipedia_api = WikipediaAPIWrapper(
    top_k_results=1,           # only fetch the single best match
    doc_content_chars_max=2000 # cap response length for Telegram
)


@tool
async def search_wikipedia(query: str) -> str:
    """
    Search Wikipedia for information about a topic.
    Use this when the user asks for facts, historical information,
    biographies, places, scientific concepts, or general knowledge.
    """
    try:
        return await asyncio.to_thread(wikipedia_api.run, query)

    except Exception as ex:
        return f"Wikipedia search failed: {ex}"


# ================================================================== #
#  TOOL REGISTRY
#  Single export used by agent.py and ToolNode.
#  To add a new tool: define it above and append it here.
# ================================================================== #

all_tools = [
    calculator,
    get_current_datetime,
    word_counter,
    search_wikipedia,
    get_weather,
    list_calendar_events,    # 👈 new
    create_calendar_event,   # 👈 new
    delete_calendar_event,   # 👈 new
    suggest_meeting_time,
    search_documents
]