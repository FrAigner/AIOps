"""KI-Analyse-Chat: fragt ein kleines lokales Ollama-Modell ueber den
Zustand der Plattform aus.

Architekturentscheidung: das Modell ist klein (1-3B Parameter, siehe README),
weil nur ~1,9 GB RAM-Headroom neben dem bestehenden Stack zur Verfuegung
stehen. Kleine Modelle rufen Tools unzuverlaessig auf - deshalb haengt die
Grundqualitaet der Antwort nicht von Tool-Use ab, sondern von einem
deterministisch zusammengestellten Kontext-Buendel (siehe context.py), das
bei jeder Anfrage neu eingesammelt wird. Tools (tools.py) sind nur fuer
Drill-down da, wenn das Modell sie tatsaechlich sauber aufruft; wenn nicht,
bleibt die Antwort trotzdem brauchbar.
"""

from __future__ import annotations

import json
import os

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from context import gather_context
from tools import TOOL_SCHEMAS, run_tool

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
# qwen2.5 traegt ueber die gesamte Groessenreihe (0.5b-72b) den "Tools"-Tag in
# der Ollama-Bibliothek und ist fuer Function-Calling trainiert - bei gleicher
# Groessenklasse zuverlaessiger als llama3.2. 1.5b passt mit ~1-1.5 GiB
# geladenem Speicherbedarf in den gemessenen ~1,9 GiB RAM-Headroom.
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
# Gemessen: ohne Deckel driftet das 1,5B-Modell bei einfachen Fragen in
# seitenlange Erklaerungen ab (89s fuer eine 3-Wort-Antwort auf "Sag nur OK.").
# Ein hartes Token-Limit begrenzt den Schaden unabhaengig davon, ob das
# Modell der Kuerze-Anweisung im Prompt folgt oder nicht.
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "150"))
MAX_TOOL_ROUNDS = 2  # kleines Modell -> Latenz und Fehlerfortpflanzung begrenzen
MAX_HISTORY_MESSAGES = 12  # Kontext-Buendel allein braucht schon einige hundert Tokens

SYSTEM_PROMPT = (
    "Du bist der Analyse-Assistent eines Observability-Systems fuer einen "
    "Onlineshop und dessen Filiale. Du bekommst bei jeder Anfrage den aktuellen "
    "Systemzustand (Alarme, Kennzahlen, Abhaengigkeiten) als Text mitgeliefert. "
    "Antworte IMMER auf Deutsch, in maximal 3 kurzen Saetzen. Keine Einleitung, "
    "keine Wiederholung der Frage, keine Nebenbemerkungen - direkt die Antwort "
    "mit konkreten Zahlen aus dem gelieferten Kontext. Nutze die angebotenen "
    "Werkzeuge nur, wenn eine Frage Details verlangt, die im Kontext nicht "
    "stehen. Wenn du unsicher bist, sag das in einem Satz, statt Zahlen zu "
    "erfinden oder abzuschweifen."
)

app = FastAPI(title="AIOps Analyse-Chat")


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


class ChatResponse(BaseModel):
    reply: str
    context: str


async def _ollama_chat(messages: list[dict], use_tools: bool, timeout: float = 150) -> dict:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"num_ctx": OLLAMA_NUM_CTX, "num_predict": OLLAMA_NUM_PREDICT},
    }
    if use_tools:
        payload["tools"] = TOOL_SCHEMAS
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
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
            parsed.append({"name": name, "arguments": args or {}})
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
            data = await _ollama_chat(messages, use_tools=True)
            message = data.get("message", {})
            tool_calls = _extract_tool_calls(message)

            if not tool_calls:
                content = message.get("content", "").strip()
                return content or "Ich konnte dazu keine Antwort formulieren.", context_block

            messages.append(message)
            for call in tool_calls:
                result = await run_tool(call["name"], call["arguments"])
                messages.append({"role": "tool", "content": result, "name": call["name"]})

        # Letzter Versuch ohne Tools, damit ein feststeckendes Modell nicht leer ausgeht.
        data = await _ollama_chat(messages, use_tools=False)
        content = data.get("message", {}).get("content", "").strip()
        return content or "Ich konnte dazu keine Antwort formulieren.", context_block

    except httpx.HTTPError as exc:
        return (
            f"Das lokale Sprachmodell ist gerade nicht erreichbar ({exc}). "
            "Der Systemzustand rechts ist trotzdem aktuell.",
            context_block,
        )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    reply, context_block = await run_chat(req.message, req.history)
    return ChatResponse(reply=reply, context=context_block)


@app.get("/health")
async def health():
    return {"status": "ok", "model": OLLAMA_MODEL}


@app.on_event("startup")
async def warmup() -> None:
    # Ohne Vorabladen dauert die erste echte Chat-Anfrage nach einem Neustart
    # spuerbar laenger (Modell-Load von Disk in den Ollama-Prozess). Ein
    # fehlgeschlagener Warmup (Ollama noch nicht bereit) ist kein Fehler -
    # die erste echte Anfrage laedt das Modell dann eben selbst nach.
    try:
        await _ollama_chat([{"role": "user", "content": "hallo"}], use_tools=False, timeout=150)
    except Exception:
        pass


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")
