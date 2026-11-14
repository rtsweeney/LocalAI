"""Tests for the creative jobs, LoRAs, cloud models and their buttons.

ComfyUI, the Claude API, OpenRouter, Ollama and OpenSCAD are all pretend versions running on
this computer, so nothing here needs a GPU, an API key or the internet. The Claude tests drive
the real `anthropic` library against the pretend server and are skipped if it isn't installed.
"""
import io
import json
import re
import struct
import sys
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "home"), str(ROOT / "tests")]
import comfy  # noqa: E402
import home  # noqa: E402
import providers  # noqa: E402
import studio  # noqa: E402
from test_home import FakePC  # noqa: E402

try:
    import anthropic  # noqa: F401
    HAVE_ANTHROPIC = True
except ImportError:
    HAVE_ANTHROPIC = False

# An edit workflow as ComfyUI exports it. The negative prompt (3) comes BEFORE the real prompt (4),
# and the prompt reaches the sampler through another box (9), so it can only be found by the wiring.
EDIT_WF = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
    "2": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, ugly", "clip": ["5", 1]}},
    "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "old prompt", "clip": ["5", 1]}},
    "5": {"class_type": "LoraLoader", "inputs": {"lora_name": "old.safetensors", "strength_model": 1.0, "strength_clip": 1.0,
                                                 "model": ["1", 0], "clip": ["1", 1]}},
    "6": {"class_type": "KSampler", "inputs": {"seed": 5, "steps": 8, "positive": ["9", 0], "negative": ["3", 0],
                                               "model": ["5", 0], "latent_image": ["7", 0]}},
    "7": {"class_type": "VAEEncode", "inputs": {"pixels": ["2", 0], "vae": ["1", 2]}},
    "8": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "ComfyUI"}},
    "9": {"class_type": "FluxGuidance", "inputs": {"guidance": 3.5, "conditioning": ["4", 0]}},
}
MUSIC_WF = {
    "1": {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {"tags": "old tags", "lyrics": "old lyrics", "clip": ["9", 0]}},
    "2": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["1", 0]}},
    "3": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": 120, "batch_size": 1}},
    "4": {"class_type": "KSampler", "inputs": {"seed": 1, "positive": ["1", 0], "negative": ["2", 0], "latent_image": ["3", 0]}},
    "5": {"class_type": "SaveAudio", "inputs": {"audio": ["4", 0]}},
}
IMAGE_WF = {k: v for k, v in EDIT_WF.items() if k not in ("2", "5", "7")}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 1024, 1024) + b"rest"
SMALL_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 400, 300) + b"rest"


class Fake(BaseHTTPRequestHandler):
    """ComfyUI, Claude, OpenRouter and Ollama in one pretend server, told apart by address."""
    jobs, uploads, polls, sent = {}, [], {}, []
    fail_images, claude_mode, cad_answers = set(), "ok", []

    def log_message(self, *a):
        pass

    def send(self, obj, code=200, raw=None, kind="application/json"):
        data = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/system_stats":
            return self.send({})
        if path.startswith("/history/"):
            pid = path.rsplit("/", 1)[1]
            Fake.polls[pid] = Fake.polls.get(pid, 0) + 1
            if Fake.polls[pid] < 2:
                return self.send({})  # still working the first time it's asked
            wf = Fake.jobs[pid]
            image = next((n["inputs"]["image"] for n in wf.values() if n["class_type"] == "LoadImage"), "")
            if any(f in image for f in Fake.fail_images):
                return self.send({pid: {"status": {"status_str": "error", "messages": [
                    ["execution_error", {"node_type": "KSampler", "exception_message": "CUDA out of memory"}]]}, "outputs": {}}})
            music = any("Audio" in n["class_type"] for n in wf.values())
            out = {"audio": [{"filename": "song_00001_.flac", "subfolder": "audio", "type": "output"}]} if music else \
                  {"images": [{"filename": "ComfyUI_00001_.png", "subfolder": "", "type": "output"},
                              {"filename": "preview.png", "subfolder": "", "type": "temp"}]}
            return self.send({pid: {"status": {"status_str": "success", "completed": True}, "outputs": {"8": out}}})
        if path == "/view":
            return self.send(None, raw=b"RESULT " + json.dumps(Fake.jobs[sorted(Fake.jobs)[-1]], sort_keys=True).encode(), kind="image/png")
        if path == "/or/models":
            return self.send({"data": [{"id": "google/gemini-pro", "name": "Gemini Pro"}, {"id": "meta/llama", "name": "Llama"}]})
        if path == "/v1/models":
            return self.send({"data": [{"id": "claude-opus-5-5", "type": "model", "display_name": "Claude Opus 5.5",
                                        "created_at": "2026-01-01T00:00:00Z"}], "has_more": False, "first_id": "claude-opus-5-5",
                              "last_id": "claude-opus-5-5"})
        if path == "/api/tags":
            return self.send({"models": [{"name": "gemma4:12b", "size": 7_000_000_000}, {"name": "gpt-oss:20b", "size": 1}]})
        if path == "/api/ps":
            return self.send({"models": []})
        if path == "/lora/ok.safetensors":
            return self.send(None, raw=b"S" * 3000, kind="application/octet-stream")
        self.send({}, 404)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        path = self.path.split("?")[0]
        if path == "/upload/image":
            name = re.search(rb'filename="([^"]+)"', raw).group(1).decode()
            Fake.uploads.append(name)
            return self.send({"name": name, "subfolder": "", "type": "input"})
        body = json.loads(raw or b"{}")
        if path == "/prompt":
            wf = body["prompt"]
            bad = [n for n in wf.values() if n["class_type"] == "LoraLoader" and n["inputs"]["lora_name"] == "missing.safetensors"]
            if bad:
                return self.send({"error": {"message": "Prompt outputs failed validation"}, "node_errors": {"5": {
                    "class_type": "LoraLoader", "errors": [{"message": "Value not in list", "details": "lora_name: 'missing.safetensors' not in ['a']"}]}}}, 400)
            pid = f"job{len(Fake.jobs) + 1:03d}"
            Fake.jobs[pid] = wf
            return self.send({"prompt_id": pid})
        Fake.sent.append({"path": self.path, "body": body, "headers": {k.lower(): v for k, v in self.headers.items()}})
        if path == "/v1/messages":
            if Fake.claude_mode == "badkey":
                return self.send({"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}, 401)
            stop = "refusal" if Fake.claude_mode == "refusal" else "end_turn"
            return self.send({"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"], "stop_sequence": None,
                              "content": [{"type": "text", "text": "Hello from Claude"}], "stop_reason": stop,
                              "usage": {"input_tokens": 3, "output_tokens": 4}})
        if path == "/or/chat/completions":
            if body["model"] == "broke/model":
                return self.send({"error": {"message": "Insufficient credits"}}, 402)
            return self.send({"choices": [{"message": {"content": "Hello from OpenRouter"}}]})
        if path == "/api/show":
            return self.send({"capabilities": ["completion", "vision"] if body["model"].startswith("gemma") else ["completion"]})
        if path == "/api/chat":
            if body["messages"][0]["role"] == "system":  # the 3D designer
                return self.send({"message": {"content": Fake.cad_answers.pop(0)}})
            if body["messages"][-1].get("images"):
                return self.send({"message": {"content": "A photo of someone standing in a kitchen, seen from the side."}})
            return self.send({"message": {"content": "OK"}})
        self.send({}, 404)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Fake.jobs, Fake.uploads, Fake.polls, Fake.sent = {}, [], {}, []
        Fake.fail_images, Fake.claude_mode, Fake.cad_answers = set(), "ok", []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / ".env.example").write_text("WEBUI_SECRET_KEY=\n")
        (self.root / "models" / "loras").mkdir(parents=True)
        self.pc = FakePC()
        self.app = home.App(system=self.pc, root=self.root, data=self.root / "data", ollama=self.url)
        self.addCleanup(self.app.hub.stop_all)
        self.app.providers.anthropic_base = self.url
        self.app.providers.openrouter_base = self.url + "/or"
        self.st = self.app.studio
        self.st.save_settings({"comfy_url": self.url, "models_dir": str(self.root / "models")})
        self.log = []

    def photos(self, n=3, folder="pics", data=PNG):
        d = self.root / folder
        d.mkdir(exist_ok=True)
        for i in range(n):
            (d / f"photo{i}.png").write_bytes(data + bytes([i]))
        return d

    def run_job(self, body):
        job = self.app.create(body)
        self.app.drain()
        return job


class WorkflowTest(Base):
    def test_finds_the_right_boxes_by_following_the_wires(self):
        slots = comfy.find_slots(EDIT_WF)
        self.assertEqual((slots["prompt"], slots["negative"], slots["images"], slots["loras"]), ("4", "3", ["2"], ["5"]))
        out = comfy.patch(EDIT_WF, prompt="a red car", image="mine.png", seed=7, lora="style.safetensors", lora_strength=0.6)
        self.assertEqual(out["4"]["inputs"]["text"], "a red car")
        self.assertEqual(out["3"]["inputs"]["text"], "blurry, ugly")  # the negative prompt is left alone
        self.assertEqual(out["2"]["inputs"]["image"], "mine.png")
        self.assertEqual(out["6"]["inputs"]["seed"], 7)
        self.assertEqual(out["5"]["inputs"], {**EDIT_WF["5"]["inputs"], "lora_name": "style.safetensors", "strength_model": 0.6, "strength_clip": 0.6})
        self.assertEqual(EDIT_WF["4"]["inputs"]["text"], "old prompt")  # the saved workflow is never modified
        self.assertNotEqual(comfy.patch(EDIT_WF)["6"]["inputs"]["seed"], 5)  # a fresh seed each run by default

    def test_music_workflow_takes_style_lyrics_and_length(self):
        out = comfy.patch(MUSIC_WF, prompt="lofi piano", lyrics="la la", seconds=45)
        self.assertEqual(out["1"]["inputs"], {"tags": "lofi piano", "lyrics": "la la", "clip": ["9", 0]})
        self.assertEqual(out["3"]["inputs"]["seconds"], 45)

    def test_wrong_files_are_refused_with_what_to_do(self):
        for text, expect in (('{"nodes": [], "links": []}', "Export (API)"), ("not json", "Export (API)"), ('{"a": 1}', "Export (API)")):
            with self.assertRaises(studio.StudioError) as e:
                self.st.save_workflow("edit", text)
            self.assertIn(expect, str(e.exception))
        with self.assertRaises(studio.StudioError) as e:
            self.st.save_workflow("edit", json.dumps(IMAGE_WF))  # a text-to-image workflow can't edit photos
        self.assertIn("no Load Image box", str(e.exception))
        self.assertEqual(self.st.save_workflow("edit", json.dumps(EDIT_WF)), {"lora": True, "seconds": False, "lyrics": False})
        with self.assertRaises(comfy.ComfyError) as e:
            comfy.patch(IMAGE_WF, lora="x.safetensors")
        self.assertIn("Load LoRA", str(e.exception))

    def test_job_without_a_saved_workflow_explains_the_setup(self):
        job = self.run_job({"kind": "image", "prompt": "a cat"})
        self.assertEqual(job.status, "failed")
        self.assertIn("Export (API)", job.lines[-1])


class CreateTest(Base):
    def test_make_an_image(self):
        self.st.save_workflow("image", json.dumps(IMAGE_WF))
        job = self.run_job({"kind": "image", "prompt": "A Cat, in a hat!"})
        self.assertEqual(job.status, "done")
        files = list((self.root / "outputs" / "images").iterdir())
        self.assertEqual(len(files), 1)  # the temp preview ComfyUI also reported is not saved
        self.assertRegex(files[0].name, r"^\d{8}-\d{6} a-cat-in-a-hat\.png$")
        self.assertIn(b'"text": "A Cat, in a hat!"', files[0].read_bytes())
        self.assertEqual(self.app.state()["recent"]["images"], [files[0].name])

    def test_bulk_edit_keeps_originals_and_survives_one_bad_photo(self):
        self.st.save_workflow("edit", json.dumps(EDIT_WF))
        d = self.photos(3)
        (d / "notes.txt").write_text("not a photo")
        (d / "sub").mkdir()
        (d / "sub" / "deep.png").write_bytes(PNG)
        before = {p.name: p.read_bytes() for p in d.glob("*.png")}
        Fake.fail_images = {"photo1"}
        job = self.run_job({"kind": "bulk", "folder": str(d), "prompt": "make it a watercolor"})
        self.assertEqual(job.status, "done")
        self.assertEqual({p.name: p.read_bytes() for p in d.glob("*.png")}, before)  # originals untouched
        out = next(p for p in d.iterdir() if p.is_dir() and p.name.startswith("AI edits"))
        self.assertEqual(sorted(p.name for p in out.glob("*.png")), ["photo0.png", "photo2.png"])
        self.assertEqual(len(Fake.uploads), 3)  # only the three photos: not the text file or the subfolder
        self.assertIn("CUDA out of memory", " ".join(job.lines))
        self.assertIn("2 edited, 1 failed", job.lines[-1])
        note = (out / "what was done.txt").read_text()
        self.assertIn("make it a watercolor", note)
        self.assertIn("photo1.png", note)
        self.assertTrue(all(b'"text": "make it a watercolor"' in p.read_bytes() for p in out.glob("*.png")))

    def test_bulk_edit_stops_early_when_nothing_works_and_refuses_bad_input(self):
        self.st.save_workflow("edit", json.dumps(EDIT_WF))
        d = self.photos(6)
        Fake.fail_images = {"photo"}
        job = self.run_job({"kind": "bulk", "folder": str(d), "prompt": "x"})
        self.assertEqual(job.status, "failed")
        self.assertEqual(len(Fake.uploads), 2)  # gave up after two, not six
        for body in ({"folder": str(d), "prompt": " "}, {"folder": str(self.root / "nope"), "prompt": "x"},
                     {"folder": str(self.root / "models"), "prompt": "x"}):
            self.assertEqual(self.run_job({"kind": "bulk", **body}).status, "failed")

    def test_a_missing_lora_is_explained(self):
        self.st.save_workflow("edit", json.dumps(EDIT_WF))
        job = self.run_job({"kind": "bulk", "folder": str(self.photos(2)), "prompt": "x", "lora": "missing.safetensors"})
        self.assertIn("is not on this PC", " ".join(job.lines))

    def test_music_and_comfyui_being_closed(self):
        self.st.save_workflow("music", json.dumps(MUSIC_WF))
        job = self.run_job({"kind": "music", "style": "lofi piano", "lyrics": "", "seconds": 9999})
        self.assertEqual(job.status, "done")
        song = next((self.root / "outputs" / "music").iterdir())
        self.assertEqual(song.suffix, ".flac")
        sent = json.loads(song.read_bytes()[7:])
        self.assertEqual((sent["1"]["inputs"]["tags"], sent["1"]["inputs"]["lyrics"], sent["3"]["inputs"]["seconds"]),
                         ("lofi piano", "[instrumental]", 600))  # no lyrics means instrumental; length is capped
        self.st.save_settings({"comfy_url": "http://127.0.0.1:9"})
        job = self.run_job({"kind": "music", "style": "x"})
        self.assertEqual(job.status, "failed")
        self.assertIn("Is ComfyUI open?", job.lines[-1])


class CharacterTest(Base):
    def test_needs_consent_and_enough_photos(self):
        d = self.photos(10)
        self.assertIn("Tick the box", self.run_job({"kind": "character", "name": "Me", "folder": str(d)}).lines[-1])
        self.assertIn("Tick the box", self.run_job({"kind": "character", "name": "Me", "folder": str(d), "consent": "yes"}).lines[-1])
        few = self.photos(5, "few")
        job = self.run_job({"kind": "character", "name": "Me", "folder": str(few), "consent": True})
        self.assertEqual(job.status, "failed")
        self.assertIn("at least 8", job.lines[-1])
        self.assertFalse((self.root / "characters").exists())

    def test_builds_a_captioned_dataset(self):
        d = self.photos(10, data=SMALL_PNG)
        (d / "copy.png").write_bytes((d / "photo0.png").read_bytes())  # an exact duplicate
        job = self.run_job({"kind": "character", "name": "Aunt May", "folder": str(d), "consent": True})
        self.assertEqual(job.status, "done")
        ds = self.root / "characters" / "aunt-may" / "dataset"
        self.assertEqual(len(list(ds.glob("*.png"))), 10)  # the duplicate was dropped
        captions = [p.read_text() for p in sorted(ds.glob("*.txt"))]
        self.assertEqual(len(captions), 10)
        self.assertTrue(all(c.startswith("a photo of auntmaychr, a photo of someone standing") for c in captions))
        log = " ".join(job.lines)
        self.assertIn("Skipped 1 exact duplicate", log)
        self.assertIn("under 768 pixels", log)
        self.assertIn("Only 10 photos", log)
        self.assertIn("auntmaychr", (self.root / "characters" / "aunt-may" / "NEXT STEPS.txt").read_text())
        self.assertEqual(self.app.state()["characters"][0]["trigger"], "auntmaychr")
        asked = [s for s in Fake.sent if s["path"] == "/api/chat"]
        self.assertEqual(asked[0]["body"]["model"], "gemma4:12b")  # the vision-capable model was picked automatically
        self.assertIn("do not guess who they are", asked[0]["body"]["messages"][0]["content"])


class CadTest(Base):
    def setUp(self):
        super().setUp()
        patcher = unittest.mock.patch.object(studio.Studio, "openscad", lambda s: "openscad")
        patcher.start()
        self.addCleanup(patcher.stop)

        def run(args, timeout=120, cwd=None, real=self.pc.run):
            if args[0] != "openscad":
                return real(args, timeout, cwd)
            code = Path(args[-1]).read_text()
            if "BAD" in code:
                return 1, "ERROR: Parser error: syntax error in file model.scad, line 3\nCan't parse file"
            Path(args[2]).write_bytes(b"solid model" + b"\x00" * 200)
            return 0, ""
        self.pc.run = run

    def test_a_failed_design_is_sent_back_with_the_error_and_fixed(self):
        Fake.cad_answers = ["```openscad\ncube(BAD;\n```", "Here you go:\n```openscad\nwidth = 60; // mm\ncube([width, 20, 5]);\n```"]
        job = self.run_job({"kind": "cad", "description": "a 60 mm wide plate"})
        self.assertEqual(job.status, "done")
        folder = next((self.root / "outputs" / "3d").iterdir())
        self.assertEqual((folder / "model.scad").read_text(), "width = 60; // mm\ncube([width, 20, 5]);\n")
        self.assertTrue((folder / "model.stl").exists())
        second = [s for s in Fake.sent if s["path"] == "/api/chat"][1]["body"]["messages"][1]["content"]
        self.assertIn("Parser error", second)   # the model was shown OpenSCAD's complaint
        self.assertIn("cube(BAD;", second)      # and its own previous attempt
        self.assertEqual(self.app.state()["recent3d"][0]["name"], folder.name)

    def test_code_that_reads_other_files_is_never_run_and_giving_up_is_reported(self):
        Fake.cad_answers = ['```openscad\nimport("C:/secret.stl");\n```'] * 3
        job = self.run_job({"kind": "cad", "description": "a thing"})
        self.assertEqual(job.status, "failed")
        self.assertIn("couldn't produce a working design in 3 attempts", job.lines[-1])
        self.assertFalse(any((self.root / "outputs" / "3d").rglob("model.scad")))


class LoraTest(Base):
    def test_download_list_delete(self):
        models = self.root / "models"
        opener = lambda req, timeout=60: urllib.request.urlopen(self.url + "/lora/ok.safetensors")  # noqa: E731
        name = comfy.download_lora(models, "https://huggingface.co/a/b/blob/main/ok.safetensors", self.log.append, opener=opener, chunk=1000)
        self.assertEqual(name, "ok.safetensors")
        self.assertEqual(self.app.state()["loras"], [{"name": "ok.safetensors", "mb": 0}])
        self.assertFalse(list((models / "loras").glob("*.part")))
        self.app.lora("delete", "ok.safetensors")
        self.assertEqual(self.app.state()["loras"], [])

    def test_unsafe_downloads_and_names_are_refused(self):
        self.assertEqual(comfy.lora_url("https://huggingface.co/a/b/blob/main/x.safetensors"), "https://huggingface.co/a/b/resolve/main/x.safetensors")
        for url in ("http://huggingface.co/a/x.safetensors", "https://evil.example/x.safetensors", "file:///c:/x.safetensors",
                    "https://huggingface.co.evil.example/x.safetensors"):
            with self.assertRaises(comfy.ComfyError, msg=url):
                self.app.lora("download", url)
        # a file that isn't .safetensors could carry program code: never saved
        opener = lambda req, timeout=60: urllib.request.urlopen(self.url + "/api/tags")  # noqa: E731
        with self.assertRaises(comfy.ComfyError) as e:
            comfy.download_lora(self.root / "models", "https://civitai.com/api/download/models/1", self.log.append, opener=opener)
        self.assertIn("not a .safetensors file", str(e.exception))
        self.assertEqual(list((self.root / "models" / "loras").iterdir()), [])
        for name in ("../../boot.ini", "x.ckpt", "a/b.safetensors", ""):
            with self.assertRaises(comfy.ComfyError, msg=name):
                self.app.lora("delete", name)


class CloudTest(Base):
    def test_keys_are_stored_but_never_shown(self):
        self.app.set_key("openrouter", "sk-or-SECRETSECRET1234")
        self.assertEqual(self.app.keys.get("openrouter"), "sk-or-SECRETSECRET1234")
        state = json.dumps(self.app.state())
        self.assertNotIn("SECRETSECRET", state)
        self.assertIn({"id": "openrouter", "name": "OpenRouter", "set": True, "tail": "1234"}, self.app.state()["keys"])
        self.app.set_key("openrouter", "")
        self.assertIsNone(self.app.keys.get("openrouter"))
        with self.assertRaises(providers.ModelError):
            self.app.set_key("aws", "x")

    def test_openrouter(self):
        with self.assertRaises(providers.ModelError) as e:
            self.app.providers.chat("openrouter:google/gemini-pro", "hi")
        self.assertIn("No OpenRouter key", str(e.exception))
        self.app.set_key("openrouter", "sk-or-1")
        self.assertEqual(self.app.providers.chat("openrouter:google/gemini-pro", "hi"), "Hello from OpenRouter")
        sent = Fake.sent[-1]
        self.assertEqual((sent["headers"]["authorization"], sent["body"]["model"]), ("Bearer sk-or-1", "google/gemini-pro"))
        with self.assertRaises(providers.ModelError) as e:
            self.app.providers.chat("openrouter:broke/model", "hi")
        self.assertIn("out of credit", str(e.exception))
        self.assertEqual(self.app.providers.openrouter_models("gemini"), [{"id": "google/gemini-pro", "name": "Gemini Pro"}])
        self.app.set_cloud_model("add", "openrouter:google/gemini-pro")
        self.assertIn("openrouter:google/gemini-pro", self.app.state()["cloud"])
        with self.assertRaises(ValueError):
            self.app.set_cloud_model("add", "gemma4:12b")

    @unittest.skipUnless(HAVE_ANTHROPIC, "pip install anthropic to run the Claude tests")
    def test_claude_request_is_built_the_documented_way(self):
        self.app.set_key("anthropic", "sk-ant-test")
        pic = self.root / "p.png"
        pic.write_bytes(PNG)
        self.assertEqual(self.app.providers.chat("claude:claude-opus-5-5", "What is this?", images=[pic]), "Hello from Claude")
        sent = Fake.sent[-1]
        body = sent["body"]
        self.assertEqual((body["model"], body["max_tokens"], body["thinking"]), ("claude-opus-5-5", 16000, {"type": "adaptive"}))
        self.assertEqual(body["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", sent["headers"]["anthropic-beta"])
        self.assertEqual(sent["headers"]["authorization"], "Bearer sk-ant-test")
        self.assertEqual([b["type"] for b in body["messages"][0]["content"]], ["image", "text"])
        self.assertEqual(body["messages"][0]["content"][0]["source"]["media_type"], "image/png")
        self.app.providers.chat("claude:claude-haiku-5-5", "hi")  # this model has no fallback: plain request
        self.assertNotIn("fallbacks", Fake.sent[-1]["body"])
        self.assertEqual(self.app.providers.chat("claude:", "hi"), "Hello from Claude")
        self.assertEqual(Fake.sent[-1]["body"]["model"], "claude-opus-5-5")  # the default model
        self.assertEqual(self.app.providers.claude_models(), ["claude-opus-5-5"])

    @unittest.skipUnless(HAVE_ANTHROPIC, "pip install anthropic to run the Claude tests")
    def test_claude_problems_become_plain_messages(self):
        with self.assertRaises(providers.ModelError) as e:
            self.app.providers.chat("claude:claude-opus-5-5", "hi")
        self.assertIn("No Claude API key", str(e.exception))
        self.app.set_key("anthropic", "sk-ant-test")
        for mode, expect in (("badkey", "rejected the API key"), ("refusal", "declined")):
            Fake.claude_mode = mode
            with self.assertRaises(providers.ModelError) as e:
                self.app.providers.chat("claude:claude-opus-5-5", "hi")
            self.assertIn(expect, str(e.exception))

    def test_scheduled_job_can_use_a_cloud_model(self):
        self.app.set_key("openrouter", "sk-or-1")
        s = self.app.schedule_save({"name": "Cloud", "kind": "prompt", "model": "openrouter:google/gemini-pro",
                                    "prompt": "hi", "when_input": "daily at 5am"})
        self.app.schedule_change(s["id"], "run")
        self.app.drain()
        self.assertEqual(self.app.output(s["id"], self.app.state()["schedules"][0]["runs"][0]), "Hello from OpenRouter")


class AgentToolsTest(Base):
    def test_agents_get_the_tools_and_only_the_shared_folder(self):
        names = [t["name"] for t in self.app.hub.list_tools()]
        self.assertEqual(names, ["look_at_image", "generate_image", "edit_image", "list_loras", "make_3d_model", "make_music"])
        (self.root / "apps" / "site").mkdir(parents=True)
        (self.root / "apps" / "site" / "hero.png").write_bytes(PNG)
        seen = self.app.hub.call("look_at_image", {"path": "/projects/site/hero.png", "question": "What is it?"})
        self.assertEqual((seen["isError"], seen["content"][0]["text"]), (False, "A photo of someone standing in a kitchen, seen from the side."))
        # A real image that is OUTSIDE the shared folder: an agent must not be able to reach it.
        (self.root / "private").mkdir()
        (self.root / "private" / "passport.png").write_bytes(PNG)
        asked = len(Fake.sent)
        for path in ("../private/passport.png", "/projects/../private/passport.png", "site/../../private/passport.png",
                     str(self.root / "private" / "passport.png")):
            out = self.app.hub.call("look_at_image", {"path": path})
            self.assertTrue(out["isError"], path)
            self.assertRegex(out["content"][0]["text"], "only use files inside the shared apps folder|There is no image at", path)
        self.assertEqual(len(Fake.sent), asked)  # the outside image was never sent to any model

    def test_generate_image_tool_hands_the_file_to_the_agent(self):
        self.st.save_workflow("image", json.dumps(IMAGE_WF))
        out = self.app.hub.call("generate_image", {"prompt": "a logo"})
        self.assertFalse(out["isError"])
        self.assertRegex(out["content"][0]["text"], r"Saved: /projects/generated/\d{8}-\d{6} a-logo\.png")
        self.assertEqual(len(list((self.root / "apps" / "generated").iterdir())), 1)
        out = self.app.hub.call("edit_image", {"path": "nope.png", "prompt": "x"})
        self.assertTrue(out["isError"])  # a clear failure the model can read, not a crash


class WebTest(Base):
    def setUp(self):
        super().setUp()
        self.web = home.serve(self.app, 0)
        threading.Thread(target=self.web.serve_forever, daemon=True).start()
        self.addCleanup(self.web.server_close)
        self.addCleanup(self.web.shutdown)
        self.base = f"http://127.0.0.1:{self.web.server_port}"

    def call(self, path, body=None, token=True):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **({"X-Token": self.app.token} if token else {})})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_new_buttons_work_and_need_the_page_secret(self):
        for path, body in (("/api/key", {"id": "openrouter", "value": "x"}), ("/api/create", {"kind": "image", "prompt": "x"}),
                           ("/api/plugin", {"name": "P", "command": "x"}), ("/api/lora", {"action": "delete", "value": "a.safetensors"}),
                           ("/api/workflow", {"role": "edit", "text": "{}"}), ("/api/settings", {})):
            self.assertEqual(self.call(path, body, token=False)[0], 403, path)
        self.assertEqual(self.app.hub.plugins, [])
        self.assertEqual(self.call("/api/workflow", {"role": "image", "text": json.dumps(IMAGE_WF)})[0], 200)
        code, raw = self.call("/api/workflow", {"role": "image", "text": '{"nodes": []}'})
        self.assertEqual(code, 400)
        self.assertIn("Export (API)", json.loads(raw)["error"])
        self.assertEqual(self.call("/api/create", {"kind": "image", "prompt": "a dog"})[0], 200)
        self.assertEqual(self.call("/api/create", {"kind": "delete-everything"})[0], 400)
        self.app.drain()
        name = self.app.state()["recent"]["images"][0]
        code, raw = self.call("/out/images/" + urllib.request.quote(name), token=False)
        self.assertEqual(code, 200)
        self.assertTrue(raw.startswith(b"RESULT"))
        self.assertEqual(self.call("/api/plugin", {"name": "Web reader", "command": "uvx mcp-server-fetch"})[0], 200)
        self.assertEqual(self.call("/api/plugin/change", {"id": "web_reader", "action": "remove"})[0], 200)

    def test_only_results_are_served_from_the_outputs_folder(self):
        (self.root / "outputs" / "images").mkdir(parents=True)
        (self.root / "outputs" / "images" / "notes.txt").write_text("x")
        (self.root / "data" / "keys.json").write_text('{"anthropic": "sk-secret"}')
        for path in ("/out/images/notes.txt", "/out/images/..%2F..%2Fdata%2Fkeys.json", "/out/images/../../data/keys.json",
                     "/out/3d/..%2F..%2Fdata/model.stl", "/out/secrets/x.png"):
            code, raw = self.call(path, token=False)
            self.assertIn(code, (403, 404), path)
            self.assertNotIn(b"sk-secret", raw)


if __name__ == "__main__":
    import unittest.mock  # noqa: F401
    unittest.main()
