import os
import json
import queue
import threading
import uuid
from datetime import datetime

import requests
import sounddevice as sd
import yfinance as yf
from vosk import Model, KaldiRecognizer
from dotenv import load_dotenv

load_dotenv()

# Constants
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
NEWS_API_KEY        = os.getenv("NEWS_API_KEY")
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY")

CITY             = "Syracuse"
MAX_STOCK_SLOTS  = 3
STOCK_SYMBOLS    = ["AAPL", "BA", "BAC"]

# Refresh intervals (ms)
WEATHER_REFRESH_MS = 10 * 60 * 1000
NEWS_REFRESH_MS    = 15 * 60 * 1000
NEWS_CYCLE_MS      =  7 * 1000
STOCK_REFRESH_MS   =  5 * 60 * 1000

# Voice (Pi-friendly: smaller block size)
VOSK_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models/vosk-model-small-en-us-0.15")
SAMPLE_RATE     = 16000
BLOCK_SIZE      = 3200          # ~0.2 s – lower latency on ARM
WAKE_GRAMMAR    = json.dumps(["hey mirror", "[unk]"])

# Global state
_weather_cache    = "Loading..."
_weather_api_data = {}
_news_cache       = []
_stock_cache      = ["Loading..." for _ in STOCK_SYMBOLS]
_todo_tasks       = []

_ai_state  = "idle"
_ai_text   = ""
_ui_queue  = queue.Queue()
_audio_queue = queue.Queue()

_root_ref       = None
_stock_card_ref = None
_todo_card_ref  = None

_widget_refs = {}
_widget_visibility = {
    "datetime": True, "news": True, "stocks": True, "ai": True, "todo": True,
}

_tracking_enabled = False
_running          = True

# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────
def bg(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()

def set_ai_state(state, text=""):
    global _ai_state, _ai_text
    _ai_state, _ai_text = state, text

def post_ui_state(state, text=""):
    _ui_queue.put((state, text))

# ─────────────────────────────────────────────
# TODO  (JSON persistence)
# ─────────────────────────────────────────────
TODO_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data/mirror_todos.json")

def load_todos():
    global _todo_tasks
    try:
        with open(TODO_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("tasks", [])
        out = []
        for i, item in enumerate(raw if isinstance(raw, list) else []):
            if isinstance(item, str) and item.strip():
                out.append({"id": f"legacy{i}", "text": item.strip()})
            elif isinstance(item, dict):
                txt = (item.get("text") or "").strip()
                if txt:
                    out.append({"id": str(item.get("id") or uuid.uuid4().hex[:12]), "text": txt})
        _todo_tasks = out
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        _todo_tasks = []

def save_todos():
    try:
        with open(TODO_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump({"tasks": _todo_tasks}, f, indent=2, ensure_ascii=False)
    except OSError:
        pass

def _todo_payload_is_meaningful(tb):
    if not isinstance(tb, dict) or not tb:
        return False
    return any([
        tb.get("set") is not None,
        tb.get("clear") is True,
        tb.get("add"),
        tb.get("remove"),
        tb.get("remove_indices"),
    ])

def apply_todo_from_ai(todo_block):
    global _todo_tasks
    if not isinstance(todo_block, dict):
        return False

    full_set = todo_block.get("set")
    if isinstance(full_set, list):
        _todo_tasks = [
            {"id": uuid.uuid4().hex[:12], "text": i.strip()}
            for i in full_set if isinstance(i, str) and i.strip()
        ]
        save_todos()
        if _todo_card_ref:
            _todo_card_ref.refresh_list()
        return True

    changed = False
    if todo_block.get("clear") is True and _todo_tasks:
        _todo_tasks = []; changed = True

    for v in (todo_block.get("remove_indices") or []):
        try:
            idx = int(v) - 1
            if 0 <= idx < len(_todo_tasks):
                _todo_tasks.pop(idx); changed = True
        except (TypeError, ValueError):
            pass

    for r in (todo_block.get("remove") or []):
        if isinstance(r, str) and r.strip():
            before = len(_todo_tasks)
            _todo_tasks = [x for x in _todo_tasks if x["text"].lower() != r.strip().lower()]
            if len(_todo_tasks) < before: changed = True

    for a in (todo_block.get("add") or []):
        if isinstance(a, str) and a.strip():
            t = a.strip()
            if not any(x["text"].lower() == t.lower() for x in _todo_tasks):
                _todo_tasks.append({"id": uuid.uuid4().hex[:12], "text": t}); changed = True

    if changed:
        save_todos()
        if _todo_card_ref:
            _todo_card_ref.refresh_list()
    return changed

def get_todo_context_lines():
    lines = ["--- To-do list (numbered for remove_indices) ---"]
    if not _todo_tasks:
        lines.append("  (empty)")
    else:
        for i, t in enumerate(_todo_tasks, 1):
            lines.append(f"  {i}. {t['text']}")
    return lines

# ─────────────────────────────────────────────
# WEATHER / NEWS / STOCKS
# ─────────────────────────────────────────────
def fetch_weather():
    global _weather_cache, _weather_api_data
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": CITY, "appid": OPENWEATHER_API_KEY, "units": "imperial"},
            timeout=5,
        )
        data = r.json()
        if "main" not in data:
            _weather_cache = "Weather N/A"; _weather_api_data = {}; return
        _weather_api_data = data
        _weather_cache = f"{data['main']['temp']:.0f}°F  {data['weather'][0]['description'].title()}"
    except Exception:
        _weather_cache = "Weather N/A"; _weather_api_data = {}

def fetch_news():
    global _news_cache
    try:
        r = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={"country": "us", "pageSize": 10, "apiKey": NEWS_API_KEY},
            timeout=5,
        )
        articles = r.json().get("articles", [])
        results = []
        for a in articles:
            pub_str = ""
            try:
                dt = datetime.strptime(a.get("publishedAt", ""), "%Y-%m-%dT%H:%M:%SZ")
                pub_str = dt.strftime("%m.%d.%Y, %H:%M")
            except Exception:
                pass
            results.append({
                "title":       a.get("title", "No title"),
                "source":      a.get("source", {}).get("name", ""),
                "pub":         pub_str,
                "description": (a.get("description") or "").strip(),
                "url":         (a.get("url") or "").strip(),
                "author":      (a.get("author") or "").strip(),
            })
        _news_cache = results or [{"title": "News unavailable", "source": "", "pub": "",
                                   "description": "", "url": "", "author": ""}]
    except Exception:
        _news_cache = [{"title": "News unavailable", "source": "", "pub": "",
                        "description": "", "url": "", "author": ""}]

def fetch_stocks():
    global _stock_cache
    results = []
    for sym in STOCK_SYMBOLS:
        try:
            info   = yf.Ticker(sym).fast_info
            price  = info.last_price
            prev   = info.previous_close
            change = price - prev
            pct    = (change / prev) * 100
            arrow  = "▲" if change >= 0 else "▼"
            results.append(f"{sym}  ${price:.2f}  {arrow}{abs(change):.2f} ({abs(pct):.2f}%)")
        except Exception:
            results.append(f"{sym}: N/A")
    _stock_cache = results
    if _root_ref:
        _root_ref.after(0, _redraw_stocks)

def _redraw_stocks():
    if _stock_card_ref:
        _stock_card_ref.apply_cache_to_canvas()

# ─────────────────────────────────────────────
# AI CONTEXT + RESPONSE
# ─────────────────────────────────────────────
def _fmt_weather():
    if not _weather_api_data:
        return f"(no structured data; banner: {_weather_cache})"
    try:
        return json.dumps(_weather_api_data, indent=2, ensure_ascii=False)
    except Exception:
        return str(_weather_api_data)

def get_mirror_context():
    now = datetime.now()
    lines = [
        "=== SMART MIRROR LIVE CONTEXT ===",
        f"Local date/time: {now.strftime('%A, %B %d, %Y %I:%M:%S %p')}",
        f"City: {CITY}",
        "",
        "--- OpenWeather ---",
        _fmt_weather(),
        "",
        "--- NewsAPI US top headlines ---",
    ]
    for i, a in enumerate(_news_cache, 1):
        lines += [
            f"{i}. {a.get('title','')}",
            f"   Source: {a.get('source','')}  |  {a.get('pub','')}",
            f"   {a.get('description','')}"
        ]
    lines += [
        "",
        f"--- Stocks ({', '.join(STOCK_SYMBOLS)}) ---",
        *[f"  {s}" for s in _stock_cache],
        "",
        *get_todo_context_lines(),
        "",
        "--- Widget visibility ---",
        *[f"  {k}: {'visible' if _widget_visibility.get(k,True) else 'hidden'}"
          for k in ("datetime","news","stocks","ai","todo")],
        "=== END CONTEXT ===",
    ]
    return "\n".join(lines)

def _parse_ai_json(text):
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        lines = raw.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e > s:
            try:
                data = json.loads(raw[s:e+1])
            except json.JSONDecodeError:
                return None
        else:
            return None
    if not isinstance(data, dict):
        return None
    msg  = data.get("message") or data.get("say") or data.get("reply") or ""
    stks = data.get("stocks")
    vis  = data.get("visibility")
    todo = data.get("todo")
    return {
        "message":    str(msg).strip(),
        "stocks":     stks if isinstance(stks, list) else None,
        "visibility": vis  if isinstance(vis,  dict) else None,
        "todo":       todo if isinstance(todo, dict) else None,
    }

def _normalize_ticker(s):
    return "".join(c for c in s.strip().upper() if c.isalnum() or c == ".")

def apply_stock_symbols(new_list):
    global STOCK_SYMBOLS
    if not new_list or len(new_list) != MAX_STOCK_SLOTS:
        return False
    cleaned, seen = [], set()
    for item in new_list:
        t = _normalize_ticker(item)
        if t and t not in seen:
            seen.add(t); cleaned.append(t)
        if len(cleaned) >= MAX_STOCK_SLOTS:
            break
    if len(cleaned) != MAX_STOCK_SLOTS:
        return False
    STOCK_SYMBOLS = cleaned
    return True

def apply_visibility(updates):
    global _widget_visibility
    if not updates:
        return
    for key, val in updates.items():
        if key in _widget_refs and isinstance(val, bool):
            _widget_refs[key].mirror_set_visible(val)
            _widget_visibility[key] = val

def fetch_ai_response(prompt):
    if not OPENAI_API_KEY:
        post_ui_state("error", "OPENAI_API_KEY not set in .env"); return
    post_ui_state("thinking", "Mirror thinking...")
    try:
        full_input = (
            "You are the voice assistant for a smart mirror. "
            "Use the live context below to answer. "
            f"Stocks widget shows exactly {MAX_STOCK_SLOTS} tickers. "
            f"Current: {', '.join(STOCK_SYMBOLS)}. "
            "If watchlist changes are requested, return the full new ordered list in \"stocks\". "
            "Optional \"visibility\" dict: keys datetime/news/stocks/ai/todo, bool values. "
            "Optional \"todo\" dict: add/remove/remove_indices/set/clear. "
            "Reply ONLY valid JSON: "
            '{"message":"...","stocks":null,"visibility":null,"todo":null}\n\n'
            f"{get_mirror_context()}\n\nUser: {prompt}"
        )
        r = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4.1-mini", "input": full_input, "max_output_tokens": 480},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()

        text = (data.get("output_text") or "").strip()
        if not text:
            parts = []
            for item in data.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        parts.append(content.get("text", "").strip())
            text = "\n".join(parts).strip()
        if not text:
            text = f"No response. Keys: {list(data.keys())}"

        parsed = _parse_ai_json(text)
        if parsed:
            msg    = parsed["message"]
            stocks = parsed["stocks"]
            vis    = parsed["visibility"]
            todo   = parsed["todo"]

            if isinstance(stocks, list) and len(stocks) == MAX_STOCK_SLOTS:
                def _do_stocks():
                    if apply_stock_symbols(stocks) and _stock_card_ref:
                        _stock_card_ref.resync_lines()
                    bg(fetch_stocks)
                if _root_ref: _root_ref.after(0, _do_stocks)

            if isinstance(vis, dict) and vis:
                if _root_ref: _root_ref.after(0, lambda: apply_visibility(vis))

            if _todo_payload_is_meaningful(todo):
                if _root_ref: _root_ref.after(0, lambda: apply_todo_from_ai(todo))

            display = msg or ("Watchlist updated." if stocks else
                              ("OK." if isinstance(vis, dict) and vis else
                               ("To-do updated." if _todo_payload_is_meaningful(todo) else text[:500])))
            post_ui_state("response", display)
        else:
            post_ui_state("response", text[:500])
    except Exception as e:
        post_ui_state("error", f"AI Error: {e}")

# ─────────────────────────────────────────────
# AUDIO CALLBACK
# ─────────────────────────────────────────────
def _audio_callback(indata, frames, time_info, status):
    if status:
        print(f"[Audio] {status}")
    _audio_queue.put(bytes(indata))

# ─────────────────────────────────────────────
# VOICE LOOP  (offline Vosk wake word)
# ─────────────────────────────────────────────
def voice_loop():
    if not os.path.exists(VOSK_MODEL_PATH):
        post_ui_state("error", f"Vosk model not found:\n{VOSK_MODEL_PATH}"); return
    try:
        model    = Model(VOSK_MODEL_PATH)
        wake_rec = KaldiRecognizer(model, SAMPLE_RATE, WAKE_GRAMMAR)
        post_ui_state("idle", "")

        with sd.RawInputStream(
            samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE,
            dtype="int16", channels=1, callback=_audio_callback,
        ):
            state = "wake"
            cmd_rec = None
            heard_speech = False
            silence_chunks = 0
            cmd_parts = []
            chunk_limit = 40

            while _running:
                data = _audio_queue.get()

                if state == "wake":
                    # ONLY FEATURE: Disable voice when hand control is on
                    if _tracking_enabled:
                        continue
                    
                    detected = False
                    if wake_rec.AcceptWaveform(data):
                        if "hey mirror" in json.loads(wake_rec.Result()).get("text", "").lower():
                            detected = True
                    elif "hey mirror" in json.loads(wake_rec.PartialResult()).get("partial", "").lower():
                        detected = True

                    if detected:
                        print("[Wake] hey mirror detected")
                        post_ui_state("listening", "Listening...")
                        cmd_rec = KaldiRecognizer(model, SAMPLE_RATE)
                        heard_speech = silence_chunks = 0
                        cmd_parts = []; chunk_limit = 40
                        state = "command"

                elif state == "command":
                    if cmd_rec.AcceptWaveform(data):
                        t = json.loads(cmd_rec.Result()).get("text", "").strip()
                        if t:
                            cmd_parts.append(t); heard_speech = True; silence_chunks = 0
                    else:
                        p = json.loads(cmd_rec.PartialResult()).get("partial", "").strip()
                        if p:
                            heard_speech = True; silence_chunks = 0
                        elif heard_speech:
                            silence_chunks += 1
                    chunk_limit -= 1

                    if (heard_speech and silence_chunks >= 4) or chunk_limit <= 0:
                        final = json.loads(cmd_rec.FinalResult()).get("text", "").strip()
                        if final: cmd_parts.append(final)
                        prompt = " ".join(p for p in cmd_parts if p).strip()
                        print(f"[Command] {prompt}")
                        if prompt:
                            bg(fetch_ai_response, prompt)
                        else:
                            post_ui_state("idle", "")
                        wake_rec = KaldiRecognizer(model, SAMPLE_RATE, WAKE_GRAMMAR)
                        state = "wake"; cmd_rec = None
                        heard_speech = silence_chunks = 0
                        cmd_parts = []; chunk_limit = 40
    except Exception as e:
        post_ui_state("error", f"Voice Error: {e}")
