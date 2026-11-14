"""The plugin hub: one address where your agents find every tool.

A "plugin" is a small program that gives an AI agent new abilities, using a standard called
MCP (Model Context Protocol). REA, for example, is a plugin with tools for taking software
apart. Without a hub you would add each plugin to each agent separately. With it:

    chat page  --+
    app builder -+-->  the hub (this file)  --+--> AI Home's own tools (vision, images, CAD, music)
    other agents +                            +--> plugin: REA
                                              +--> plugin: anything else you add

Add a plugin once in AI Home and every connected agent can use it.

Two ways tools are offered to a model:
  * always listed    every tool's description is sent to the model up front. Simple, but each
                     description uses up some of the model's memory.
  * on demand        the model sees just two tools, "find_tools" and "use_tool", and looks up
                     what it needs. Essential for big plugins: REA has about 200 tools, far
                     more than a local model can keep in mind at once.

Uses only Python's standard library.
"""
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROTOCOL = "2025-06-18"
KNOWN_PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
ON_DEMAND_ABOVE = 25  # plugins with more tools than this start in on-demand mode
HUB_PORT = 3011
# Ready-made entries for the Plugins tab. "needs" is a program that must be installed first.
CATALOG = [
    {"name": "REA (reverse engineering)", "command": "npx -y rea-agents@6.7.0 mcp", "needs": "Node.js",
     "what": "About 200 tools for taking apart programs, apps and firmware. Needs Node.js, and your own "
             "Ghidra or similar for deep analysis. Some of its tools run or change things on this PC.",
     "instructions": "Before using any REA tool that runs a program, drives an app, changes a connected "
                     "device or overwrites a file, ask the user first. Skip those tools in unattended runs."},
    {"name": "Web page reader", "command": "uvx mcp-server-fetch", "needs": "uv",
     "what": "Lets an agent read a web page you point it at."},
    {"name": "Browser control", "command": "npx -y @playwright/mcp@latest", "needs": "Node.js",
     "what": "Lets an agent click through websites in a real browser."},
]


class PluginError(Exception):
    pass


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:20] or "plugin"


class StdioPlugin:
    """A plugin that runs as a child program and talks over its input and output."""

    def __init__(self, command, env=None):
        self.command, self.env = command, env
        self.proc, self.lock, self.waiting, self.count = None, threading.Lock(), {}, 0
        self.stderr_tail = []

    def start(self):
        exe = shutil.which(self.command[0])
        if not exe:
            raise PluginError(f"\"{self.command[0]}\" is not installed, or needs a restart to be found.")
        hidden = {"creationflags": 0x08000000} if os.name == "nt" else {}
        self.proc = subprocess.Popen([exe] + self.command[1:], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                     bufsize=1, env=self.env, **hidden)
        threading.Thread(target=self.read_loop, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self.err_loop, args=(self.proc,), daemon=True).start()
        self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                    "clientInfo": {"name": "ai-home", "version": "1.0"}}, timeout=180)
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def err_loop(self, proc):
        for line in proc.stderr:
            self.stderr_tail = (self.stderr_tail + [line.rstrip()])[-8:]

    def read_loop(self, proc):
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue  # plugins sometimes print stray text; ignore anything that isn't a message
            if not isinstance(msg, dict):
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                slot = self.waiting.get(msg["id"])
                if slot:
                    slot["msg"] = msg
                    slot["event"].set()
            elif "id" in msg and "method" in msg:  # the plugin is asking the hub for something
                reply = {"result": {}} if msg["method"] == "ping" else {
                    "error": {"code": -32601, "message": "The hub doesn't support that."}}
                self.send({"jsonrpc": "2.0", "id": msg["id"], **reply})
        for slot in list(self.waiting.values()):  # the program ended: wake anyone still waiting
            slot["event"].set()

    def send(self, msg):
        with self.lock:
            try:
                self.proc.stdin.write(json.dumps(msg) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError):
                raise PluginError("The plugin stopped running. " + " ".join(self.stderr_tail[-2:])) from None

    def request(self, method, params=None, timeout=600):
        if not self.alive():
            raise PluginError("The plugin stopped running. " + " ".join(self.stderr_tail[-2:]))
        with self.lock:
            self.count += 1
            rid = self.count
        slot = self.waiting[rid] = {"event": threading.Event(), "msg": None}
        try:
            self.send({"jsonrpc": "2.0", "id": rid, "method": method, **({"params": params} if params is not None else {})})
            if not slot["event"].wait(timeout):
                raise PluginError(f"The plugin did not answer within {timeout} seconds.")
            msg = slot["msg"]
        finally:
            self.waiting.pop(rid, None)
        if msg is None:
            raise PluginError("The plugin stopped before answering. " + " ".join(self.stderr_tail[-2:]))
        if "error" in msg:
            raise PluginError(str(msg["error"].get("message", msg["error"])))
        return msg["result"]

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


class HttpPlugin:
    """A plugin that is already running somewhere and is reached by web address."""

    def __init__(self, url, token=None):
        self.url, self.token, self.session, self.count, self.ok = url, token, None, 0, False

    def start(self):
        self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                    "clientInfo": {"name": "ai-home", "version": "1.0"}}, timeout=60)
        self.post({"jsonrpc": "2.0", "method": "notifications/initialized"}, 30)
        self.ok = True

    def post(self, msg, timeout):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url, json.dumps(msg).encode(), headers), timeout=timeout) as r:
                self.session = r.headers.get("Mcp-Session-Id") or self.session
                kind, raw = r.headers.get("Content-Type", ""), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise PluginError(f"The plugin's server returned an error ({e.code}).") from None
        except (urllib.error.URLError, OSError) as e:
            raise PluginError(f"Could not reach the plugin at {self.url} ({getattr(e, 'reason', e)}).") from None
        if "text/event-stream" in kind:  # the answer arrives as a stream of "data:" lines
            for line in raw.splitlines():
                if line.startswith("data:"):
                    try:
                        got = json.loads(line[5:])
                    except ValueError:
                        continue
                    if isinstance(got, dict) and got.get("id") == msg.get("id"):
                        return got
            return None
        return json.loads(raw) if raw.strip() else None

    def request(self, method, params=None, timeout=600):
        self.count += 1
        msg = self.post({"jsonrpc": "2.0", "id": self.count, "method": method,
                         **({"params": params} if params is not None else {})}, timeout)
        if not msg:
            raise PluginError("The plugin sent back nothing.")
        if "error" in msg:
            raise PluginError(str(msg["error"].get("message", msg["error"])))
        return msg["result"]

    def alive(self):
        return self.ok

    def stop(self):
        self.ok = False


def text_result(text, error=False):
    return {"content": [{"type": "text", "text": str(text)}], "isError": bool(error)}


class Hub:
    def __init__(self, data, builtins=()):
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.builtins = {t["name"]: t for t in builtins}
        self.lock = threading.RLock()
        self.live, self.tools, self.errors = {}, {}, {}
        tok = self.data / "hub_token"  # kept between restarts so agents stay connected
        if not tok.exists():
            tok.write_text(secrets.token_urlsafe(24), encoding="ascii")
        self.token = tok.read_text(encoding="ascii").strip()
        self.plugins = self.load()

    def load(self):
        try:
            return json.loads((self.data / "plugins.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def save(self):
        tmp = self.data / "plugins.tmp"
        tmp.write_text(json.dumps(self.plugins, indent=1), encoding="utf-8")
        tmp.replace(self.data / "plugins.json")

    # ---------------------------------------------------------------- managing plugins

    def add(self, name, command="", url="", instructions=""):
        name, command, url = str(name).strip()[:60], str(command).strip(), str(url).strip()
        if not name:
            raise PluginError("Give the plugin a name.")
        if bool(command) == bool(url):
            raise PluginError("Give either the command that starts the plugin, or its web address (not both).")
        if url and not re.match(r"https?://", url):
            raise PluginError("A plugin's web address starts with http:// or https://.")
        with self.lock:
            pid, n = slug(name), 2
            while any(p["id"] == pid for p in self.plugins):
                pid, n = f"{slug(name)[:17]}_{n}", n + 1
            p = {"id": pid, "name": name, "command": command, "url": url, "enabled": True,
                 "on_demand": None, "instructions": str(instructions).strip()[:2000]}
            self.plugins.append(p)
            self.save()
        return p

    def find(self, pid):
        p = next((p for p in self.plugins if p["id"] == pid), None)
        if not p:
            raise PluginError("That plugin no longer exists.")
        return p

    def change(self, pid, action):
        with self.lock:
            p = self.find(pid)
            if action == "remove":
                self.stop(pid)
                self.plugins.remove(p)
            elif action == "toggle":
                p["enabled"] = not p["enabled"]
                if not p["enabled"]:
                    self.stop(pid)
            elif action == "on_demand":
                p["on_demand"] = not self.is_on_demand(p)
            elif action == "restart":
                self.stop(pid)
            else:
                raise PluginError("That button doesn't exist.")
            self.save()

    def stop(self, pid):
        conn = self.live.pop(pid, None)
        if conn:
            conn.stop()
        self.tools.pop(pid, None)
        self.errors.pop(pid, None)

    def stop_all(self):
        for pid in list(self.live):
            self.stop(pid)

    def connect(self, p):
        """Start a plugin if it isn't running, and learn what tools it has."""
        with self.lock:
            conn = self.live.get(p["id"])
            if conn and conn.alive() and p["id"] in self.tools:
                return conn
            self.stop(p["id"])
            try:
                if p["url"]:
                    conn = HttpPlugin(p["url"])
                else:
                    conn = StdioPlugin(shlex.split(p["command"], posix=os.name != "nt"))
                conn.start()
                tools, cursor = [], None
                while True:
                    got = conn.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=120)
                    tools += got.get("tools", [])
                    cursor = got.get("nextCursor")
                    if not cursor:
                        break
            except (PluginError, OSError, ValueError) as e:
                conn and conn.stop()
                self.errors[p["id"]] = str(e)
                raise PluginError(f"{p['name']}: {e}") from None
            self.live[p["id"]], self.tools[p["id"]] = conn, tools
            self.errors.pop(p["id"], None)
            return conn

    def is_on_demand(self, p):
        if p.get("on_demand") is not None:
            return p["on_demand"]
        return len(self.tools.get(p["id"], [])) > ON_DEMAND_ABOVE

    def view(self):
        return [{**{k: p[k] for k in ("id", "name", "command", "url", "enabled")},
                 "running": p["id"] in self.live and self.live[p["id"]].alive(),
                 "tools": len(self.tools[p["id"]]) if p["id"] in self.tools else None,
                 "on_demand": self.is_on_demand(p), "error": self.errors.get(p["id"])} for p in self.plugins]

    # ---------------------------------------------------------------- what agents see

    def enabled(self):
        out = []
        for p in [p for p in self.plugins if p["enabled"]]:
            try:
                self.connect(p)
                out.append(p)
            except PluginError:
                pass  # a broken plugin must not take the working ones down with it
        return out

    def wire_name(self, p, tool):
        return f"{p['id']}__{tool['name']}"[:64]

    def list_tools(self):
        tools = [{k: t[k] for k in ("name", "description", "inputSchema")} for t in self.builtins.values()]
        lazy = False
        for p in self.enabled():
            if self.is_on_demand(p):
                lazy = True
                continue
            for t in self.tools[p["id"]]:
                tools.append({"name": self.wire_name(p, t), "description": f"[{p['name']}] {t.get('description', '')}",
                              "inputSchema": t.get("inputSchema") or {"type": "object"}})
        if lazy:
            tools += [
                {"name": "find_tools", "description": "Search the extra plugin tools by keyword. Returns matching "
                 "tool names, what they do, and the arguments they take. Use this first, then use_tool.",
                 "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
                {"name": "use_tool", "description": "Run a tool found with find_tools.",
                 "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "arguments": {"type": "object"}},
                                 "required": ["name"]}}]
        return tools

    def find_tools(self, query):
        words = [w for w in re.findall(r"[a-z0-9]+", str(query).lower()) if len(w) > 1]
        scored = []
        for p in self.enabled():
            if not self.is_on_demand(p):
                continue
            for t in self.tools[p["id"]]:
                name, desc = t["name"].lower(), str(t.get("description", "")).lower()
                score = sum(3 * (w in name) + (w in desc) for w in words)
                if score:
                    scored.append((score, self.wire_name(p, t), t))
        scored.sort(key=lambda s: (-s[0], s[1]))
        if not scored:
            return "No tools matched. Try different or fewer words."
        return json.dumps([{"name": n, "description": str(t.get("description", ""))[:400],
                            "arguments": t.get("inputSchema", {}).get("properties", {})} for _, n, t in scored[:8]], indent=1)

    def call(self, name, args):
        args = args if isinstance(args, dict) else {}
        if name in self.builtins:
            try:
                return text_result(self.builtins[name]["run"](args))
            except Exception as e:  # shown to the model so it can react, instead of breaking the chat
                return text_result(f"That didn't work: {e}", error=True)
        if name == "find_tools":
            return text_result(self.find_tools(args.get("query", "")))
        if name == "use_tool":
            name, args = str(args.get("name", "")), args.get("arguments") or {}
        for p in self.enabled():
            for t in self.tools[p["id"]]:
                if self.wire_name(p, t) == name:
                    try:
                        return self.live[p["id"]].request("tools/call", {"name": t["name"], "arguments": args})
                    except PluginError as e:
                        return text_result(f"{p['name']} failed: {e}", error=True)
        return text_result(f"There is no tool called {name}. Use find_tools to look one up.", error=True)

    def instructions(self):
        notes = [f"{p['name']}: {p['instructions']}" for p in self.plugins if p["enabled"] and p.get("instructions")]
        return "\n".join(["Tools from AI Home, running on the user's own PC."] + notes)

    def handle(self, msg):
        """Answer one MCP message. Returns None for messages that need no answer."""
        if not isinstance(msg, dict) or "method" not in msg:
            return None
        rid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
        if rid is None:
            return None  # a notification
        try:
            if method == "initialize":
                asked = params.get("protocolVersion")
                result = {"protocolVersion": asked if asked in KNOWN_PROTOCOLS else PROTOCOL,
                          "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "ai-home", "version": "1.0"}, "instructions": self.instructions()}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.list_tools()}
            elif method == "tools/call":
                result = self.call(str(params.get("name", "")), params.get("arguments"))
            else:
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": str(e)}}
        return {"jsonrpc": "2.0", "id": rid, "result": result}


class HubHandler(BaseHTTPRequestHandler):
    hub = None

    def log_message(self, *a):
        pass

    def reply(self, code, body=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        if data:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def allowed(self):
        # Reached from this PC, or from a Docker container on this PC (host.docker.internal).
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        given = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        return host in ("localhost", "127.0.0.1", "host.docker.internal") and secrets.compare_digest(given, self.hub.token)

    def do_GET(self):
        self.reply(405 if self.allowed() else 401, {"error": "This address only accepts POST."})

    do_DELETE = do_GET

    def do_POST(self):
        if not self.allowed():
            return self.reply(401, {"error": "Missing or wrong key."})
        if self.path.split("?")[0].rstrip("/") != "/mcp":
            return self.reply(404, {"error": "The hub's address ends in /mcp"})
        try:
            msg = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 20_000_000)))
        except ValueError:
            return self.reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
        if isinstance(msg, list):
            answers = [a for a in map(self.hub.handle, msg) if a]
            return self.reply(200, answers) if answers else self.reply(202)
        answer = self.hub.handle(msg)
        self.reply(200, answer) if answer else self.reply(202)


def serve_hub(hub, port=HUB_PORT):
    return ThreadingHTTPServer(("127.0.0.1", port), type("H", (HubHandler,), {"hub": hub}))
