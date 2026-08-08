"""KI-Analyse-Chat: fragt ein beliebiges OpenAI-kompatibles LLM-Backend
ueber den Zustand der Plattform aus.

Architekturentscheidung: Cloud-/Remote-LLM statt eines lokalen Modells, weil
die verfuegbare Hardware (Docker Desktop, ~3,8 GB RAM insgesamt) fuer ein
Modell mit verlaesslichem Tool-Calling nicht ausreicht (siehe README fuer die
gemessenen Grenzen des vorherigen Ollama-Setups). Das Backend ist bewusst
austauschbar (LLM_BASE_URL/LLM_API_KEY/LLM_MODEL) - Standard ist Groq
(kostenlos, schnell), es funktioniert aber mit jedem OpenAI-/chat-completions-
kompatiblen Endpunkt (OpenAI, lokaler vLLM/llama.cpp-Server, etc.). Trotzdem
bleibt das deterministisch zusammengestellte Kontext-Buendel (siehe
context.py) die Grundlage jeder Antwort - Tools (tools.py) sind fuer
Drill-down da, auf den sich ein groesseres Modell zuverlaessig stuetzen kann.
"""

from __future__ import annotations

import json
import os

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from context import gather_context
from tools import TOOL_SCHEMAS, run_tool

# GROQ_* bleibt als Fallback, damit bestehende .env-Dateien weiterlaufen -
# LLM_* ist der eigentliche, provider-neutrale Name.
LLM_BASE_URL = (os.getenv("LLM_BASE_URL") or "https://api.groq.com/openai/v1").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("GROQ_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL") or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "400"))
MAX_TOOL_ROUNDS = 3
MAX_HISTORY_MESSAGES = 12  # Kontext-Buendel allein braucht schon einige hundert Tokens

# Erlaubt dem Grafana-App-Plugin (im Browser unter localhost:3000 geladen),
# diesen Dienst direkt per fetch() anzusprechen. Lokales PoC-Setup, daher
# bewusst per Env-Var statt fest auf eine Origin beschraenkt.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")]

SYSTEM_PROMPT = (
    "Du bist der Analyse-Assistent eines Observability-Systems fuer einen "
    "Onlineshop und dessen Filiale. Du bekommst bei jeder Anfrage den aktuellen "
    "Systemzustand (Alarme, Kennzahlen, Abhaengigkeiten) als Text mitgeliefert. "
    "Antworte IMMER auf Deutsch, in maximal 4 kurzen Saetzen. Keine Einleitung, "
    "keine Wiederholung der Frage, keine Nebenbemerkungen - direkt die Antwort "
    "mit konkreten Zahlen aus dem gelieferten Kontext. Nutze die angebotenen "
    "Werkzeuge, wenn eine Frage Details verlangt, die im Kontext nicht stehen. "
    "Wenn der Nutzer ausdruecklich ein Dashboard oder eine Visualisierung "
    "erstellen moechte, rufe create_or_update_dashboard mit sinnvollen "
    "PromQL-Ausdruecken auf (list_datasources zeigt die verfuegbaren Quellen) "
    "und nenne danach den zurueckgegebenen Link. Wenn du unsicher bist, sag "
    "das in einem Satz, statt Zahlen zu erfinden oder abzuschweifen."
)

app = FastAPI(title="AIOps Analyse-Chat")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


class ChatResponse(BaseModel):
    reply: str
    context: str


async def _llm_chat(messages: list[dict], use_tools: bool, timeout: float = 30) -> dict:
    if not LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY (bzw. GROQ_API_KEY) ist nicht gesetzt")
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": 0.3,
    }
    if use_tools:
        payload["tools"] = TOOL_SCHEMAS
        payload["tool_choice"] = "auto"
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{LLM_BASE_URL}/chat/completions", json=payload, headers=headers, timeout=timeout
        )
        r.raise_for_status()
        return r.json()


def _extract_tool_calls(message: dict) -> list[dict]:
    calls = message.get("tool_calls") or []
    parsed = []
    for c in calls:
        fn = c.get("function", {})
        name = fn.get("name")
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if name:
            parsed.append({"id": c.get("id"), "name": name, "arguments": args or {}})
    return parsed


async def run_chat(user_message: str, history: list[dict]) -> tuple[str, str]:
    context_block = await gather_context()
    trimmed_history = history[-MAX_HISTORY_MESSAGES:]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": context_block},
        *trimmed_history,
        {"role": "user", "content": user_message},
    ]

    try:
        for _round in range(MAX_TOOL_ROUNDS):
            data = await _llm_chat(messages, use_tools=True)
            message = data["choices"][0]["message"]
            tool_calls = _extract_tool_calls(message)

            if not tool_calls:
                content = (message.get("content") or "").strip()
                return content or "Ich konnte dazu keine Antwort formulieren.", context_block

            messages.append(message)
            for call in tool_calls:
                result = await run_tool(call["name"], call["arguments"])
                messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": result}
                )

        # Letzter Versuch ohne Tools, damit das Modell nicht leer ausgeht.
        data = await _llm_chat(messages, use_tools=False)
        content = (data["choices"][0]["message"].get("content") or "").strip()
        return content or "Ich konnte dazu keine Antwort formulieren.", context_block

    except RuntimeError as exc:
        return (
            f"Der KI-Chat ist nicht konfiguriert ({exc}). Bitte LLM_API_KEY setzen "
            "(z.B. kostenlos auf console.groq.com/keys). Der Systemzustand rechts "
            "ist trotzdem aktuell.",
            context_block,
        )
    except httpx.HTTPStatusError as exc:
        detail = "ungueltiger API-Key" if exc.response.status_code == 401 else str(exc)
        return (
            f"LLM-Anfrage fehlgeschlagen ({detail}). Der Systemzustand rechts ist "
            "trotzdem aktuell.",
            context_block,
        )
    except httpx.HTTPError as exc:
        return (
            f"LLM-Backend ist gerade nicht erreichbar ({exc}). Der Systemzustand "
            "rechts ist trotzdem aktuell.",
            context_block,
        )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    reply, context_block = await run_chat(req.message, req.history)
    return ChatResponse(reply=reply, context=context_block)


@app.get("/health")
async def health():
    return {"status": "ok", "model": LLM_MODEL, "base_url": LLM_BASE_URL, "configured": bool(LLM_API_KEY)}


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")
