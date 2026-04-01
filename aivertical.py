import os
import json
import queue
import threading
import uuid
import tkinter as tk
import requests
import yfinance as yf
import sounddevice as sd
from vosk import Model, KaldiRecognizer
from datetime import datetime
from dotenv import load_dotenv

# Second monitor connection COMMENT OUT IF NO SECOND MONITOR
from screeninfo import get_monitors
monitors = get_monitors()

load_dotenv()

# =========================
# CONFIG
# =========================
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

CITY = "Syracuse"
MAX_STOCK_SLOTS = 3
STOCK_SYMBOLS = ["AAPL", "BA", "BAC"]

WEATHER_REFRESH_MS = 10 * 60 * 1000
NEWS_REFRESH_MS    = 15 * 60 * 1000
NEWS_CYCLE_MS      = 7 * 1000
STOCK_REFRESH_MS   = 5 * 60 * 1000
CLOCK_REFRESH_MS   = 1000

BG_COLOR    = "black"
BOX_COLOR   = "#1c1c1e"
BOX_OUTLINE = "#2f2f2f"
FG_COLOR    = "white"
DIM_COLOR   = "#888888"

FONT_TITLE    = ("Arial", 14, "bold")
FONT_BODY     = ("Arial", 13)
FONT_COMPACT  = ("Arial", 12)

WIDGET_PAD = 10

TODO_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mirror_todos.json")
TODO_LINE_HEIGHT = 30
TODO_MAX_VISIBLE_LINES = 14
TODO_CARD_WIDTH = 340

# =========================
# OFFLINE VOICE CONFIG
# =========================
VOSK_MODEL_PATH = "/Users/kenny/Downloads/vosk-model-small-en-us-0.15"  # update this path to your Vosk model
SAMPLE_RATE = 16000
BLOCK_SIZE = 4000  # smaller = more responsive
WAKE_GRAMMAR = json.dumps(["hey mirror", "[unk]"])

# =========================
# API CACHE
# =========================
_weather_cache = "Loading..."
_weather_api_data = {}  # full OpenWeather JSON (for AI context)
_news_cache    = []
_stock_cache   = ["Loading..." for _ in STOCK_SYMBOLS]
_todo_tasks = []  # [{"id": str, "text": str}, ...]

# =========================
# AI WIDGET STATE
# =========================
_ai_state = "idle"   # idle, listening, thinking, response, error
_ai_text  = ""
_ui_queue = queue.Queue()
_audio_queue = queue.Queue()

_root_ref = None
_stock_card_ref = None
_todo_card_ref = None

# Keys: datetime (clock/weather), news, stocks, ai, todo — filled after widgets are built
_widget_refs = {}
_widget_visibility = {
    "datetime": True, "news": True, "stocks": True, "ai": True, "todo": True,
}

def set_ai_state(state, text=""):
    global _ai_state, _ai_text
    _ai_state = state
    _ai_text = text

def post_ui_state(state, text=""):
    _ui_queue.put((state, text))

def bg(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()

# =========================
# TODO LIST (JSON persistence)
# =========================
def load_todos():
    global _todo_tasks
    try:
        with open(TODO_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("tasks", [])
        if not isinstance(raw, list):
            raw = []
        out = []
        for i, item in enumerate(raw):
            if isinstance(item, str) and item.strip():
                out.append({"id": f"legacy{i}", "text": item.strip()})
            elif isinstance(item, dict):
                txt = (item.get("text") or "").strip()
                if not txt:
                    continue
                tid = str(item.get("id") or uuid.uuid4().hex[:12])
                out.append({"id": tid, "text": txt})
        _todo_tasks = out
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        _todo_tasks = []

def save_todos():
    try:
        with open(TODO_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump({"tasks": _todo_tasks}, f, indent=2, ensure_ascii=False)
    except OSError:
        pass

def apply_todo_from_ai(todo_block):
    """Apply todo ops from the model; persist and redraw widget. Main thread only."""
    global _todo_tasks
    if not todo_block or not isinstance(todo_block, dict):
        return False

    full_set = todo_block.get("set")
    if isinstance(full_set, list):
        new = []
        for item in full_set:
            if isinstance(item, str) and item.strip():
                new.append({"id": uuid.uuid4().hex[:12], "text": item.strip()})
        _todo_tasks = new
        save_todos()
        if _todo_card_ref is not None:
            _todo_card_ref.refresh_list()
        return True

    changed = False
    if todo_block.get("clear") is True:
        if _todo_tasks:
            _todo_tasks = []
            changed = True

    ridx_list = todo_block.get("remove_indices") or []
    if isinstance(ridx_list, list) and ridx_list:
        indices = []
        for v in ridx_list:
            try:
                if isinstance(v, (int, float)):
                    indices.append(int(v) - 1)
                elif isinstance(v, str) and v.strip().isdigit():
                    indices.append(int(v.strip()) - 1)
            except (TypeError, ValueError):
                continue
        for idx in sorted(set(indices), reverse=True):
            if 0 <= idx < len(_todo_tasks):
                _todo_tasks.pop(idx)
                changed = True

    rems = todo_block.get("remove") or []
    if isinstance(rems, list):
        for r in rems:
            if isinstance(r, str) and r.strip():
                rl = r.strip().lower()
                before = len(_todo_tasks)
                _todo_tasks = [x for x in _todo_tasks if x["text"].lower() != rl]
                if len(_todo_tasks) < before:
                    changed = True

    adds = todo_block.get("add") or []
    if isinstance(adds, list):
        for a in adds:
            if isinstance(a, str) and a.strip():
                t = a.strip()
                if not any(x["text"].lower() == t.lower() for x in _todo_tasks):
                    _todo_tasks.append({"id": uuid.uuid4().hex[:12], "text": t})
                    changed = True

    if changed:
        save_todos()
        if _todo_card_ref is not None:
            _todo_card_ref.refresh_list()
    return changed

def _todo_payload_is_meaningful(todo_block):
    if not isinstance(todo_block, dict) or not todo_block:
        return False
    if todo_block.get("set") is not None:
        return True
    if todo_block.get("clear") is True:
        return True
    if todo_block.get("add"):
        return True
    if todo_block.get("remove"):
        return True
    if todo_block.get("remove_indices"):
        return True
    return False

def get_todo_context_lines():
    lines = ["--- To-do list (numbered for remove_indices) ---"]
    if not _todo_tasks:
        lines.append("  (empty)")
    else:
        for i, task in enumerate(_todo_tasks, start=1):
            lines.append(f"  {i}. {task['text']}")
    return lines

# =========================
# WEATHER / NEWS / STOCKS
# =========================
def fetch_weather():
    global _weather_cache, _weather_api_data
    try:
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {"q": CITY, "appid": OPENWEATHER_API_KEY, "units": "imperial"}
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        if "main" not in data:
            _weather_cache = "Weather N/A"
            _weather_api_data = {}
            return
        _weather_api_data = data
        temp = data["main"]["temp"]
        desc = data["weather"][0]["description"].title()
        _weather_cache = f"{temp:.0f}°F  {desc}"
    except Exception:
        _weather_cache = "Weather N/A"
        _weather_api_data = {}

def fetch_news():
    global _news_cache
    try:
        url = "https://newsapi.org/v2/top-headlines"
        params = {"country": "us", "pageSize": 10, "apiKey": NEWS_API_KEY}
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        articles = data.get("articles", [])
        results = []
        for a in articles:
            title = a.get("title", "No title")
            source = a.get("source", {}).get("name", "")
            published = a.get("publishedAt", "")
            try:
                dt = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ")
                pub_str = dt.strftime("%m.%d.%Y, %H:%M")
            except Exception:
                pub_str = ""
            results.append({
                "title": title,
                "source": source,
                "pub": pub_str,
                "description": (a.get("description") or "").strip(),
                "url": (a.get("url") or "").strip(),
                "author": (a.get("author") or "").strip(),
            })
        _news_cache = results if results else [{
            "title": "News unavailable", "source": "", "pub": "",
            "description": "", "url": "", "author": "",
        }]
    except Exception:
        _news_cache = [{
            "title": "News unavailable", "source": "", "pub": "",
            "description": "", "url": "", "author": "",
        }]

def _schedule_stock_card_redraw():
    """Must run on main thread; safe to call from worker via root.after(0, ...)."""
    if _root_ref is not None and _stock_card_ref is not None:
        _stock_card_ref.apply_cache_to_canvas()

def fetch_stocks():
    global _stock_cache
    results = []
    for sym in STOCK_SYMBOLS:
        try:
            ticker = yf.Ticker(sym)
            info   = ticker.fast_info
            price  = info.last_price
            prev   = info.previous_close
            change = price - prev
            pct    = (change / prev) * 100
            arrow  = "▲" if change >= 0 else "▼"
            results.append(f"{sym}  ${price:.2f}  {arrow}{abs(change):.2f} ({abs(pct):.2f}%)")
        except Exception:
            results.append(f"{sym}: N/A")
    _stock_cache = results
    if _root_ref is not None:
        _root_ref.after(0, _schedule_stock_card_redraw)

def _fmt_weather_for_context():
    if not _weather_api_data:
        return f"(no structured data; banner text: {_weather_cache})"
    try:
        return json.dumps(_weather_api_data, indent=2, ensure_ascii=False)
    except Exception:
        return str(_weather_api_data)

def get_mirror_context_for_ai():
    """Everything the mirror widgets know: time, OpenWeather payload, NewsAPI articles, stocks."""
    now = datetime.now()
    lines = [
        "=== SMART MIRROR LIVE CONTEXT ===",
        f"Local date/time: {now.strftime('%A, %B %d, %Y %I:%M:%S %p')}",
        f"Configured city label: {CITY}",
        "",
        "--- OpenWeather (current weather API response) ---",
        _fmt_weather_for_context(),
        "",
        "--- NewsAPI (US top headlines; fields per article) ---",
    ]
    for i, a in enumerate(_news_cache, 1):
        lines.append(f"{i}. Title: {a.get('title', '')}")
        lines.append(f"   Source: {a.get('source', '')}  |  Published: {a.get('pub', '')}")
        if a.get("author"):
            lines.append(f"   Author: {a['author']}")
        if a.get("description"):
            lines.append(f"   Description: {a['description']}")
        if a.get("url"):
            lines.append(f"   URL: {a['url']}")
        lines.append("")
    lines.append("--- Stocks widget (symbols: " + ", ".join(STOCK_SYMBOLS) + ") ---")
    for s in _stock_cache:
        lines.append(f"  {s}")
    lines.extend(get_todo_context_lines())
    lines.append("")
    lines.append(
        "--- Widget visibility (user can hide/show via voice; you control with JSON) ---"
    )
    for k in ("datetime", "news", "stocks", "ai", "todo"):
        vis = _widget_visibility.get(k, True)
        lines.append(f"  {k}: {'visible' if vis else 'hidden'}")
    lines.append("=== END CONTEXT ===")
    return "\n".join(lines)

def _parse_ai_json_response(text):
    """Strip optional markdown fences and parse JSON with message + optional stocks."""
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    data = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None
        else:
            return None
    if not isinstance(data, dict):
        return None
    msg = data.get("message")
    if msg is None:
        msg = data.get("say") or data.get("reply")
    stocks = data.get("stocks")
    if stocks is not None and not isinstance(stocks, list):
        stocks = None
    vis = data.get("visibility")
    if vis is not None and not isinstance(vis, dict):
        vis = None
    todo = data.get("todo")
    if todo is not None and not isinstance(todo, dict):
        todo = None
    return {
        "message": (msg if isinstance(msg, str) else str(msg)).strip(),
        "stocks": stocks,
        "visibility": vis,
        "todo": todo,
    }

def _normalize_ticker(s):
    if not isinstance(s, str):
        return ""
    t = s.strip().upper()
    return "".join(c for c in t if c.isalnum() or c == ".")

def apply_stock_symbols_from_ai(new_list):
    """Set watchlist to exactly MAX_STOCK_SLOTS tickers from the model (deduped, order kept)."""
    global STOCK_SYMBOLS
    if not new_list or len(new_list) != MAX_STOCK_SLOTS:
        return False
    cleaned = []
    seen = set()
    for item in new_list:
        t = _normalize_ticker(item)
        if not t or t in seen:
            continue
        seen.add(t)
        cleaned.append(t)
        if len(cleaned) >= MAX_STOCK_SLOTS:
            break
    if len(cleaned) != MAX_STOCK_SLOTS:
        return False
    STOCK_SYMBOLS = cleaned[:MAX_STOCK_SLOTS]
    return True

def apply_widget_visibility_from_ai(visibility_updates):
    """Show/hide mirror cards; restore previous place() coords. Main thread only."""
    global _widget_visibility
    if not visibility_updates:
        return
    for key, val in visibility_updates.items():
        if key not in _widget_refs:
            continue
        if not isinstance(val, bool):
            continue
        w = _widget_refs[key]
        w.mirror_set_visible(val)
        _widget_visibility[key] = val

def fetch_ai_response(prompt):
    if not OPENAI_API_KEY:
        post_ui_state("error", "OPENAI_API_KEY not found in .env")
        return

    post_ui_state("thinking", "Mirror thinking...")

    try:
        url = "https://api.openai.com/v1/responses"
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        context_block = get_mirror_context_for_ai()
        full_input = (
            "You are the voice assistant for this smart mirror. The following block is live data "
            "from the mirror's widgets (OpenWeather, NewsAPI, stocks, and local time). "
            "Use it to answer questions about weather, news, stocks, date, and time. "
            "If the user asks for something not in the context, use general knowledge.\n\n"
            "STOCK WATCHLIST CONTROL: The stocks widget shows exactly "
            f"{MAX_STOCK_SLOTS} tickers in order (first = top line). Current tickers are: "
            f"{', '.join(STOCK_SYMBOLS)}.\n"
            "If the user asks to show a stock, add one, put one first, replace one, or remove one, "
            "you MUST set the JSON key \"stocks\" to the new full ordered list of exactly "
            f"{MAX_STOCK_SLOTS} Yahoo Finance ticker symbols (uppercase). "
            "Example: \"show me Microsoft stock\" / \"put Microsoft first\" → drop the last slot "
            "if needed and use [\"MSFT\", then the previous first two in order], e.g. "
            '[\"MSFT\",\"AAPL\",\"BA\"] when the list was AAPL, BA, BAC.\n'
            "If the user does NOT ask to change the watchlist, set \"stocks\" to null.\n\n"
            "WIDGET VISIBILITY: Optional key \"visibility\" (object). Keys: "
            "\"datetime\" (clock/weather bar), \"news\", \"stocks\", \"ai\", \"todo\". "
            "Values true = show, false = hide. Only include keys the user asked to change. "
            'Examples: hide stocks → "visibility": {"stocks": false}. '
            'Show stocks again → "visibility": {"stocks": true}. '
            "Hiding removes the widget from view but its position is remembered.\n\n"
            "TODO LIST: The numbered list in context is the current saved to-do list. "
            "Optional key \"todo\" (object) with any of: "
            "\"add\" string array (append), \"remove\" string array "
            "(remove lines matching text, case-insensitive), \"remove_indices\" "
            "(1-based integers from the list in context), \"set\" string array "
            "(replace entire list in order; use [] to clear via set), "
            "\"clear\" true (empty all). Omit \"todo\" or use null if the user is not editing todos.\n\n"
            "Reply format: respond with ONLY valid JSON, no markdown fences, one object with keys:\n"
            '{"message":"...", "stocks":null or [SYM1,SYM2,SYM3], '
            '"visibility":null or object, '
            '"todo":null or {"add":[],"remove":[],"remove_indices":[],"set":null,"clear":false}}\n\n'
            f"{context_block}\n\n"
            "--- User said (voice command) ---\n"
            f"{prompt}"
        )
        payload = {
            "model": "gpt-4.1-mini",
            "input": full_input,
            "max_output_tokens": 480
        }

        r = requests.post(url, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()

        text = (data.get("output_text") or "").strip()

        if not text:
            parts = []
            for item in data.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        t = content.get("text", "").strip()
                        if t:
                            parts.append(t)
            text = "\n".join(parts).strip()

        if not text:
            text = f"No response returned.\n\nRaw response keys: {list(data.keys())}"

        parsed = _parse_ai_json_response(text)

        if parsed:
            msg = (parsed.get("message") or "").strip()
            stocks_update = parsed.get("stocks")
            vis_update = parsed.get("visibility")
            todo_update = parsed.get("todo")

            if isinstance(stocks_update, list) and len(stocks_update) == MAX_STOCK_SLOTS:
                def _apply_stocks():
                    if apply_stock_symbols_from_ai(stocks_update) and _stock_card_ref is not None:
                        _stock_card_ref.resync_lines()
                    bg(fetch_stocks)

                if _root_ref is not None:
                    _root_ref.after(0, _apply_stocks)

            if isinstance(vis_update, dict) and vis_update:
                def _apply_vis():
                    apply_widget_visibility_from_ai(vis_update)

                if _root_ref is not None:
                    _root_ref.after(0, _apply_vis)

            if _todo_payload_is_meaningful(todo_update):
                def _apply_todo():
                    apply_todo_from_ai(todo_update)

                if _root_ref is not None:
                    _root_ref.after(0, _apply_todo)

            if msg:
                display = msg
            elif stocks_update:
                display = "Watchlist updated."
            elif isinstance(vis_update, dict) and vis_update:
                display = "OK."
            elif _todo_payload_is_meaningful(todo_update):
                display = "To-do updated."
            else:
                display = text[:500]
            post_ui_state("response", display)
        else:
            post_ui_state("response", text)

    except Exception as e:
        post_ui_state("error", f"AI Error: {e}")

# =========================
# AUDIO CALLBACK
# =========================
def audio_callback(indata, frames, time_info, status):
    if status:
        print(status)
    _audio_queue.put(bytes(indata))

# =========================
# OFFLINE WAKE + COMMAND LOOP
# =========================
def voice_loop():
    if not os.path.exists(VOSK_MODEL_PATH):
        post_ui_state("error", f"Missing model:\n{VOSK_MODEL_PATH}")
        return

    try:
        model = Model(VOSK_MODEL_PATH)
        wake_rec = KaldiRecognizer(model, SAMPLE_RATE, WAKE_GRAMMAR)

        post_ui_state("idle", "")

        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            dtype="int16",
            channels=1,
            callback=audio_callback
        ):
            state = "wake"
            cmd_rec = None
            heard_speech = False
            silence_chunks = 0
            command_text_parts = []
            command_chunk_limit = 40  # safety cap

            while True:
                data = _audio_queue.get()

                if state == "wake":
                    detected = False

                    if wake_rec.AcceptWaveform(data):
                        result = json.loads(wake_rec.Result())
                        text = result.get("text", "").strip().lower()
                        if "hey mirror" in text:
                            detected = True
                    else:
                        partial = json.loads(wake_rec.PartialResult()).get("partial", "").strip().lower()
                        if "hey mirror" in partial:
                            detected = True

                    if detected:
                        print("[Wake] hey mirror detected")
                        post_ui_state("listening", "Mirror listening...")

                        cmd_rec = KaldiRecognizer(model, SAMPLE_RATE)
                        heard_speech = False
                        silence_chunks = 0
                        command_text_parts = []
                        state = "command"

                elif state == "command":
                    if cmd_rec.AcceptWaveform(data):
                        result = json.loads(cmd_rec.Result())
                        text = result.get("text", "").strip()
                        if text:
                            command_text_parts.append(text)
                            heard_speech = True
                            silence_chunks = 0
                    else:
                        partial = json.loads(cmd_rec.PartialResult()).get("partial", "").strip()
                        if partial:
                            heard_speech = True
                            silence_chunks = 0
                        else:
                            if heard_speech:
                                silence_chunks += 1

                    command_chunk_limit -= 1

                    if (heard_speech and silence_chunks >= 4) or command_chunk_limit <= 0:
                        final_result = json.loads(cmd_rec.FinalResult())
                        final_text = final_result.get("text", "").strip()
                        if final_text:
                            command_text_parts.append(final_text)

                        prompt = " ".join(part for part in command_text_parts if part).strip()
                        print(f"[Command] {prompt}")

                        if prompt:
                            fetch_ai_response(prompt)
                        else:
                            post_ui_state("idle", "")

                        wake_rec = KaldiRecognizer(model, SAMPLE_RATE, WAKE_GRAMMAR)
                        state = "wake"
                        cmd_rec = None
                        heard_speech = False
                        silence_chunks = 0
                        command_text_parts = []
                        command_chunk_limit = 40

    except Exception as e:
        post_ui_state("error", f"Voice Error: {e}")

# =========================
# ROUNDED RECTANGLE HELPER
# =========================
def rounded_rect_points(x1, y1, x2, y2, r=30):
    return [
        x1+r, y1,  x2-r, y1,
        x2,   y1,  x2,   y1+r,
        x2,   y2-r, x2,  y2,
        x2-r, y2,  x1+r, y2,
        x1,   y2,  x1,   y2-r,
        x1,   y1+r, x1,  y1
    ]

# =========================
# DRAGGABLE CARD BASE
# =========================
class DraggableCard(tk.Canvas):
    _all_cards = []

    def __init__(self, parent, width, height, title, **kw):
        super().__init__(
            parent,
            width=width, height=height,
            bg=BG_COLOR, highlightthickness=0, bd=0,
            **kw
        )
        self.card_w = width
        self.card_h = height

        self._bg_id = self.create_polygon(
            rounded_rect_points(4, 4, width-4, height-4, r=28),
            smooth=True,
            splinesteps=36,
            fill=BOX_COLOR,
            outline="white",
            width=3
        )

        if title:
            self.create_text(
                20, 20, text=title,
                fill=DIM_COLOR, font=FONT_TITLE, anchor="nw"
            )

        self._drag_ox = 0
        self._drag_oy = 0
        self._mirror_place = None  # last place(x,y) for restore after hide
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

        DraggableCard._all_cards.append(self)

    def place(self, cnf={}, **kw):
        tk.Canvas.place(self, cnf, **kw)
        x = kw.get("x")
        y = kw.get("y")
        if x is None and isinstance(cnf, dict):
            x = cnf.get("x")
        if y is None and isinstance(cnf, dict):
            y = cnf.get("y")
        if x is not None and y is not None:
            try:
                self._mirror_place = (int(float(x)), int(float(y)))
            except (TypeError, ValueError):
                pass

    def mirror_set_visible(self, visible):
        """Hide with place_forget or show at last saved coordinates."""
        if visible:
            if self._mirror_place is not None:
                x, y = self._mirror_place
                self.place(x=x, y=y)
        else:
            try:
                if self.winfo_manager():
                    self._mirror_place = (self.winfo_x(), self.winfo_y())
            except tk.TclError:
                pass
            self.place_forget()

    def _on_press(self, e):
        self._drag_ox = e.x
        self._drag_oy = e.y
        self.tk.call("raise", self._w)
        self.itemconfigure(self._bg_id, outline="#00ff00")
        self.update_idletasks()

    def _on_drag(self, e):
        parent = self.master
        pw = parent.winfo_width()
        ph = parent.winfo_height()

        nx = self.winfo_x() + e.x - self._drag_ox
        ny = self.winfo_y() + e.y - self._drag_oy

        nx = max(WIDGET_PAD, min(pw - self.card_w - WIDGET_PAD, nx))
        ny = max(WIDGET_PAD, min(ph - self.card_h - WIDGET_PAD, ny))

        nx, ny = self._resolve_collisions(nx, ny)
        self.place(x=nx, y=ny)

    def _on_release(self, e):
        self.itemconfigure(self._bg_id, outline="white")
        try:
            if self.winfo_manager():
                self._mirror_place = (self.winfo_x(), self.winfo_y())
        except tk.TclError:
            pass
        self.update_idletasks()

    def _resolve_collisions(self, nx, ny):
        for other in DraggableCard._all_cards:
            if other is self:
                continue
            try:
                if not other.winfo_manager():
                    continue
            except tk.TclError:
                continue

            ox = other.winfo_x()
            oy = other.winfo_y()
            ow = other.card_w
            oh = other.card_h

            overlap_x = nx < ox + ow + WIDGET_PAD and nx + self.card_w + WIDGET_PAD > ox
            overlap_y = ny < oy + oh + WIDGET_PAD and ny + self.card_h + WIDGET_PAD > oy

            if overlap_x and overlap_y:
                push_left  = (nx + self.card_w + WIDGET_PAD) - ox
                push_right = (ox + ow + WIDGET_PAD) - nx
                push_up    = (ny + self.card_h + WIDGET_PAD) - oy
                push_down  = (oy + oh + WIDGET_PAD) - ny

                min_push = min(push_left, push_right, push_up, push_down)
                if min_push == push_left:
                    nx = ox - self.card_w - WIDGET_PAD
                elif min_push == push_right:
                    nx = ox + ow + WIDGET_PAD
                elif min_push == push_up:
                    ny = oy - self.card_h - WIDGET_PAD
                else:
                    ny = oy + oh + WIDGET_PAD

        parent = self.master
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        nx = max(WIDGET_PAD, min(pw - self.card_w - WIDGET_PAD, nx))
        ny = max(WIDGET_PAD, min(ph - self.card_h - WIDGET_PAD, ny))
        return nx, ny

# =========================
# DATE / TIME / WEATHER CARD
# =========================
class DateTimeWeatherCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=480, height=80, title="")
        self._line = self.create_text(
            240, 40, text="...",
            fill=FG_COLOR, font=FONT_BODY, anchor="center"
        )
        self.place(x=x, y=y)
        self._tick()

    def _tick(self):
        now = datetime.now()
        date_str = now.strftime("%a, %b %d")
        time_str = now.strftime("%I:%M:%S %p").lstrip("0")
        self.itemconfig(
            self._line,
            text=f"{date_str}   |   {time_str}   |   {_weather_cache}"
        )
        self.after(CLOCK_REFRESH_MS, self._tick)

    def refresh_weather(self):
        bg(fetch_weather)
        self.after(WEATHER_REFRESH_MS, self.refresh_weather)

# =========================
# NEWS CARD
# =========================
class NewsCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=480, height=190, title="News")
        self._idx = 0

        self._source_id = self.create_text(
            24, 48, text="",
            fill=DIM_COLOR, font=("Arial", 11), anchor="nw"
        )
        self._pub_id = self.create_text(
            24, 66, text="",
            fill=DIM_COLOR, font=("Arial", 11), anchor="nw"
        )
        self._headline_id = self.create_text(
            24, 90, text="Loading...",
            fill=FG_COLOR, font=("Arial", 14, "bold"),
            anchor="nw", width=440
        )

        self.place(x=x, y=y)
        self._cycle()
        self.refresh_news()

    def refresh_news(self):
        bg(fetch_news)
        self.after(NEWS_REFRESH_MS, self.refresh_news)

    def _cycle(self):
        if _news_cache:
            n = len(_news_cache)
            self._idx = self._idx % n
            item = _news_cache[self._idx]
            self.itemconfig(self._source_id,   text=item["source"])
            self.itemconfig(self._pub_id,      text=item["pub"])
            self.itemconfig(self._headline_id, text=item["title"])
            self._idx += 1
        self.after(NEWS_CYCLE_MS, self._cycle)

# =========================
# STOCKS CARD
# =========================
class StocksCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=360, height=155, title="Stocks")
        self._line_ids = []
        for i in range(len(STOCK_SYMBOLS)):
            tid = self.create_text(
                20, 48 + i * 34, text="Loading...",
                fill=FG_COLOR, font=FONT_COMPACT,
                anchor="nw", width=320
            )
            self._line_ids.append(tid)
        self.place(x=x, y=y)
        self._refresh()

    def _refresh(self):
        bg(fetch_stocks)
        self.after(500, self._apply)
        self.after(STOCK_REFRESH_MS, self._refresh)

    def apply_cache_to_canvas(self):
        """Push _stock_cache to line items (call from main thread)."""
        self._apply()

    def _apply(self):
        for i, tid in enumerate(self._line_ids):
            text = _stock_cache[i] if i < len(_stock_cache) else "N/A"
            color = FG_COLOR
            if "▲" in text:
                color = "#34c759"
            elif "▼" in text:
                color = "#ff453a"
            self.itemconfig(tid, text=text, fill=color)

        if any("Loading" in s for s in _stock_cache):
            self.after(2000, self._apply)

    def resync_lines(self):
        """Recreate line widgets when STOCK_SYMBOLS count changes (main thread)."""
        n = len(STOCK_SYMBOLS)
        while len(self._line_ids) < n:
            tid = self.create_text(
                20, 48 + len(self._line_ids) * 34,
                text="Loading...",
                fill=FG_COLOR, font=FONT_COMPACT,
                anchor="nw", width=320
            )
            self._line_ids.append(tid)
        while len(self._line_ids) > n:
            last = self._line_ids.pop()
            self.delete(last)
        for i, tid in enumerate(self._line_ids):
            self.coords(tid, 20, 48 + i * 34)

# =========================
# TODO LIST CARD (vertical, JSON-backed)
# =========================
class TodoCard(DraggableCard):
    def __init__(self, parent, x, y):
        h = min(
            72 + TODO_MAX_VISIBLE_LINES * TODO_LINE_HEIGHT + 36,
            monitors[1].height - 120,
        )
        super().__init__(parent, width=TODO_CARD_WIDTH, height=int(h), title="To-do")
        self._row_ids = []
        self.place(x=x, y=y)
        self.refresh_list()

    def refresh_list(self):
        for rid in self._row_ids:
            try:
                self.delete(rid)
            except tk.TclError:
                pass
        self._row_ids.clear()
        y0 = 48
        tasks = _todo_tasks[:TODO_MAX_VISIBLE_LINES]
        if not tasks:
            tid = self.create_text(
                24,
                y0,
                text="No tasks — ask the mirror to add one",
                fill=DIM_COLOR,
                font=FONT_COMPACT,
                anchor="nw",
                width=TODO_CARD_WIDTH - 40)
            self._row_ids.append(tid)
        else:
            for t in tasks:
                tid = self.create_text(
                    24,
                    y0,
                    text=f"• {t['text']}",
                    fill=FG_COLOR,
                    font=FONT_COMPACT,
                    anchor="nw",
                    width=TODO_CARD_WIDTH - 40
                )
                self._row_ids.append(tid)
                y0 += TODO_LINE_HEIGHT
            overflow = len(_todo_tasks) - TODO_MAX_VISIBLE_LINES
            if overflow > 0:
                tid = self.create_text(
                    24,
                    y0,
                    text=f"+ {overflow} more",
                    fill=DIM_COLOR,
                    font=("Arial", 11),
                    anchor="nw")
                self._row_ids.append(tid)

# =========================
# AI RESPONSE CARD
# =========================
class AIResponseCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=520, height=220, title="AI")

        self._text_id = self.create_text(
            260, 110,
            text="",
            fill=FG_COLOR,
            font=FONT_BODY,
            anchor="center",
            width=470,
            justify="center"
        )

        self.place(x=x, y=y)
        self._poll()

    def _poll(self):
        global _ai_state, _ai_text

        while not _ui_queue.empty():
            state, text = _ui_queue.get_nowait()
            set_ai_state(state, text)

        if _ai_state == "idle":
            self.coords(self._text_id, 260, 110)
            self.itemconfig(
                self._text_id,
                text="",
                anchor="center",
                justify="center"
            )

        elif _ai_state in ("listening", "thinking"):
            self.coords(self._text_id, 260, 110)
            self.itemconfig(
                self._text_id,
                text=_ai_text,
                anchor="center",
                justify="center"
            )

        elif _ai_state in ("response", "error"):
            self.coords(self._text_id, 20, 52)
            self.itemconfig(
                self._text_id,
                text=_ai_text,
                anchor="nw",
                justify="left"
            )

        self.after(150, self._poll)

# =========================
# MAIN WINDOW
# =========================
load_todos()

root = tk.Tk()
root.title("Smart Mirror Dashboard")
root.configure(bg=BG_COLOR)
#COMMENT OUT IF NO SECOND MONITOR
root.geometry(f"{monitors[1].width}x{monitors[1].height}+{monitors[1].x}+{monitors[1].y}")
root.attributes("-fullscreen", True)
root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))

canvas = tk.Frame(root, bg=BG_COLOR)
canvas.pack(fill="both", expand=True)

_m = monitors[1]
_todo_h = min(72 + TODO_MAX_VISIBLE_LINES * TODO_LINE_HEIGHT + 36, _m.height - 120)
_todo_y = max(WIDGET_PAD, (_m.height - int(_todo_h)) // 2)

dtw_card   = DateTimeWeatherCard(canvas, x=10,   y=10)
news_card  = NewsCard(canvas,            x=600, y=10)
stock_card = StocksCard(canvas,          x=10,   y=1680)
todo_card  = TodoCard(canvas,            x=WIDGET_PAD, y=_todo_y)
ai_card    = AIResponseCard(canvas,      x=550,  y=1700)

_root_ref = root
_stock_card_ref = stock_card
_todo_card_ref = todo_card
_widget_refs.update({
    "datetime": dtw_card,
    "news": news_card,
    "stocks": stock_card,
    "ai": ai_card,
    "todo": todo_card,
})

bg(fetch_weather)
dtw_card.refresh_weather()

threading.Thread(target=voice_loop, daemon=True).start()

root.mainloop()