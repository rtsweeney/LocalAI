"""Tests for the AI Home control panel, run against a pretend PC and a pretend Ollama.

The pretend PC answers winget, docker, schtasks and friends the way Windows would, and remembers
what has been "installed", so these tests can press the panel's buttons without touching a real
machine. No GPU, Docker or internet is needed.
"""
import datetime as dt
import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "home"))
import home  # noqa: E402

SAT = dt.datetime(2026, 11, 14, 17, 5)  # a Saturday


class FakePC:
    def __init__(self):
        self.programs, self.services, self.volumes, self.images = set(), {}, set(), set()
        self.docker_running = False
        self.tasks, self.env, self.calls = set(), {}, []
        self.command_results = {}

    def http_ok(self, url, timeout=3):
        return False

    def run(self, args, timeout=120, cwd=None):
        self.calls.append(list(args))
        a = list(args)
        if a[0] == "winget" and a[1] == "list":
            pkg = a[a.index("--id") + 1]
            return (0, f"Name Id\nThing {pkg}") if pkg in self.programs else (1, "No installed package found.")
        if a[:2] == ["docker", "info"]:
            return (0, "ok") if self.docker_running else (1, "cannot connect")
        if a[:3] == ["docker", "compose", "ps"]:
            return 0, "\n".join(json.dumps({"Service": s, "State": st}) for s, st in self.services.items())
        if a[:3] == ["docker", "image", "rm"]:
            self.images.discard(a[3])
            return 0, ""
        if a[:3] == ["docker", "volume", "rm"]:
            if a[3] in self.volumes:
                self.volumes.discard(a[3])
                return 0, a[3]
            return 1, "Error: No such volume"
        if a[0] == "nvidia-smi":
            return 0, "NVIDIA GeForce RTX 5080, 16303\n"
        if a[0] == "setx":
            self.env[a[1]] = a[2]
            return 0, ""
        if a[0] == "schtasks":
            name = a[a.index("/TN") + 1]
            if "/Query" in a:
                return (0, "") if name in self.tasks else (1, "ERROR: cannot find")
            self.tasks.add(name) if "/Create" in a else self.tasks.discard(name)
            return 0, "SUCCESS"
        return 127, "unknown"

    def stream(self, args, on_line, cwd=None, shell=False, timeout=7200):
        self.calls.append(args if isinstance(args, str) else list(args))
        if isinstance(args, str):  # a scheduled command
            code, lines = self.command_results.get(args, (0, ["ran " + args]))
            for ln in lines:
                on_line(ln)
            return code
        a = list(args)
        if a[0] == "winget":
            pkg = a[a.index("--id") + 1]
            self.programs.add(pkg) if a[1] == "install" else self.programs.discard(pkg)
            on_line(f"Successfully {a[1]}ed")
            return 0
        if a[:2] == ["docker", "compose"]:
            verb, svc = a[2], a[-1]
            if verb == "up":
                self.services[svc] = "running"
                self.volumes.update({"open-webui": {"localai_open-webui"},
                                     "agent-canvas": {"localai_openhands-data"}}.get(svc, set()))
            elif verb == "start":
                self.services[svc] = "running"
            elif verb == "stop":
                self.services[svc] = "exited"
            elif verb == "rm":
                self.services.pop(svc, None)
            on_line(f"Container {svc} {verb}")
            return 0
        if "newsdesk.py" in str(a[1:2]):
            on_line("4/4 Writing the review page")
            return 0
        return 127


class FakeOllama(BaseHTTPRequestHandler):
    models = {}
    loaded = set()
    chats = []

    def log_message(self, *a):
        pass

    def send(self, obj, raw=None):
        data = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")

    def do_GET(self):
        if self.path == "/api/tags":
            self.send({"models": [{"name": n, "size": s} for n, s in FakeOllama.models.items()]})
        elif self.path == "/api/ps":
            self.send({"models": [{"name": n} for n in FakeOllama.loaded]})

    def do_POST(self):
        b = self.body()
        if self.path == "/api/pull":
            if "missing" in b["model"]:
                return self.send(None, b'{"error":"pull model manifest: file does not exist"}\n')
            FakeOllama.models[b["model"]] = 7_000_000_000
            steps = [{"status": "pulling manifest"}, {"status": "pulling abc", "total": 100, "completed": 10},
                     {"status": "pulling abc", "total": 100, "completed": 100}, {"status": "success"}]
            self.send(None, "".join(json.dumps(s) + "\n" for s in steps).encode())
        elif self.path == "/api/generate":
            FakeOllama.loaded.discard(b["model"])
            self.send({})
        elif self.path == "/api/chat":
            FakeOllama.chats.append(b)
            self.send({"message": {"content": "Three ideas: A, B, C."}})

    def do_DELETE(self):
        b = self.body()
        if FakeOllama.models.pop(b["model"], None) is None:
            return self.send_error(404)
        self.send({})


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ollama = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=cls.ollama.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.ollama.shutdown()

    def setUp(self):
        FakeOllama.models, FakeOllama.loaded, FakeOllama.chats = {"gemma4:12b": 7_600_000_000}, {"gemma4:12b"}, []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copy(ROOT / ".env.example", self.root / ".env.example")
        self.pc, self.clock = FakePC(), [SAT]
        self.app = home.App(system=self.pc, root=self.root, data=self.root / "data",
                            ollama=f"http://127.0.0.1:{self.ollama.server_port}", now=lambda: self.clock[0])
        self.app.refresh()

    def press(self, cid, action):
        job = self.app.act(cid, action)
        self.app.drain()
        return job

    def part(self, cid):
        return next(c for c in self.app.state()["components"] if c["id"] == cid)


class PartsTest(Base):
    def test_fresh_pc_shows_nothing_installed_and_reads_the_gpu(self):
        st = self.app.state()
        self.assertTrue(all(not c["installed"] for c in st["components"]))
        self.assertEqual(st["gpu"], {"name": "NVIDIA GeForce RTX 5080", "vram_gb": 16})
        self.assertEqual([c["id"] for c in st["components"] if c["group"] == "required"], ["ollama", "docker", "chat"])

    def test_one_click_install_and_uninstall_of_a_windows_program(self):
        job = self.press("ollama", "install")
        self.assertEqual(job.status, "done")
        self.assertIn(["winget", "install", "--exact", "--id", "Ollama.Ollama",
                       "--accept-source-agreements", "--accept-package-agreements"], self.pc.calls)
        self.assertEqual(self.pc.env, {"OLLAMA_CONTEXT_LENGTH": "32768"})  # needed by the app builder
        self.assertTrue(self.part("ollama")["installed"])
        self.press("comfyui", "install")
        self.assertIn("Comfy.ComfyUI-Desktop", self.pc.programs)
        self.assertEqual(self.press("comfyui", "uninstall").status, "done")
        self.assertFalse(self.part("comfyui")["installed"])
        self.assertTrue(self.part("ollama")["installed"])  # removing one part leaves the others

    def test_docker_part_refuses_politely_when_docker_is_off(self):
        job = self.press("chat", "install")
        self.assertEqual(job.status, "failed")
        self.assertIn("Docker isn't running", job.lines[0])
        self.assertFalse(any(c[:3] == ["docker", "compose", "up"] for c in self.pc.calls if isinstance(c, list)))
        self.assertFalse((self.root / ".env").exists())

    def test_chat_page_lifecycle_keeps_data_until_told_to_delete_it(self):
        self.pc.docker_running = True
        self.assertEqual(self.press("chat", "install").status, "done")
        env = (self.root / ".env").read_text()
        self.assertRegex(env, r"WEBUI_SECRET_KEY=[0-9a-f]{64}\n")
        self.assertEqual(self.part("chat"), {**self.part("chat"), "installed": True, "running": True})
        self.press("chat", "stop")
        self.assertEqual((self.part("chat")["installed"], self.part("chat")["running"]), (True, False))
        self.press("chat", "start")
        self.assertTrue(self.part("chat")["running"])

        job = self.press("chat", "uninstall")
        self.assertFalse(self.part("chat")["installed"])
        self.assertIn("localai_open-webui", self.pc.volumes)  # chats survive a plain uninstall
        self.assertIn("Kept your chats", " ".join(job.lines))

        self.press("chat", "install")
        self.assertEqual((self.root / ".env").read_text(), env)  # the secret is not regenerated
        job = self.press("chat", "delete_data")
        self.assertEqual(job.status, "done")
        self.assertNotIn("localai_open-webui", self.pc.volumes)
        self.assertFalse(self.part("chat")["installed"])

    def test_buttons_that_do_not_exist_are_refused(self):
        for cid, action in (("nope", "install"), ("ollama", "start"), ("ollama", "delete_data"),
                            ("voice", "delete_data"), ("chat", "rm -rf")):
            with self.assertRaises(ValueError):
                self.app.act(cid, action)
        self.assertEqual(self.app.jobs, [])

    def test_start_with_windows_switch(self):
        self.app.set_autostart(True)
        create = next(c for c in self.pc.calls if c[0] == "schtasks" and "/Create" in c)
        self.assertIn("ONLOGON", create)
        self.assertIn("--no-browser", create[create.index("/TR") + 1])
        self.app.refresh()
        self.assertTrue(self.app.state()["autostart"])
        self.app.set_autostart(False)
        self.app.refresh()
        self.assertFalse(self.app.state()["autostart"])


class ModelsTest(Base):
    def test_list_download_unload_delete(self):
        st = self.app.state()
        self.assertEqual(st["models"], [{"name": "gemma4:12b", "gb": 7.6, "loaded": True}])
        self.assertEqual({s["name"]: s["have"] for s in st["starters"]},
                         {"gpt-oss:20b": False, "gemma4:12b": True, "qwen3-embedding:0.6b": False})
        job = self.app.model("pull", "hf.co/unsloth/gemma-4-12b-it-GGUF:Q4_K_M")
        self.app.drain()
        self.assertEqual(job.status, "done")
        self.assertEqual(job.lines[:3], ["pulling manifest", "pulling abc 100%", "success"])  # progress updates in place
        self.app.model("unload", "gemma4:12b")
        self.app.model("delete", "hf.co/unsloth/gemma-4-12b-it-GGUF:Q4_K_M")
        self.app.drain()
        self.assertEqual(self.app.state()["models"], [{"name": "gemma4:12b", "gb": 7.6, "loaded": False}])

    def test_failed_download_and_bad_names(self):
        job = self.app.model("pull", "missing:1b")
        self.app.drain()
        self.assertEqual(job.status, "failed")
        self.assertIn("could not download", job.lines[-1])
        job = self.app.model("delete", "never-had:1b")
        self.app.drain()
        self.assertEqual(job.status, "failed")
        for bad in ("", "a b", "x; rm -rf /", "--help", "a" * 300):
            with self.assertRaises(ValueError):
                self.app.model("pull", bad)

    def test_ollama_off_is_reported_not_crashed(self):
        self.app.ollama = "http://127.0.0.1:9"
        self.assertIsNone(self.app.state()["models"])


class ScheduleTest(Base):
    def add(self, **kw):
        return self.app.schedule_save({"name": "Job", "kind": "command", "command": "echo hi",
                                       "when_input": "daily at 5am", **kw})

    def outputs(self, s):
        return sorted((self.root / "data" / "outputs" / s["id"]).glob("*.txt"))

    def test_runs_at_its_time_once_and_reschedules(self):
        s = self.add()
        self.assertEqual(s["next"], "2026-11-15T05:00")
        self.clock[0] = dt.datetime(2026, 11, 15, 4, 59)
        self.app.tick()
        self.app.drain()
        self.assertEqual(self.outputs(s), [])
        self.clock[0] = dt.datetime(2026, 11, 15, 5, 0, 20)
        self.app.tick()
        self.app.tick()  # a second look in the same minute must not start a second copy
        self.app.drain()
        self.assertEqual(len(self.outputs(s)), 1)
        self.assertEqual(self.outputs(s)[0].read_text(), "ran echo hi")
        view = self.app.state()["schedules"][0]
        self.assertEqual((view["next"], view["last"]), ("2026-11-16T05:00", {"at": "2026-11-15T05:00", "ok": True}))
        saved = json.loads((self.root / "data" / "schedules.json").read_text())
        self.assertEqual(saved[0]["next"], "2026-11-16T05:00")  # survives a restart

    def test_pc_that_was_off_catches_up_once_not_once_per_missed_day(self):
        s = self.add()
        self.clock[0] = dt.datetime(2026, 11, 20, 9, 0)  # five mornings missed
        self.app.tick()
        self.app.drain()
        self.app.tick()
        self.app.drain()
        self.assertEqual(len(self.outputs(s)), 1)
        self.assertEqual(self.app.state()["schedules"][0]["next"], "2026-11-21T05:00")

    def test_one_time_job_turns_itself_off(self):
        s = self.add(when_input="in 30m")
        self.clock[0] = SAT + dt.timedelta(minutes=31)
        self.app.tick()
        self.app.drain()
        view = self.app.state()["schedules"][0]
        self.assertEqual((len(self.outputs(s)), view["enabled"], view["next"]), (1, False, None))

    def test_model_job_asks_fresh_and_saves_the_answer(self):
        s = self.add(kind="prompt", model="gemma4:12b", prompt="Give me three ideas.")
        self.app.schedule_change(s["id"], "run")
        self.app.schedule_change(s["id"], "run")  # pressed twice: still one run
        self.app.drain()
        self.assertEqual(len(FakeOllama.chats), 1)
        self.assertEqual(FakeOllama.chats[0]["messages"], [{"role": "user", "content": "Give me three ideas."}])
        name = self.app.state()["schedules"][0]["runs"][0]
        self.assertEqual(self.app.output(s["id"], name), "Three ideas: A, B, C.")

    def test_failures_are_recorded_and_news_desk_job_runs_the_news_desk(self):
        self.pc.command_results["bad"] = (3, ["boom"])
        s = self.add(command="bad")
        n = self.add(kind="newsdesk", name="News")
        self.app.schedule_change(s["id"], "run")
        self.app.schedule_change(n["id"], "run")
        self.app.drain()
        by = {x["name"]: x for x in self.app.state()["schedules"]}
        self.assertFalse(by["Job"]["last"]["ok"])
        self.assertIn("error code 3", self.outputs(s)[0].read_text())
        self.assertTrue(by["News"]["last"]["ok"])
        self.assertTrue(any(isinstance(c, list) and str(c[-2]).endswith("newsdesk.py") and c[-1] == "run" for c in self.pc.calls))

    def test_turn_off_edit_and_delete(self):
        s = self.add()
        self.app.schedule_change(s["id"], "toggle")
        self.clock[0] = dt.datetime(2026, 11, 16, 6, 0)
        self.app.tick()
        self.app.drain()
        self.assertEqual(self.outputs(s), [])  # off means off
        self.app.schedule_change(s["id"], "run")
        self.app.drain()
        edited = self.app.schedule_save({"id": s["id"], "name": "Renamed", "kind": "command",
                                         "command": "echo hi", "when_input": "every 2h"})
        self.assertEqual((edited["id"], edited["last"]["ok"], len(self.app.schedules)), (s["id"], True, 1))
        self.app.schedule_change(s["id"], "delete")
        self.assertEqual((self.app.schedules, self.outputs(s)), ([], []))

    def test_bad_jobs_are_refused_with_a_reason(self):
        for kw in ({"name": ""}, {"kind": "format-disk"}, {"when_input": "whenever"}, {"command": " "},
                   {"kind": "prompt", "model": "gemma4:12b", "prompt": ""}, {"kind": "prompt", "model": "", "prompt": "x"}):
            with self.assertRaises(ValueError):
                self.add(**kw)
        self.assertEqual(self.app.schedules, [])

    def test_schedule_phrases(self):
        def nxt(text):
            return str(home.next_run(home.parse_schedule(text, SAT), SAT))
        self.assertEqual(nxt("every 2h"), "2026-11-14 19:05:00")
        self.assertEqual(nxt("every hour"), "2026-11-14 18:05:00")
        self.assertEqual(nxt("in 45m"), "2026-11-14 17:50:00")
        self.assertEqual(nxt("daily at 9am"), "2026-11-15 09:00:00")
        self.assertEqual(nxt("weekdays at 6:30"), "2026-11-16 06:30:00")  # skips Sunday
        self.assertEqual(nxt("weekends at 10"), "2026-11-15 10:00:00")
        self.assertEqual(nxt("Mon, Wed and Fri at 8pm"), "2026-11-16 20:00:00")
        self.assertEqual(nxt("thursdays at 12am"), "2026-11-19 00:00:00")
        self.assertEqual(nxt("once 2026-12-01 14:00"), "2026-12-01 14:00:00")
        self.assertEqual(nxt("*/15 9-17 * * mon-fri"), "2026-11-16 09:00:00")
        self.assertEqual(nxt("0 0 29 2 *"), "2028-02-29 00:00:00")  # a leap day is found
        self.assertEqual(nxt("0 12 1 * 0"), "2026-11-15 12:00:00")  # day-of-month OR day-of-week
        every = home.parse_schedule("every 2h", SAT)
        self.assertEqual(str(home.next_run(every, SAT + dt.timedelta(hours=5))), "2026-11-14 23:05:00")
        for bad in ("", "tomorrow", "daily at 25:00", "daily at 13pm", "once 2020-01-01 10:00",
                    "61 * * * *", "someday at 9", "every 0m", "once 2026-02-30 10:00"):
            with self.assertRaises(ValueError, msg=bad):
                home.parse_schedule(bad, SAT)


class WebTest(Base):
    def setUp(self):
        super().setUp()
        self.server = home.serve(self.app, 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def get(self, path, token=True, host=None, body=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Token"] = self.app.token if token is True else token
        if host:
            headers["Host"] = host
        req = urllib.request.Request(self.base + path, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_page_and_state_load(self):
        code, page = self.get("/", token=False)
        self.assertEqual(code, 200)
        self.assertIn(self.app.token, page)
        self.assertNotIn("__TOKEN__", page)
        code, text = self.get("/api/state")
        self.assertEqual(code, 200)
        self.assertEqual(len(json.loads(text)["components"]), len(home.COMPONENTS))

    def test_another_website_cannot_press_buttons(self):
        install = {"id": "comfyui", "action": "install"}
        self.assertEqual(self.get("/api/component", token=False, body=install)[0], 403)   # no secret
        self.assertEqual(self.get("/api/component", token="guess", body=install)[0], 403)  # wrong secret
        self.assertEqual(self.get("/api/component", host="evil.example", body=install)[0], 403)  # name trick
        self.assertEqual(self.get("/api/state", token=False)[0], 403)
        self.assertEqual(self.get("/", token=False, host="evil.example:3010")[0], 403)
        self.assertEqual(self.app.jobs, [])
        self.assertEqual(self.get("/api/component", body=install)[0], 200)

    def test_files_outside_the_allowed_folders_are_not_served(self):
        (self.root / "data" / "outputs" / "abcd1234").mkdir(parents=True)
        (self.root / "data" / "secret.txt").write_text("s")
        for path in ("/guide/../home/home.py", "/guide/..%2F.env.example", "/guide/nope.md",
                     "/drafts/../../etc/passwd", "/drafts/2026-11-14/../../config.json"):
            self.assertIn(self.get(path)[0], (403, 404), path)
        for q in ("id=abcd1234&file=../secret.txt", "id=..&file=secret.txt", "id=abcd1234&file=..%2Fsecret.txt"):
            self.assertEqual(self.get("/api/output?" + q)[0], 400, q)
        self.assertEqual(self.get("/guide/01-concepts.md")[0], 200)

    def test_schedule_buttons_over_the_web(self):
        code, text = self.get("/api/preview", body={"when_input": "weekdays at 6:30"})
        self.assertEqual((code, json.loads(text)["next"]), (200, "2026-11-16T06:30"))
        code, text = self.get("/api/preview", body={"when_input": "blah"})
        self.assertEqual(code, 400)
        self.assertIn("I don't understand", json.loads(text)["error"])
        code, text = self.get("/api/schedule", body={"name": "N", "kind": "newsdesk", "when_input": "daily at 5am"})
        self.assertEqual(code, 200)
        sid = json.loads(text)["id"]
        self.assertEqual(self.get("/api/schedule/change", body={"id": sid, "action": "delete"})[0], 200)
        self.assertEqual(self.get("/api/schedule/change", body={"id": sid, "action": "delete"})[0], 400)


if __name__ == "__main__":
    unittest.main()
