# 🤖 Telegram AI Chatbot

<img width="100%" alt="Telegram AI Chatbot" src="https://github.com/user-attachments/assets/ff07872c-6f46-4403-bf87-b91f809be737" />

An AI-powered Telegram assistant built with **Python, FastAPI, LangGraph, and Google Gemini**. The chatbot combines conversational AI with external tools, persistent conversation history, document processing, and integrations to provide more useful, context-aware responses.

## ✨ Features

- 💬 **Conversational AI** — interact with an AI assistant directly through Telegram.
- 🧠 **Conversation memory** — maintain conversation context across messages and sessions.
- 👤 **User-specific data** — support personalized information and context.
- 📄 **Document processing** — read and process documents through the assistant.
- 📅 **Google Calendar integration** — interact with calendar functionality.
- 🌤️ **Weather lookup** — retrieve weather information for a city.
- 🧮 **Mathematical calculations** — evaluate mathematical expressions.
- 📚 **Wikipedia search** — retrieve information from Wikipedia.
- 🕒 **Date and time tools** — access date and time information.
- 🔗 **Telegram webhook integration** — receive Telegram updates through a backend API.

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| Python | Core application logic |
| FastAPI | Backend API and webhook endpoint |
| LangGraph | AI agent workflow and tool orchestration |
| Google Gemini | Language model |
| MongoDB | Persistent conversation state and user-related data |
| Telegram Bot API | Telegram messaging integration |
| Uvicorn | ASGI application server |

## 🏗️ Architecture

The application uses an agent-based workflow rather than relying on the language model to answer every question from its own knowledge.

1. **Receive a message:** Telegram sends an update to the backend.
2. **Process the request:** The application extracts the message and relevant conversation context.
3. **Run the agent:** LangGraph coordinates the language model and available tools.
4. **Execute tools:** When appropriate, the agent invokes a tool to retrieve information or perform an operation.
5. **Generate a response:** The model uses the available results to formulate a reply.
6. **Persist conversation state:** MongoDB supports conversation continuity and stored user-related information.

### Core Components

- **API layer:** Handles incoming Telegram webhook requests.
- **Agent layer:** Coordinates the conversation workflow using LangGraph and Gemini.
- **Tool layer:** Provides integrations for supported tasks such as weather, calculations, Wikipedia, and calendar operations.
- **Persistence layer:** Stores conversation state and user-related information in MongoDB.

## 🧠 Agent Workflow

The chatbot follows a tool-using agent pattern. Instead of answering every request directly, the model can decide whether a tool is needed, use the tool's result, and then prepare a response.

For example, when asked about the weather in a city, the agent can retrieve weather information and use the returned result to answer the user.

This approach helps separate language understanding from tasks that require external data or specific operations.
