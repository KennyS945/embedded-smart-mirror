import os
import json
import queue
import signal
import sys
import threading
import time
import uuid
import tkinter as tk
from datetime import datetime

import cv2
import mediapipe as mp
import requests
import sounddevice as sd
import yfinance as yf
from dotenv import load_dotenv
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from pynput.mouse import Button, Controller as MouseController
from vosk import Model, KaldiRecognizer

load_dotenv()


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
CLOCK_REFRESH_MS   = 1000

# Colours
BG_COLOR    = "black"
BOX_COLOR   = "#1c1c1e"
FG_COLOR    = "white"
DIM_COLOR   = "#888888"

# Fonts
FONT_TITLE   = ("Arial", 14, "bold")
FONT_BODY    = ("Arial", 13)
FONT_COMPACT = ("Arial", 12)

WIDGET_PAD = 10

# TODO
TODO_JSON_PATH        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mirror_todos.json")
TODO_LINE_HEIGHT      = 30
TODO_MAX_VISIBLE      = 14
TODO_CARD_WIDTH       = 340

# Voice  (Pi-friendly: smaller block size)
VOSK_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vosk-model-small-en-us-0.15")
SAMPLE_RATE     = 16000
BLOCK_SIZE      = 3200          # ~0.2 s – lower latency on ARM
WAKE_GRAMMAR    = json.dumps(["hey mirror", "[unk]"])

# Hand tracking  (Pi-friendly settings)
HAND_MODEL_PATH       = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hand_landmarker.task")
CAMERA_ID             = 0
FRAME_WIDTH           = 320     # lower res → less CPU
FRAME_HEIGHT          = 240
SMOOTHING_WINDOW      = 3       # reduced for faster response
HAND_SKIP_FRAMES      = 1       # process every Nth frame (1 = every frame)
ILY_HOLD_SECONDS      = 3.0
HAND_MAX_FPS          = 30.0    # increased to 30 FPS for better responsiveness

# Custom cursor settings
CURSOR_RADIUS         = 15      # pixels
CURSOR_OUTLINE_WIDTH  = 2       # pixels
CURSOR_COLOR          = "rgba(100, 200, 255, 0.5)"  # semi-transparent cyan

# ─────────────────────────────────────────────
# GLOBAL STATE
# ─────────────────────────────────────────────
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
_ily_label      = None
_ily_remaining  = 0.0

_widget_refs = {}
_widget_visibility = {
    "datetime": True, "news": True, "stocks": True, "ai": True, "todo": True,
}

# Hand tracking
_mouse           = MouseController()
_tracking_enabled = False
_running          = True
_position_buffer  = []
_detection_result = None

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
                    # DISABLE VOICE ACTIVATION IF HAND CONTROL IS ACTIVE
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

# ─────────────────────────────────────────────
# HAND TRACKING
# ─────────────────────────────────────────────
def _get_screen_size():
    try:
        import subprocess
        out = subprocess.check_output(
            "xrandr | grep '*' | awk '{print $1}'", shell=True
        ).decode().strip().split("\n")[0]
        w, h = out.split("x")
        return int(w), int(h)
    except Exception:
        return 1920, 1080

def _smooth(x, y):
    """Optimized smoothing with reduced buffer for lower latency"""
    _position_buffer.append((x, y))
    if len(_position_buffer) > SMOOTHING_WINDOW:
        _position_buffer.pop(0)
    
    # Use weighted moving average for faster response
    if len(_position_buffer) == 1:
        return x, y
    
    # More weight on recent positions
    weights = [i + 1 for i in range(len(_position_buffer))]
    total_weight = sum(weights)
    ax = int(sum(px * w for (px, _), w in zip(_position_buffer, weights)) / total_weight)
    ay = int(sum(py * w for (_, py), w in zip(_position_buffer, weights)) / total_weight)
    return ax, ay

def _set_ily_remaining(remaining):
    """Thread-safe-ish: hand thread writes, UI loop reads."""
    global _ily_remaining
    try:
        _ily_remaining = float(remaining)
    except (TypeError, ValueError):
        _ily_remaining = 0.0

def ui_overlay_loop():
    """Main-thread loop: renders countdown."""
    global _ily_label
    if _root_ref is None:
        return
    
    # Handle ILY countdown
    if _ily_remaining <= 0: 
        if _ily_label is not None: 
            _ily_label.destroy()
            _ily_label = None
    else:
        if _ily_label is None:
            _ily_label = tk.Label(
                _root_ref, text="", fg="white", bg="#1c1c1e",
                font=("Arial", 14, "bold"), padx=12, pady=8,
            )
            y = 10
            dtw = _widget_refs.get("datetime")
            if dtw is not None:
                try:
                    y = dtw.winfo_y() + dtw.card_h + 10
                except Exception:
                    y = 95
            _ily_label.place(x=10, y=y)
        
        action = "off" if _tracking_enabled else "on"
        _ily_label.config(text=f"Cursor {action} in {_ily_remaining:.1f}s")
    
    # Handle system cursor visibility
    try:
        if _tracking_enabled:
            # Hide system cursor when hand control is active
            _root_ref.config(cursor="none")
        else:
            # Show system cursor when hand control is off
            _root_ref.config(cursor="")
    except Exception:
        pass
    
    # ~30 FPS UI overlay updates
    _root_ref.after(33, ui_overlay_loop)

def hand_tracking_loop():
    global _tracking_enabled, _running

    if not os.path.exists(HAND_MODEL_PATH):
        print(f"[Hand] Model not found: {HAND_MODEL_PATH}"); return

    screen_w, screen_h = _get_screen_size()
    cap = cv2.VideoCapture(CAMERA_ID)
    if not cap.isOpened():
        print("[Hand] Unable to open webcam."); return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    # Pi: request MJPEG for lower USB bandwidth
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

    try:
        detector = vision.HandLandmarker.create_from_options(
            vision.HandLandmarkerOptions(
                base_options=python.BaseOptions(model_asset_path=HAND_MODEL_PATH),
                running_mode=vision.RunningMode.IMAGE,
                num_hands=1,
                min_hand_detection_confidence=0.5,   # slightly increased for accuracy
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
        )
    except Exception as e:
        print(f"[Hand] Failed to load model: {e}"); cap.release(); return

    was_fist    = False
    ily_start   = None
    frame_count = 0
    last_tick   = 0.0

    try:
        while _running and cap.isOpened():
            # Cap processing FPS (prevents pegging CPU on Pi)
            now = time.time()
            min_dt = 1.0 / max(HAND_MAX_FPS, 1.0)
            if last_tick and (now - last_tick) < min_dt:
                time.sleep(max(0.0, min_dt - (now - last_tick)))
            last_tick = time.time()

            # Cheap skip: grab (no decode) on skipped frames
            frame_count += 1
            if HAND_SKIP_FRAMES > 1 and (frame_count % HAND_SKIP_FRAMES) != 0:
                cap.grab()
                continue

            ok, frame = cap.read()
            if not ok:
                continue

            frame    = cv2.flip(frame, 1)
            rgb      = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_img   = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = detector.detect(mp_img)

            if not result or not result.hand_landmarks:
                if was_fist:
                    try: _mouse.release(Button.left)
                    except Exception: pass
                    was_fist = False
                ily_start = None
                continue

            lm = result.hand_landmarks[0]

            # ILY gesture: thumb + index + pinky out; middle + ring folded
            is_ily = (
                lm[4].x < lm[3].x       and   # thumb out (mirrored)
                lm[8].y  < lm[6].y       and   # index out
                lm[12].y > lm[10].y      and   # middle in
                lm[16].y > lm[14].y      and   # ring in
                lm[20].y < lm[18].y            # pinky out
            )

            if is_ily:
                if ily_start is None:
                    ily_start = time.time()
                elapsed   = time.time() - ily_start
                remaining = ILY_HOLD_SECONDS - elapsed
                if elapsed >= ILY_HOLD_SECONDS:
                    _tracking_enabled = not _tracking_enabled
                    ily_start = None
                    _set_ily_remaining(0)
                    print(f"[Hand] Tracking {'ON' if _tracking_enabled else 'OFF'}")
                    if not _tracking_enabled and was_fist:
                        try: 
                            _mouse.release(Button.left)
                        except Exception: 
                            pass
                        was_fist = False
                else:
                    _set_ily_remaining(remaining)
            else:
                ily_start = None
                _set_ily_remaining(0)

            if not _tracking_enabled:
                continue

            palm    = lm[9]
            sx, sy  = int(palm.x * screen_w), int(palm.y * screen_h)
            mx, my  = _smooth(sx, sy)
            try:
                _mouse.position = (mx, my)
            except Exception:
                pass

            tips    = [8, 12, 16, 20]
            knucks  = [6, 10, 14, 18]
            is_fist = all(lm[t].y > lm[k].y for t, k in zip(tips, knucks))
            try:
                if is_fist and not was_fist:
                    _mouse.press(Button.left)
                elif not is_fist and was_fist:
                    _mouse.release(Button.left)
            except Exception:
                pass
            was_fist = is_fist

    except Exception as e:
        print(f"[Hand] Crash: {e}")
    finally:
        try: _mouse.release(Button.left)
        except Exception: pass
        _set_ily_remaining(0)
        try: detector.close()
        except Exception: pass
        cap.release()

# ─────────────────────────────────────────────
# ROUNDED RECTANGLE HELPER
# ─────────────────────────────────────────────
def rounded_rect_points(x1, y1, x2, y2, r=28):
    return [
        x1+r, y1,   x2-r, y1,
        x2,   y1,   x2,   y1+r,
        x2,   y2-r, x2,   y2,
        x2-r, y2,   x1+r, y2,
        x1,   y2,   x1,   y2-r,
        x1,   y1+r, x1,   y1,
    ]

# ─────────────────────────────────────────────
# DRAGGABLE CARD BASE
# ─────────────────────────────────────────────
class DraggableCard(tk.Canvas):
    _all_cards = []

    def __init__(self, parent, width, height, title, **kw):
        super().__init__(parent, width=width, height=height,
                         bg=BG_COLOR, highlightthickness=0, bd=0, **kw)
        self.card_w = width
        self.card_h = height
        self._mirror_place = None

        self._bg_id = self.create_polygon(
            rounded_rect_points(4, 4, width-4, height-4),
            smooth=True, splinesteps=36, fill=BOX_COLOR, outline="white", width=3,
        )
        if title:
            self.create_text(20, 20, text=title, fill=DIM_COLOR, font=FONT_TITLE, anchor="nw")

        self._drag_ox = self._drag_oy = 0
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        DraggableCard._all_cards.append(self)

    def place(self, cnf={}, **kw):
        tk.Canvas.place(self, cnf, **kw)
        x = kw.get("x") or (cnf.get("x") if isinstance(cnf, dict) else None)
        y = kw.get("y") or (cnf.get("y") if isinstance(cnf, dict) else None)
        if x is not None and y is not None:
            try:
                self._mirror_place = (int(float(x)), int(float(y)))
            except (TypeError, ValueError):
                pass

    def mirror_set_visible(self, visible):
        if visible:
            if self._mirror_place:
                self.place(x=self._mirror_place[0], y=self._mirror_place[1])
        else:
            try:
                if self.winfo_manager():
                    self._mirror_place = (self.winfo_x(), self.winfo_y())
            except tk.TclError:
                pass
            self.place_forget()

    def _on_press(self, e):
        self._drag_ox, self._drag_oy = e.x, e.y
        self.tk.call("raise", self._w)
        self.itemconfigure(self._bg_id, outline="#00ff00")

    def _on_drag(self, e):
        pw, ph = self.master.winfo_width(), self.master.winfo_height()
        nx = max(WIDGET_PAD, min(pw - self.card_w - WIDGET_PAD, self.winfo_x() + e.x - self._drag_ox))
        ny = max(WIDGET_PAD, min(ph - self.card_h - WIDGET_PAD, self.winfo_y() + e.y - self._drag_oy))
        nx, ny = self._resolve_collisions(nx, ny)
        self.place(x=nx, y=ny)

    def _on_release(self, e):
        self.itemconfigure(self._bg_id, outline="white")
        try:
            if self.winfo_manager():
                self._mirror_place = (self.winfo_x(), self.winfo_y())
        except tk.TclError:
            pass

    def _resolve_collisions(self, nx, ny):
        for other in DraggableCard._all_cards:
            if other is self:
                continue
            try:
                if not other.winfo_manager():
                    continue
            except tk.TclError:
                continue
            ox, oy, ow, oh = other.winfo_x(), other.winfo_y(), other.card_w, other.card_h
            if (nx < ox+ow+WIDGET_PAD and nx+self.card_w+WIDGET_PAD > ox and
                    ny < oy+oh+WIDGET_PAD and ny+self.card_h+WIDGET_PAD > oy):
                pl = (nx+self.card_w+WIDGET_PAD) - ox
                pr = (ox+ow+WIDGET_PAD) - nx
                pu = (ny+self.card_h+WIDGET_PAD) - oy
                pd = (oy+oh+WIDGET_PAD) - ny
                m  = min(pl, pr, pu, pd)
                if m == pl: nx = ox - self.card_w - WIDGET_PAD
                elif m == pr: nx = ox + ow + WIDGET_PAD
                elif m == pu: ny = oy - self.card_h - WIDGET_PAD
                else:         ny = oy + oh + WIDGET_PAD
        pw, ph = self.master.winfo_width(), self.master.winfo_height()
        return (max(WIDGET_PAD, min(pw-self.card_w-WIDGET_PAD, nx)),
                max(WIDGET_PAD, min(ph-self.card_h-WIDGET_PAD, ny)))

# ─────────────────────────────────────────────
# WIDGETS
# ─────────────────────────────────────────────
class DateTimeWeatherCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=480, height=80, title="")
        self._line = self.create_text(240, 40, text="...", fill=FG_COLOR,
                                      font=FONT_BODY, anchor="center")
        self.place(x=x, y=y)
        self._tick()
        self._sched_weather()

    def _tick(self):
        now = datetime.now()
        self.itemconfig(self._line, text=(
            f"{now.strftime('%a, %b %d')}   |   "
            f"{now.strftime('%I:%M:%S %p').lstrip('0')}   |   {_weather_cache}"
        ))
        self.after(CLOCK_REFRESH_MS, self._tick)

    def _sched_weather(self):
        bg(fetch_weather)
        self.after(WEATHER_REFRESH_MS, self._sched_weather)


class NewsCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=480, height=190, title="News")
        self._idx = 0
        self._src_id = self.create_text(24, 48,  text="", fill=DIM_COLOR, font=("Arial",11), anchor="nw")
        self._pub_id = self.create_text(24, 66,  text="", fill=DIM_COLOR, font=("Arial",11), anchor="nw")
        self._hdl_id = self.create_text(24, 90,  text="Loading...", fill=FG_COLOR,
                                        font=("Arial",14,"bold"), anchor="nw", width=440)
        self.place(x=x, y=y)
        self._cycle()
        self._sched_news()

    def _sched_news(self):
        bg(fetch_news)
        self.after(NEWS_REFRESH_MS, self._sched_news)

    def _cycle(self):
        if _news_cache:
            self._idx %= len(_news_cache)
            item = _news_cache[self._idx]
            self.itemconfig(self._src_id, text=item["source"])
            self.itemconfig(self._pub_id, text=item["pub"])
            self.itemconfig(self._hdl_id, text=item["title"])
            self._idx += 1
        self.after(NEWS_CYCLE_MS, self._cycle)


class StocksCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=360, height=155, title="Stocks")
        self._line_ids = []
        for i in range(len(STOCK_SYMBOLS)):
            tid = self.create_text(20, 48 + i*34, text="Loading...",
                                   fill=FG_COLOR, font=FONT_COMPACT, anchor="nw", width=320)
            self._line_ids.append(tid)
        self.place(x=x, y=y)
        self._sched_stocks()

    def _sched_stocks(self):
        bg(fetch_stocks)
        self.after(500, self._apply)
        self.after(STOCK_REFRESH_MS, self._sched_stocks)

    def apply_cache_to_canvas(self):
        self._apply()

    def _apply(self):
        for i, tid in enumerate(self._line_ids):
            txt = _stock_cache[i] if i < len(_stock_cache) else "N/A"
            color = "#34c759" if "▲" in txt else ("#ff453a" if "▼" in txt else FG_COLOR)
            self.itemconfig(tid, text=txt, fill=color)
        if any("Loading" in s for s in _stock_cache):
            self.after(2000, self._apply)

    def resync_lines(self):
        n = len(STOCK_SYMBOLS)
        while len(self._line_ids) < n:
            tid = self.create_text(20, 48 + len(self._line_ids)*34, text="Loading...",
                                   fill=FG_COLOR, font=FONT_COMPACT, anchor="nw", width=320)
            self._line_ids.append(tid)
        while len(self._line_ids) > n:
            self.delete(self._line_ids.pop())
        for i, tid in enumerate(self._line_ids):
            self.coords(tid, 20, 48 + i*34)


class TodoCard(DraggableCard):
    def __init__(self, parent, x, y, max_h):
        h = min(72 + TODO_MAX_VISIBLE * TODO_LINE_HEIGHT + 36, max_h - 120)
        super().__init__(parent, width=TODO_CARD_WIDTH, height=int(h), title="To-do")
        self._row_ids = []
        self.place(x=x, y=y)
        self.refresh_list()

    def refresh_list(self):
        for rid in self._row_ids:
            try: self.delete(rid)
            except tk.TclError: pass
        self._row_ids.clear()
        y0    = 48
        tasks = _todo_tasks[:TODO_MAX_VISIBLE]
        if not tasks:
            self._row_ids.append(self.create_text(
                24, y0, text="No tasks – ask the mirror to add one",
                fill=DIM_COLOR, font=FONT_COMPACT, anchor="nw", width=TODO_CARD_WIDTH-40))
        else:
            for t in tasks:
                self._row_ids.append(self.create_text(
                    24, y0, text=f"• {t['text']}",
                    fill=FG_COLOR, font=FONT_COMPACT, anchor="nw", width=TODO_CARD_WIDTH-40))
                y0 += TODO_LINE_HEIGHT
            ov = len(_todo_tasks) - TODO_MAX_VISIBLE
            if ov > 0:
                self._row_ids.append(self.create_text(
                    24, y0, text=f"+ {ov} more",
                    fill=DIM_COLOR, font=("Arial",11), anchor="nw"))


class AIResponseCard(DraggableCard):
    def __init__(self, parent, x, y):
        super().__init__(parent, width=520, height=220, title="AI")
        self._text_id = self.create_text(260, 110, text="", fill=FG_COLOR,
                                         font=FONT_BODY, anchor="center", width=470, justify="center")
        self.place(x=x, y=y)
        self._poll()

    def _poll(self):
        global _ai_state, _ai_text
        while not _ui_queue.empty():
            state, text = _ui_queue.get_nowait()
            set_ai_state(state, text)
        if _ai_state == "idle":
            self.coords(self._text_id, 260, 110)
            self.itemconfig(self._text_id, text="", anchor="center", justify="center")
        elif _ai_state in ("listening", "thinking"):
            self.coords(self._text_id, 260, 110)
            self.itemconfig(self._text_id, text=_ai_text, anchor="center", justify="center")
        else:  # response / error
            self.coords(self._text_id, 20, 52)
            self.itemconfig(self._text_id, text=_ai_text, anchor="nw", justify="left")
        self.after(150, self._poll)

# ─────────────────────────────────────────────
# EXIT
# ─────────────────────────────────────────────
def close_app(event=None):
    global _running
    _running = False
    if _root_ref:
        try: _root_ref.quit(); _root_ref.destroy()
        except Exception: pass

def _handle_signal(sig, frame):
    close_app(); sys.exit(0)

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    global _root_ref, _stock_card_ref, _todo_card_ref

    load_todos()

    root = tk.Tk()
    root.title("Smart Mirror")
    root.configure(bg=BG_COLOR)

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.attributes("-fullscreen", True)
    root.bind("<Escape>", close_app)
    root.bind("q",        close_app)
    root.protocol("WM_DELETE_WINDOW", close_app)
    signal.signal(signal.SIGINT, _handle_signal)

    _root_ref = root

    canvas = tk.Frame(root, bg=BG_COLOR)
    canvas.pack(fill="both", expand=True)

    # Layout – sensible defaults for a 1920×1080 or similar Pi display
    todo_h = min(72 + TODO_MAX_VISIBLE * TODO_LINE_HEIGHT + 36, sh - 120)
    todo_y = max(WIDGET_PAD, (sh - int(todo_h)) // 2)

    dtw_card   = DateTimeWeatherCard(canvas, x=10,  y=10)
    news_card  = NewsCard(canvas,            x=510, y=10)
    stock_card = StocksCard(canvas,          x=10,  y=sh - 175)
    todo_card  = TodoCard(canvas,            x=WIDGET_PAD, y=todo_y, max_h=sh)
    ai_card    = AIResponseCard(canvas,      x=sw - 540,   y=sh - 240)

    _stock_card_ref = stock_card
    _todo_card_ref  = todo_card
    _widget_refs.update({
        "datetime": dtw_card, "news": news_card,
        "stocks": stock_card, "ai": ai_card, "todo": todo_card,
    })

    # Start UI overlay loop (cursor + countdown)
    root.after(33, ui_overlay_loop)

    # Initial data fetch
    bg(fetch_weather)
    bg(fetch_news)

    # Background threads
    threading.Thread(target=voice_loop,         daemon=True).start()
    threading.Thread(target=hand_tracking_loop, daemon=True).start()

    root.mainloop()


if __name__ == "__main__":
    main()
