#!/usr/bin/env python3
"""AI Home: one control panel for everything in this folder.

    python home\\home.py            (or double-click "Start AI Home.bat")

It opens a page at http://localhost:3010 where you can:
  * see what is installed and running, and open each part
  * install, start, stop and uninstall every part with one click
  * download, check and delete models
  * schedule jobs: a question for a model, the news desk, or any command

It runs on Windows itself (not in Docker) because it drives winget, Docker and Ollama for you.
The page only answers this PC: it listens on 127.0.0.1 and every request must carry a secret
that only the page it served knows, so another website open in your browser can't press its
buttons.

Uses only Python's standard library, so there is nothing to install.
"""
import argparse
import datetime as dt
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(HERE))
import fit  # noqa: E402  (the model-fit checker, reused for the Models tab)
import comfy  # noqa: E402
import gateway  # noqa: E402
import providers  # noqa: E402
import studio  # noqa: E402

PORT = 3010
TASK_NAME = "AI Home"
OLLAMA = "http://127.0.0.1:11434"
MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
         ".mp4": "video/mp4", ".webm": "video/webm", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac",
         ".ogg": "audio/ogg", ".stl": "model/stl", ".scad": "text/plain"}
MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,199}$")

# Everything the panel can manage. "required" parts are the basics; the rest are optional.
#   kind "winget"  = a normal Windows program, installed by Windows' own installer
#   kind "compose" = a web page that runs inside Docker (defined in compose.yaml)
COMPONENTS = [
    {"id": "ollama", "name": "Ollama", "group": "required", "kind": "winget",
     "winget": "Ollama.Ollama", "health": OLLAMA,
     "what": "Runs the AI models on your graphics card. Everything else talks to it.",
     "start_hint": "Open Ollama from the Start menu."},
    {"id": "docker", "name": "Docker Desktop", "group": "required", "kind": "winget",
     "winget": "Docker.DockerDesktop", "docker": True,
     "what": "Runs the chat page, voice engine and app builder in sealed boxes.",
     "start_hint": "Open Docker Desktop from the Start menu and wait for \"Engine running\". "
                   "Restart the PC first if you only just installed it."},
    {"id": "chat", "name": "Chat home page", "group": "required", "kind": "compose",
     "service": "open-webui", "image": "ghcr.io/open-webui/open-webui:main",
     "volume": "localai_open-webui", "open": "http://localhost:3000", "needs": ["docker", "ollama"],
     "what": "Open WebUI: chat with your models from the PC or your iPhone.",
     "data": "your chats, accounts and settings"},
    {"id": "voice", "name": "Voice engine", "group": "optional", "kind": "compose",
     "service": "kokoro", "image": "ghcr.io/remsky/kokoro-fastapi-cpu:latest",
     "health": "http://127.0.0.1:8880/health", "needs": ["docker"],
     "what": "Kokoro: reads chat answers aloud and makes audiobooks."},
    {"id": "builder", "name": "App builder", "group": "optional", "kind": "compose",
     "service": "agent-canvas", "image": "ghcr.io/openhands/agent-canvas:latest",
     "volume": "localai_openhands-data", "open": "http://localhost:3001/canvas",
     "needs": ["docker", "ollama"],
     "what": "OpenHands Agent Canvas: builds an app from one sentence.",
     "data": "the app builder's settings and conversations (apps it built stay in the apps folder)"},
    {"id": "comfyui", "name": "ComfyUI", "group": "optional", "kind": "winget",
     "winget": "Comfy.ComfyUI-Desktop",
     "what": "Makes images and video. Opens in its own window.",
     "start_hint": "Open ComfyUI from the Start menu."},
    {"id": "tailscale", "name": "Tailscale", "group": "optional", "kind": "winget",
     "winget": "Tailscale.Tailscale",
     "what": "Private link to your iPhone. See the iPhone guide for the two commands to run.",
     "start_hint": "Open Tailscale from the Start menu and sign in."},
    {"id": "git", "name": "Git", "group": "optional", "kind": "winget", "winget": "Git.Git",
     "what": "Downloads updates to this folder. The app builder also uses it."},
    {"id": "openscad", "name": "OpenSCAD", "group": "optional", "kind": "winget", "winget": "OpenSCAD.OpenSCAD",
     "what": "Turns the designs a model writes into 3D-printable files. Needed for Create > 3D models."},
    {"id": "nodejs", "name": "Node.js", "group": "optional", "kind": "winget", "winget": "OpenJS.NodeJS.LTS",
     "what": "Runs most plugins, including REA. Install it before adding plugins that start with \"npx\"."},
    {"id": "uv", "name": "uv", "group": "optional", "kind": "winget", "winget": "astral-sh.uv",
     "what": "Runs plugins that start with \"uvx\"."},
]
BY_ID = {c["id"]: c for c in COMPONENTS}
STARTER_MODELS = [
    {"name": "gpt-oss:20b", "why": "Main model: chat and the app builder", "group": "required"},
    {"name": "gemma4:12b", "why": "Smaller and quicker: everyday chat and the news desk", "group": "optional"},
    {"name": "qwen3-embedding:0.6b", "why": "Tiny helper the news desk needs to group headlines", "group": "optional"},
]
GUIDES = [("01-concepts.md", "The five ideas you need"), ("02-install.md", "Install"),
          ("03-models.md", "Choosing models"), ("04-app-builder.md", "The app builder"),
          ("05-images-video.md", "Images and video"), ("06-voices-audiobooks.md", "Voices and audiobooks"),
          ("07-iphone.md", "Using it from your iPhone"), ("08-news-desk.md", "The news desk"),
          ("09-troubleshooting.md", "Troubleshooting"), ("10-control-panel.md", "This control panel"),
          ("11-create.md", "Create: images, photos, video, 3D, music"), ("12-plugins-and-cloud.md", "Plugins and cloud models")]


# ================================================================== talking to the PC

class System:
    """Every command the panel runs goes through here, so tests can swap in a pretend PC."""
    hidden = {"creationflags": 0x08000000} if os.name == "nt" else {}  # no flashing black windows

    def run(self, args, timeout=120, cwd=None):
        try:
            p = subprocess.run(args, capture_output=True, text=True, errors="replace",
                               timeout=timeout, cwd=cwd, stdin=subprocess.DEVNULL, **self.hidden)
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except FileNotFoundError:
            return 127, f"{args[0]} is not installed (or not on the PATH yet; a restart fixes that)."
        except subprocess.TimeoutExpired:
            return 124, f"{args[0]} did not answer within {timeout} seconds."

    def stream(self, args, on_line, cwd=None, shell=False, timeout=7200):
        """Run a long command, handing each line of its output to on_line as it appears."""
        try:
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 errors="replace", cwd=cwd, shell=shell, stdin=subprocess.DEVNULL,
                                 **self.hidden)
        except FileNotFoundError:
            on_line(f"{args[0]} is not installed (or not on the PATH yet; a restart fixes that).")
            return 127
        killer = threading.Timer(timeout, p.kill)
        killer.start()
        try:
            for line in p.stdout:
                line = line.strip()
                if line and not re.fullmatch(r"[\s\-\\|/█▒░.]*\d*%?", line):  # skip progress spinners
                    on_line(line)
            return p.wait()
        finally:
            killer.cancel()

    def http_ok(self, url, timeout=3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout):
                return True
        except urllib.error.HTTPError:
            return True  # it answered, even if with an error page: something is running there
        except Exception:
            return False


def api(base, path, body=None, method=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw.strip() else {}


# ================================================================== schedules

DAYS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
UNITS = {"m": 1, "min": 1, "mins": 1, "minute": 1, "minutes": 1, "h": 60, "hr": 60, "hrs": 60,
         "hour": 60, "hours": 60, "d": 1440, "day": 1440, "days": 1440}
EXAMPLES = ('Try: "every 2h", "every 30m", "daily at 9am", "weekdays at 6:30", '
            '"mon,wed,fri at 8pm", "in 45m", "once 2026-12-01 14:00", or a cron line like "0 5 * * *".')


def clock(text):
    """'9am' -> (9, 0); '6:30' -> (6, 30); '8:15pm' -> (20, 15)."""
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text.strip())
    if not m:
        raise ValueError(f'"{text}" is not a time. Write it like 9am, 6:30 or 20:15.')
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap and not 1 <= h <= 12:
        raise ValueError(f'"{text}" is not a time. With am or pm the hour is 1 to 12.')
    if ap:
        h = h % 12 + (12 if ap == "pm" else 0)
    if h > 23 or mi > 59:
        raise ValueError(f'"{text}" is not a time. Hours go to 23 and minutes to 59.')
    return h, mi


def cron_field(text, lo, hi, names=None):
    out = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
            if step < 1:
                raise ValueError
        if part == "*":
            a, b = lo, hi
        else:
            ends = [(names or {}).get(x.lower()[:3], x) for x in part.split("-", 1)]
            a = int(ends[0])
            b = int(ends[1]) if len(ends) == 2 else (hi if step > 1 else a)
        if not (lo <= a <= hi and lo <= b <= hi and a <= b):
            raise ValueError
        out.update(range(a, b + 1, step))
    return out


def cron_sets(expr):
    f = expr.split()
    if len(f) != 5:
        raise ValueError("A cron line has five parts: minute hour day-of-month month day-of-week.")
    try:
        dow = {d % 7 for d in cron_field(f[4], 0, 7, DAYS)}  # 7 is another way to write Sunday
        return (cron_field(f[0], 0, 59), cron_field(f[1], 0, 23), cron_field(f[2], 1, 31),
                cron_field(f[3], 1, 12), dow, f[2] != "*", f[4] != "*")
    except ValueError:
        raise ValueError(f'"{expr}" is not a valid cron line. ' + EXAMPLES) from None


def parse_schedule(text, now):
    """Turn a phrase like "every 2h" or "weekdays at 6:30" into a stored schedule."""
    t = re.sub(r"\s+", " ", text.strip().lower())
    if not t:
        raise ValueError("Say when it should run. " + EXAMPLES)
    t = re.sub(r"^every (minute|hour|day)$", r"every 1 \1", t).replace("hourly", "every 1 hour")
    m = re.fullmatch(r"(every|in) (\d+) ?([a-z]+)", t)
    if m and m.group(3) in UNITS:
        minutes = int(m.group(2)) * UNITS[m.group(3)]
        if minutes < 1:
            raise ValueError("The gap must be at least one minute.")
        if m.group(1) == "in":
            return {"kind": "once", "at": (now + dt.timedelta(minutes=minutes)).isoformat(timespec="minutes")}
        return {"kind": "interval", "minutes": minutes, "anchor": now.isoformat(timespec="minutes")}
    m = re.fullmatch(r"(?:once |on |at )?(\d{4}-\d{2}-\d{2})[ t](\d{1,2}:\d{2})", t)
    if m:
        try:
            at = dt.datetime.fromisoformat(f"{m.group(1)}T{m.group(2).zfill(5)}")
        except ValueError:
            raise ValueError(f'"{text}" is not a real date and time.') from None
        if at <= now:
            raise ValueError("That time has already passed.")
        return {"kind": "once", "at": at.isoformat(timespec="minutes")}
    m = re.fullmatch(r"(.+?) at (.+)", t)
    if m:
        who, (h, mi) = m.group(1).replace("every ", "").strip(), clock(m.group(2))
        if who in ("day", "daily"):
            dow = "*"
        elif who in ("weekday", "weekdays"):
            dow = "1-5"
        elif who in ("weekend", "weekends"):
            dow = "0,6"
        else:
            names = [d.strip().rstrip("s")[:3] for d in re.split(r"[ ,]+|and", who) if d.strip()]
            if not names or any(n not in DAYS for n in names):
                raise ValueError(f'I don\'t understand "{m.group(1)}". ' + EXAMPLES)
            dow = ",".join(str(DAYS[n]) for n in names)
        return {"kind": "cron", "expr": f"{mi} {h} * * {dow}"}
    if len(t.split()) == 5 and re.fullmatch(r"[\d*/,\-a-z ]+", t):
        cron_sets(t)
        return {"kind": "cron", "expr": t}
    raise ValueError(f'I don\'t understand "{text}". ' + EXAMPLES)


def next_run(spec, after):
    """The first time strictly after `after` that this schedule should run, or None if never."""
    if spec["kind"] == "once":
        at = dt.datetime.fromisoformat(spec["at"])
        return at if at > after else None
    if spec["kind"] == "interval":
        anchor, gap = dt.datetime.fromisoformat(spec["anchor"]), dt.timedelta(minutes=spec["minutes"])
        if after < anchor:
            return anchor + gap
        return anchor + gap * (int((after - anchor) / gap) + 1)
    minutes, hours, doms, months, dows, dom_set, dow_set = cron_sets(spec["expr"])
    start = after.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    for offset in range(366 * 5):  # far enough to reach a Feb 29
        day = (start + dt.timedelta(days=offset)).date()
        dom_ok, dow_ok = day.day in doms, (day.isoweekday() % 7) in dows
        # Cron's rule: if both day-of-month and day-of-week are given, either one matching is enough.
        if day.month not in months or not ((dom_ok or dow_ok) if dom_set and dow_set else (dom_ok and dow_ok)):
            continue
        for h in sorted(hours):
            for mi in sorted(minutes):
                t = dt.datetime.combine(day, dt.time(h, mi))
                if t >= start:
                    return t
    return None


def describe(spec):
    if spec["kind"] == "once":
        return "Once, " + dt.datetime.fromisoformat(spec["at"]).strftime("%a %b %d at %H:%M")
    if spec["kind"] == "interval":
        n = spec["minutes"]
        for size, word in ((1440, "day"), (60, "hour"), (1, "minute")):
            if n % size == 0:
                k = n // size
                return f"Every {word}" if k == 1 else f"Every {k} {word}s"
    return "Cron: " + spec["expr"]


# ================================================================== the app

class Job:
    def __init__(self, n, title):
        self.id, self.title, self.status, self.lines = n, title, "waiting", []
        self.started = dt.datetime.now().isoformat(timespec="seconds")

    def log(self, line):
        self.lines.append(str(line))
        del self.lines[:-400]

    def view(self):
        return {"id": self.id, "title": self.title, "status": self.status, "started": self.started,
                "lines": self.lines[-400:]}


class App:
    def __init__(self, system=None, root=ROOT, data=None, ollama=OLLAMA, now=dt.datetime.now):
        self.sys, self.root, self.ollama, self.now = system or System(), Path(root), ollama, now
        self.data = Path(data) if data else HERE / "data"
        (self.data / "outputs").mkdir(parents=True, exist_ok=True)
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.RLock()
        self.jobs, self.job_count = [], 0
        self.queues = {"manage": queue.Queue(), "tasks": queue.Queue()}
        self.status, self.winget_cache, self.gpu, self.autostart = {}, {}, None, False
        self.schedules = self.load()
        self.busy_tasks = set()
        self.keys = providers.Keys(self.data / "keys.json")
        self.providers = providers.Providers(self.keys, self.ollama)
        self.studio = studio.Studio(self.root, self.data, self.providers, self.sys)
        self.hub = gateway.Hub(self.data, builtins=self.studio.tools())
        self.slow, self.hub_port = {}, gateway.HUB_PORT

    # ---------------------------------------------------------------- jobs
    # Two lines of work: "manage" (installs, downloads) and "tasks" (scheduled jobs). Each line
    # does one thing at a time, so two scheduled jobs never fight over the graphics card.

    def submit(self, line, title, work):
        with self.lock:
            self.job_count += 1
            job = Job(self.job_count, title)
            self.jobs.append(job)
            del self.jobs[:-40]
        self.queues[line].put((job, work))
        return job

    def worker(self, line):
        while True:
            job, work = self.queues[line].get()
            self.run_job(job, work, recheck=line == "manage")

    def run_job(self, job, work, recheck=True):
        job.status = "running"
        try:
            ok = work(job)
            job.status = "failed" if ok is False else "done"
        except Exception as e:
            job.log(f"Stopped with an error: {e}")
            job.status = "failed"
        if recheck:  # an install or uninstall just finished: look again at what is on the PC
            self.refresh(force_winget=True)

    def drain(self):  # for tests: run everything that is waiting, right now
        for q in self.queues.values():
            while not q.empty():
                self.run_job(*q.get())

    # ---------------------------------------------------------------- what is installed and running

    def docker_up(self):
        return self.sys.run(["docker", "info"], timeout=20)[0] == 0

    def compose_state(self):
        code, out = self.sys.run(["docker", "compose", "ps", "-a", "--format", "json"],
                                 timeout=30, cwd=self.root)
        rows = []
        if code == 0:
            for chunk in ([out] if out.lstrip().startswith("[") else out.splitlines()):
                try:
                    got = json.loads(chunk)
                    rows += got if isinstance(got, list) else [got]
                except ValueError:
                    pass
        return {r.get("Service"): r.get("State") for r in rows if isinstance(r, dict)}

    def winget_installed(self, pkg, force=False):
        if force or pkg not in self.winget_cache:
            code, out = self.sys.run(["winget", "list", "--exact", "--id", pkg,
                                      "--accept-source-agreements"], timeout=60)
            self.winget_cache[pkg] = code == 0 and pkg.lower() in out.lower()
        return self.winget_cache[pkg]

    def refresh(self, force_winget=False):
        docker = self.docker_up()
        services = self.compose_state() if docker else {}
        out = {}
        for c in COMPONENTS:
            if c["kind"] == "winget":
                installed = self.winget_installed(c["winget"], force_winget)
                if c.get("docker"):
                    running = docker
                elif c.get("health"):
                    running = self.sys.http_ok(c["health"])
                else:
                    running = None  # an ordinary program: the panel can't see if its window is open
                installed = installed or bool(running)
            else:
                state = services.get(c["service"])
                installed, running = state is not None, state == "running"
            out[c["id"]] = {"installed": installed, "running": running}
        if self.gpu is None:
            code, text = self.sys.run(["nvidia-smi", "--query-gpu=name,memory.total",
                                       "--format=csv,noheader,nounits"], timeout=15)
            m = re.match(r"\s*(.+?),\s*(\d+)", text) if code == 0 else None
            self.gpu = {"name": m.group(1), "vram_gb": round(int(m.group(2)) / 1024)} if m else {}
        self.autostart = self.sys.run(["schtasks", "/Query", "/TN", TASK_NAME], timeout=20)[0] == 0
        self.status = out
        return out

    def models(self):
        try:
            have = api(self.ollama, "/api/tags", timeout=5).get("models", [])
            loaded = {m["name"] for m in api(self.ollama, "/api/ps", timeout=5).get("models", [])}
        except Exception:
            return None  # Ollama isn't answering
        return [{"name": m["name"], "gb": round(m.get("size", 0) / 1e9, 1), "loaded": m["name"] in loaded}
                for m in sorted(have, key=lambda m: m["name"])]

    def state(self):
        models = self.models()
        names = {m["name"] for m in models or []} | {m["name"].removesuffix(":latest") for m in models or []}
        drafts = sorted((self.root / "newsdesk" / "drafts").glob("*/review.html"))
        with self.lock:
            return {
                "components": [{**{k: c.get(k) for k in ("id", "name", "group", "kind", "what", "open",
                                                           "start_hint", "needs", "data")},
                                **self.status.get(c["id"], {"installed": False, "running": False})}
                               for c in COMPONENTS],
                "models": models,
                "starters": [{**s, "have": s["name"] in names} for s in STARTER_MODELS],
                "gpu": self.gpu or {},
                "jobs": [j.view() for j in reversed(self.jobs)],
                "schedules": [self.schedule_view(s) for s in self.schedules],
                "guides": [{"file": f, "title": t} for f, t in GUIDES],
                "drafts": drafts[-1].parent.name if drafts else None,
                "autostart": self.autostart,
                **self.extra_state(),
            }

    def cached(self, name, seconds, work, default):
        """Remember a slow answer for a while, so the page's 3-second refresh stays quick."""
        at, value = self.slow.get(name, (0, default))
        if time.time() - at > seconds:
            try:
                value = work()
            except Exception:
                value = default
            self.slow[name] = (time.time(), value)
        return value

    def cloud_models(self):
        try:
            return json.loads((self.data / "cloud_models.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def recent(self, kind, count=8):
        files = [f for f in (self.root / "outputs" / kind).glob("*") if f.is_file() and f.suffix.lower() in MEDIA]
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        return [f.name for f in files[:count]]

    def recent_3d(self, count=6):
        folders = sorted((d for d in (self.root / "outputs" / "3d").glob("*") if (d / "model.stl").exists()),
                         key=lambda d: d.stat().st_mtime, reverse=True)
        return [{"name": d.name, "preview": (d / "preview.png").exists()} for d in folders[:count]]

    def extra_state(self):
        settings = self.studio.settings()
        claude = self.cached("claude", 600, self.providers.claude_models, [])
        return {
            "keys": self.keys.view(),
            "cloud": ["claude:" + m for m in claude] + self.cloud_models(),
            "settings": settings,
            "vision": self.cached("vision", 120, self.providers.vision_models, []),
            "comfy_up": self.cached("comfy", 10, self.studio.comfy().alive, False),
            "workflows": self.studio.workflows_view(),
            "loras": comfy.list_loras(settings["models_dir"]) if settings["models_dir"] else None,
            "characters": self.studio.characters(),
            "recent": {k: self.recent(k) for k in ("images", "edits", "video", "music")},
            "recent3d": self.recent_3d(),
            "plugins": self.hub.view(),
            "catalog": gateway.CATALOG,
            "hub": {"url": f"http://host.docker.internal:{self.hub_port}/mcp", "local": f"http://localhost:{self.hub_port}/mcp",
                    "token": self.hub.token, "tools": [{"name": t["name"], "what": t["description"]} for t in self.studio.tools()]},
        }

    # ---------------------------------------------------------------- keys, creating, plugins

    def set_key(self, name, value):
        self.keys.set(name, value)
        self.slow.pop("claude", None)
        if name == "anthropic" and value.strip():
            try:
                import anthropic  # noqa: F401
            except ImportError:
                return self.submit("manage", "Install the Claude library", lambda job: self.sys.stream(
                    [sys.executable, "-m", "pip", "install", "anthropic"], job.log) == 0)
        return None

    def set_cloud_model(self, action, spec):
        spec = str(spec).strip()
        if not re.fullmatch(r"(claude|openrouter):[A-Za-z0-9][A-Za-z0-9._/:\-]{0,150}", spec):
            raise ValueError("That isn't a cloud model name.")
        models = [m for m in self.cloud_models() if m != spec] + ([spec] if action == "add" else [])
        (self.data / "cloud_models.json").write_text(json.dumps(models), encoding="utf-8")

    def test_model(self, spec):
        if not MODEL_NAME.fullmatch(spec or ""):
            raise ValueError("Pick a model to test.")

        def work(job):
            job.log(f"Asking {spec} to reply with one word")
            job.log("It answered: " + self.providers.chat(spec, "Reply with the single word OK.", timeout=300)[:200])
        return self.submit("manage", f"Test {spec}", work)

    def create(self, body):
        """Start one creative job. They share the scheduled-jobs line, so the graphics card does one at a time."""
        kind, st = body.get("kind"), self.studio
        text = lambda k: str(body.get(k, "")).strip()  # noqa: E731
        strength = float(body["strength"]) if str(body.get("strength", "")).strip() else None
        jobs = {
            "image": ("Make an image", lambda j: st.generate_image(j.log, text("prompt"), text("lora"), strength)),
            "bulk": ("Edit a folder of photos", lambda j: st.bulk_edit(j.log, text("folder"), text("prompt"), text("lora"), strength)),
            "video": ("Make a video", lambda j: st.make_video(j.log, text("image"), text("prompt"))),
            "music": ("Make music", lambda j: st.make_music(j.log, text("style"), str(body.get("lyrics", "")), body.get("seconds") or 60)),
            "character": ("Prepare a character", lambda j: st.character_prepare(j.log, text("name"), text("folder"), text("trigger"), body.get("consent") is True)),
            "cad": ("Design a 3D model", lambda j: st.make_3d(j.log, text("description"), text("model") or None)),
        }
        if kind not in jobs:
            raise ValueError("That button doesn't exist.")
        title, work = jobs[kind]

        def run(job):
            try:
                work(job)
            except (studio.StudioError, providers.ModelError) as e:
                job.log(str(e))
                return False
        return self.submit("tasks", title, run)

    def lora(self, action, value):
        models = self.studio.models_dir()
        if action == "delete":
            comfy.lora_path(models, value).unlink(missing_ok=True)
            return None
        if action != "download":
            raise ValueError("That button doesn't exist.")
        comfy.lora_url(value)  # refuse a bad link now, not later in the job

        def work(job):
            try:
                comfy.download_lora(models, value, job.log, token=self.keys.get("civitai"))
            except comfy.ComfyError as e:
                job.log(str(e))
                return False
        return self.submit("manage", "Download a LoRA", work)

    def plugin_test(self, pid):
        p = self.hub.find(pid)

        def work(job):
            job.log(f"Starting {p['name']}. The first start can take a minute while it downloads.")
            self.hub.stop(pid)
            self.hub.connect(p)
            n = len(self.hub.tools[pid])
            job.log(f"It works: {n} tools." + (" Because that is a lot, agents will look them up on demand." if self.hub.is_on_demand(p) else ""))
        return self.submit("manage", f"Test plugin {p['name']}", work)

    def open_folder(self, kind):
        folder = {"outputs": self.root / "outputs", "characters": self.root / "characters", "apps": self.root / "apps"}.get(kind)
        if not folder:
            raise ValueError("No such folder.")
        folder.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(str(folder))  # opens it in File Explorer
        return str(folder)

    # ---------------------------------------------------------------- install, start, stop, uninstall

    def ensure_env(self, job):
        """compose.yaml needs a .env file holding a random secret. Make it if it's missing."""
        env = self.root / ".env"
        if not env.exists():
            text = (self.root / ".env.example").read_text(encoding="utf-8")
            env.write_text(re.sub(r"(?m)^WEBUI_SECRET_KEY=.*$", "WEBUI_SECRET_KEY=" + secrets.token_hex(32), text),
                           encoding="ascii")
            job.log("Created your private settings file (.env).")
        (self.root / "apps").mkdir(exist_ok=True)

    def act(self, cid, action):
        c = BY_ID.get(cid)
        allowed = {"winget": ("install", "uninstall"),
                   "compose": ("install", "start", "stop", "uninstall", "delete_data")}
        if not c or action not in allowed[c["kind"]]:
            raise ValueError("That button doesn't exist.")
        if action == "delete_data" and not c.get("volume"):
            raise ValueError(f"{c['name']} keeps no data to delete.")
        titles = {"install": "Install", "start": "Start", "stop": "Stop", "uninstall": "Uninstall",
                  "delete_data": "Uninstall and delete the data of"}
        return self.submit("manage", f"{titles[action]} {c['name']}", lambda job: self.do(job, c, action))

    def do(self, job, c, action):
        run = lambda args, **kw: self.sys.stream(args, job.log, **kw)  # noqa: E731
        if c["kind"] == "winget":
            if action == "install":
                job.log(f"Asking Windows to install {c['name']}. Approve the permission prompt if one appears.")
                code = run(["winget", "install", "--exact", "--id", c["winget"],
                            "--accept-source-agreements", "--accept-package-agreements"])
                if c["id"] == "ollama":
                    # The app builder needs models to remember more text than Ollama's default allows.
                    self.sys.run(["setx", "OLLAMA_CONTEXT_LENGTH", "32768"])
                    job.log("Set Ollama's memory per conversation to 32,768 tokens (applies after a restart).")
                ok = code == 0 or self.winget_installed(c["winget"], force=True)
                if ok and c.get("start_hint"):
                    job.log("Installed. Next: " + c["start_hint"])
                return ok
            job.log(f"Asking Windows to uninstall {c['name']}.")
            return run(["winget", "uninstall", "--exact", "--id", c["winget"]]) == 0

        if not self.docker_up():
            job.log("Docker isn't running. " + BY_ID["docker"]["start_hint"])
            return False
        compose = ["docker", "compose"]
        if action == "install":
            self.ensure_env(job)
            job.log(f"Downloading and starting {c['name']}. The first time can take several minutes.")
            return run(compose + ["up", "-d", c["service"]], cwd=self.root) == 0
        if action in ("start", "stop"):
            return run(compose + [action, c["service"]], cwd=self.root) == 0
        # uninstall, with or without the data
        ok = run(compose + ["rm", "--stop", "--force", c["service"]], cwd=self.root) == 0
        self.sys.run(["docker", "image", "rm", c["image"]], timeout=120)  # frees the disk space
        job.log(f"Removed {c['name']} and its download.")
        if action == "delete_data":
            code, out = self.sys.run(["docker", "volume", "rm", c["volume"]], timeout=60)
            gone = code == 0 or "no such volume" in out.lower()
            job.log(f"Deleted {c['data']}." if gone else f"Could not delete the data: {out.strip()}")
            ok = ok and gone
        elif c.get("volume"):
            job.log(f"Kept {c['data']}. Installing again brings it back.")
        return ok

    def set_autostart(self, on):
        """Start the panel quietly when you sign in to Windows, so scheduled jobs keep running."""
        if on:
            exe = Path(sys.executable)
            quiet = exe.with_name("pythonw.exe")  # Python without a console window
            command = f'"{quiet if quiet.exists() else exe}" "{HERE / "home.py"}" --no-browser'
            code, out = self.sys.run(["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", TASK_NAME,
                                      "/TR", command], timeout=30)
        else:
            code, out = self.sys.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME], timeout=30)
        if code != 0:
            raise ValueError("Windows refused: " + out.strip()[:300])
        self.autostart = on

    # ---------------------------------------------------------------- models

    def model(self, action, name):
        if not MODEL_NAME.fullmatch(name or ""):
            raise ValueError("That isn't a model name. It looks like gemma4:12b or hf.co/owner/repo:Q4_K_M.")
        if action == "pull":
            return self.submit("manage", f"Download {name}", lambda job: self.pull(job, name))
        if action == "delete":
            return self.submit("manage", f"Delete {name}", lambda job: self.call_ollama(
                job, "/api/delete", {"model": name}, "DELETE", f"Deleted {name} from disk."))
        if action == "unload":
            return self.submit("manage", f"Unload {name}", lambda job: self.call_ollama(
                job, "/api/generate", {"model": name, "keep_alive": 0}, "POST", f"{name} is off the graphics card."))
        raise ValueError("That button doesn't exist.")

    def call_ollama(self, job, path, body, method, done):
        try:
            api(self.ollama, path, body, method, timeout=120)
        except Exception as e:
            job.log(f"Ollama said no: {e}")
            return False
        job.log(done)

    def pull(self, job, name):
        req = urllib.request.Request(self.ollama + "/api/pull", data=json.dumps({"model": name}).encode(),
                                     headers={"Content-Type": "application/json"})
        last = None
        try:
            with urllib.request.urlopen(req, timeout=3600) as r:
                for raw in r:
                    msg = json.loads(raw)
                    if msg.get("error"):
                        job.log("Ollama could not download it: " + msg["error"])
                        return False
                    text = msg.get("status", "")
                    if msg.get("total"):
                        text += f" {int(100 * msg.get('completed', 0) / msg['total'])}%"
                    if text != last:
                        if last and last.split(" ")[:-1] == text.split(" ")[:-1] and job.lines:
                            job.lines[-1] = text  # same step, new percentage: update in place
                        else:
                            job.log(text)
                        last = text
        except Exception as e:
            job.log(f"Could not reach Ollama: {e}. Is it running?")
            return False
        job.log(f"{name} is ready. It now appears in the chat page's model list.")

    def fit_check(self, repo, context):
        repo = repo.replace("https://huggingface.co/", "").replace("hf.co/", "").strip("/ ")
        if not re.fullmatch(r"[\w.\-]+/[\w.\-]+", repo):
            raise ValueError('A Hugging Face repo looks like "owner/name". Use Search to find one.')
        vram = (self.gpu or {}).get("vram_gb") or 16
        try:
            versions = fit.variants(fit.get(f"{fit.API}/{repo}/tree/main?recursive=1"))
        except Exception as e:
            raise ValueError(f"Could not read {repo} from Hugging Face ({e}). Check the name.") from None
        rows = []
        for v in versions:
            need = fit.need_gb(v["bytes"], context, 1.0)
            rows.append({"quant": v["quant"], "gb": round(v["bytes"] / fit.GB, 1), "need": round(need, 1),
                         "verdict": fit.verdict(need, vram),
                         "pull": f"hf.co/{repo}:{v['quant']}" if v["quant"] != "?" else None})
        return {"repo": repo, "vram": vram, "context": context, "versions": rows}

    def fit_search(self, words):
        q = urllib.parse.urlencode({"search": words, "filter": "gguf", "sort": "downloads",
                                    "direction": "-1", "limit": 12})
        try:
            return [{"id": r["id"], "downloads": r.get("downloads", 0)} for r in fit.get(f"{fit.API}?{q}")]
        except Exception as e:
            raise ValueError(f"Could not search Hugging Face ({e}).") from None

    # ---------------------------------------------------------------- schedules

    def load(self):
        f = self.data / "schedules.json"
        try:
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        except ValueError:
            f.replace(f.with_suffix(".broken"))  # keep the damaged file for rescue, start clean
            return []

    def save(self):
        tmp = self.data / "schedules.tmp"
        tmp.write_text(json.dumps(self.schedules, indent=1), encoding="utf-8")
        tmp.replace(self.data / "schedules.json")

    def schedule_view(self, s):
        runs = sorted((self.data / "outputs" / s["id"]).glob("*.txt"), reverse=True)
        return {**s, "when_text": describe(s["when"]), "runs": [r.name for r in runs[:10]],
                "queued": s["id"] in self.busy_tasks}

    def schedule_save(self, body):
        name = str(body.get("name", "")).strip()[:80]
        kind = body.get("kind")
        if not name:
            raise ValueError("Give the job a name.")
        if kind not in ("prompt", "newsdesk", "command"):
            raise ValueError("Pick what the job should do.")
        when = parse_schedule(str(body.get("when_input", "")), self.now())
        s = {"name": name, "kind": kind, "when": when, "when_input": str(body["when_input"]).strip(),
             "enabled": True, "last": None}
        if kind == "prompt":
            s["model"], s["prompt"] = str(body.get("model", "")), str(body.get("prompt", "")).strip()
            if not MODEL_NAME.fullmatch(s["model"]) or not s["prompt"]:
                raise ValueError("Pick a model and write what to ask it.")
        if kind == "command":
            s["command"] = str(body.get("command", "")).strip()
            if not s["command"]:
                raise ValueError("Write the command to run.")
        nxt = next_run(when, self.now())
        s["next"] = nxt.isoformat(timespec="minutes") if nxt else None
        with self.lock:
            old = next((x for x in self.schedules if x["id"] == body.get("id")), None)
            if old:
                s["id"], s["last"] = old["id"], old.get("last")
                self.schedules[self.schedules.index(old)] = s
            else:
                s["id"] = secrets.token_hex(4)
                self.schedules.append(s)
            self.save()
        return s

    def schedule_change(self, sid, action):
        with self.lock:
            s = next((x for x in self.schedules if x["id"] == sid), None)
            if not s:
                raise ValueError("That job no longer exists.")
            if action == "delete":
                self.schedules.remove(s)
                shutil.rmtree(self.data / "outputs" / s["id"], ignore_errors=True)
            elif action == "toggle":
                s["enabled"] = not s["enabled"]
                nxt = next_run(s["when"], self.now()) if s["enabled"] else None
                s["next"] = nxt.isoformat(timespec="minutes") if nxt else None
            elif action == "run":
                self.launch(s)
            else:
                raise ValueError("That button doesn't exist.")
            self.save()

    def tick(self):
        """Called every few seconds: start any job whose time has come."""
        now = self.now()
        with self.lock:
            for s in self.schedules:
                if not s["enabled"] or not s.get("next") or dt.datetime.fromisoformat(s["next"]) > now:
                    continue
                self.launch(s)
                nxt = next_run(s["when"], now)  # from now, so a PC that was off doesn't replay a backlog
                s["next"] = nxt.isoformat(timespec="minutes") if nxt else None
                if not nxt:
                    s["enabled"] = False  # a one-time job has had its turn
            self.save()

    def launch(self, s):
        if s["id"] in self.busy_tasks:
            return  # still waiting or running from last time: don't pile up copies
        self.busy_tasks.add(s["id"])
        snapshot = dict(s)
        self.submit("tasks", f"Scheduled: {s['name']}", lambda job: self.run_task(job, snapshot))

    def run_task(self, job, s):
        started, lines, ok = self.now(), [], True
        try:
            if s["kind"] == "prompt":
                # A fresh conversation every time: the job has no memory of earlier runs or chats.
                job.log(f"Asking {s['model']}")
                lines = [self.providers.chat(s["model"], s["prompt"]) or "(the model gave an empty answer)"]
            else:
                if s["kind"] == "newsdesk":
                    args, shell = [sys.executable, str(self.root / "newsdesk" / "newsdesk.py"), "run"], False
                else:
                    args, shell = s["command"], True
                code = self.sys.stream(args, lambda ln: (lines.append(ln), job.log(ln)), cwd=self.root, shell=shell)
                ok = code == 0
                if not ok:
                    lines.append(f"(it ended with error code {code})")
        except Exception as e:
            ok = False
            lines.append(f"It failed: {e}")
            job.log(lines[-1])
        finally:
            folder = self.data / "outputs" / s["id"]
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{started:%Y-%m-%d %H%M%S}.txt").write_text("\n".join(lines), encoding="utf-8")
            for old in sorted(folder.glob("*.txt"))[:-50]:
                old.unlink()
            with self.lock:
                self.busy_tasks.discard(s["id"])
                live = next((x for x in self.schedules if x["id"] == s["id"]), None)
                if live:
                    live["last"] = {"at": started.isoformat(timespec="minutes"), "ok": ok}
                    self.save()
        job.log("Saved the result. See it on the Schedule tab.")
        return ok

    def output(self, sid, name):
        if not re.fullmatch(r"[0-9a-f]{8}", sid) or not re.fullmatch(r"[\d\- ]+\.txt", name):
            raise ValueError("No such result.")
        return (self.data / "outputs" / sid / name).read_text(encoding="utf-8")

    # ---------------------------------------------------------------- running in the background

    def start_threads(self):
        for line in self.queues:
            threading.Thread(target=self.worker, args=(line,), daemon=True).start()

        def loop(work, pause):
            while True:
                try:
                    work()
                except Exception:
                    pass
                time.sleep(pause)
        threading.Thread(target=loop, args=(self.refresh, 6), daemon=True).start()
        threading.Thread(target=loop, args=(self.tick, 15), daemon=True).start()


# ================================================================== the web page

class Handler(BaseHTTPRequestHandler):
    app = None

    def log_message(self, *a):
        pass

    def reply(self, code, body, kind="application/json"):
        data = body if isinstance(body, bytes) else (
            body.encode() if isinstance(body, str) else json.dumps(body).encode())
        self.send_response(code)
        self.send_header("Content-Type", kind + ("; charset=utf-8" if "text" in kind or "json" in kind else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def local(self):
        """Only answer when the browser asked for this PC by name. This blocks a trick where an
        outside website points its own name at 127.0.0.1 to reach the panel."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ("localhost", "127.0.0.1")

    def trusted(self):
        return self.local() and secrets.compare_digest(self.headers.get("X-Token") or "", self.app.token)

    def do_GET(self):
        if not self.local():
            return self.reply(403, {"error": "This page only answers on the PC itself."})
        url = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        try:
            if url.path == "/":
                page = (HERE / "index.html").read_text(encoding="utf-8")
                return self.reply(200, page.replace("__TOKEN__", self.app.token), "text/html")
            if url.path.startswith("/guide/"):
                name = url.path.removeprefix("/guide/")
                if name not in {f for f, _ in GUIDES}:
                    return self.reply(404, "No such guide.", "text/plain")
                return self.reply(200, (ROOT / "docs" / name).read_text(encoding="utf-8"), "text/plain")
            m = re.fullmatch(r"/drafts/(\d{4}-\d{2}-\d{2})/review\.html", url.path)
            if m:
                f = self.app.root / "newsdesk" / "drafts" / m.group(1) / "review.html"
                return self.reply(200, f.read_bytes(), "text/html") if f.exists() else self.reply(404, "Not found.", "text/plain")
            m = re.fullmatch(r"/out/(images|edits|video|music)/([^/\\]+)", urllib.parse.unquote(url.path))
            m3 = re.fullmatch(r"/out/3d/([^/\\]+)/(preview\.png|model\.stl|model\.scad)", urllib.parse.unquote(url.path))
            if m or m3:
                f = self.app.root / "outputs" / (m.group(1) if m else "3d") / (m.group(2) if m else m3.group(1) + "/" + m3.group(2))
                kind = MEDIA.get(f.suffix.lower())
                if ".." in f.parts or not kind or not f.is_file():
                    return self.reply(404, "Not found.", "text/plain")
                return self.reply(200, f.read_bytes(), kind)
            if not self.trusted():
                return self.reply(403, {"error": "Reload the page."})
            if url.path == "/api/openrouter":
                return self.reply(200, self.app.providers.openrouter_models(q.get("q", "")))
            if url.path == "/api/state":
                return self.reply(200, self.app.state())
            if url.path == "/api/fit":
                return self.reply(200, self.app.fit_check(q.get("repo", ""), int(q.get("context") or 8192)))
            if url.path == "/api/search":
                return self.reply(200, self.app.fit_search(q.get("q", "")))
            if url.path == "/api/output":
                return self.reply(200, {"text": self.app.output(q.get("id", ""), q.get("file", ""))})
            self.reply(404, {"error": "Not found."})
        except (ValueError, OSError, providers.ModelError) as e:
            self.reply(400, {"error": str(e)})

    def do_POST(self):
        if not self.trusted():
            return self.reply(403, {"error": "Reload the page."})
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 20_000_000)) or b"{}")
            if self.path == "/api/component":
                job = self.app.act(body.get("id"), body.get("action"))
            elif self.path == "/api/model":
                job = self.app.model(body.get("action"), str(body.get("name", "")).strip())
            elif self.path == "/api/schedule":
                return self.reply(200, self.app.schedule_save(body))
            elif self.path == "/api/schedule/change":
                self.app.schedule_change(body.get("id"), body.get("action"))
                return self.reply(200, {})
            elif self.path == "/api/key":
                job = self.app.set_key(body.get("id"), str(body.get("value", "")))
                return self.reply(200, {"job": job.id if job else None})
            elif self.path == "/api/cloud_model":
                self.app.set_cloud_model(body.get("action"), body.get("spec"))
                return self.reply(200, {})
            elif self.path == "/api/model/test":
                job = self.app.test_model(str(body.get("spec", "")).strip())
            elif self.path == "/api/settings":
                return self.reply(200, self.app.studio.save_settings(body))
            elif self.path == "/api/workflow":
                return self.reply(200, self.app.studio.save_workflow(body.get("role"), str(body.get("text", ""))))
            elif self.path == "/api/create":
                job = self.app.create(body)
            elif self.path == "/api/lora":
                job = self.app.lora(body.get("action"), str(body.get("value", "")))
                return self.reply(200, {"job": job.id if job else None})
            elif self.path == "/api/plugin":
                return self.reply(200, self.app.hub.add(body.get("name", ""), body.get("command", ""), body.get("url", ""), body.get("instructions", "")))
            elif self.path == "/api/plugin/change":
                self.app.hub.change(body.get("id"), body.get("action"))
                return self.reply(200, {})
            elif self.path == "/api/plugin/test":
                job = self.app.plugin_test(body.get("id"))
            elif self.path == "/api/open":
                return self.reply(200, {"folder": self.app.open_folder(body.get("kind"))})
            elif self.path == "/api/autostart":
                self.app.set_autostart(bool(body.get("on")))
                return self.reply(200, {})
            elif self.path == "/api/preview":
                when = parse_schedule(str(body.get("when_input", "")), self.app.now())
                nxt = next_run(when, self.app.now())
                return self.reply(200, {"text": describe(when), "next": nxt.isoformat(timespec="minutes") if nxt else None})
            else:
                return self.reply(404, {"error": "Not found."})
            self.reply(200, {"job": job.id})
        except (ValueError, OSError, studio.StudioError, comfy.ComfyError, gateway.PluginError, providers.ModelError) as e:
            self.reply(400, {"error": str(e)})


def serve(app, port=PORT):
    handler = type("H", (Handler,), {"app": app})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def main(argv=None):
    p = argparse.ArgumentParser(description="AI Home control panel.")
    p.add_argument("--no-browser", action="store_true", help="don't open the page (used at Windows sign-in)")
    p.add_argument("--port", type=int, default=PORT)
    a = p.parse_args(argv)
    app = App()
    try:
        server = serve(app, a.port)
    except OSError:
        # Already running (for example, started at sign-in): just show the page.
        if not a.no_browser:
            webbrowser.open(f"http://localhost:{a.port}")
        return
    app.start_threads()
    try:  # the plugin hub: where the chat page and app builder find their tools
        hub_server = gateway.serve_hub(app.hub, app.hub_port)
        threading.Thread(target=hub_server.serve_forever, daemon=True).start()
    except OSError:
        print(f"Port {app.hub_port} is busy, so the plugin hub is off this time.")
    print(f"AI Home is running at http://localhost:{a.port}\nLeave this window open. Close it to stop scheduled jobs.")
    if not a.no_browser:
        webbrowser.open(f"http://localhost:{a.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.hub.stop_all()  # don't leave plugin programs running


if __name__ == "__main__":
    main()
