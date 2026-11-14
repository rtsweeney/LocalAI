"""Driving ComfyUI from code: run a saved workflow with your own prompt, photo or LoRA.

ComfyUI describes each job as a "workflow": a set of numbered boxes ("nodes") wired together.
You build and test a workflow once inside ComfyUI, export it, and this module can then run it
again and again, swapping in a new prompt, a new input photo, a new seed or a LoRA each time.

Uses only Python's standard library.
"""
import copy
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

TEXT_KEYS = ("text", "prompt", "tags", "string")
IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
# What each kind of job must be able to set in its workflow.
ROLES = {
    "image": {"title": "Make an image from text", "needs": ["prompt"],
              "how": "an image template such as Z-Image Turbo or FLUX.2 klein text-to-image"},
    "edit": {"title": "Edit a photo with a prompt", "needs": ["prompt", "image"],
             "how": "an image-edit template such as FLUX.2 klein Image Edit or Qwen-Image-Edit"},
    "video": {"title": "Turn an image into a video", "needs": ["prompt", "image"],
              "how": "an image-to-video template such as Wan 2.2 or LTX"},
    "music": {"title": "Make music", "needs": ["prompt"],
              "how": "an audio template such as ACE-Step 1.5 text-to-music"},
}


class ComfyError(Exception):
    """A problem worth showing the user as-is."""


def check_format(wf):
    if isinstance(wf, dict) and isinstance(wf.get("nodes"), list):
        raise ComfyError("This is ComfyUI's normal save format, which can't be run from outside. "
                         "In ComfyUI choose Workflow > Export (API) and use that file instead.")
    if not isinstance(wf, dict) or not wf or not all(
            isinstance(n, dict) and "class_type" in n and isinstance(n.get("inputs"), dict) for n in wf.values()):
        raise ComfyError("This isn't a ComfyUI workflow. In ComfyUI choose Workflow > Export (API).")


def is_link(v):
    return isinstance(v, list) and len(v) == 2 and isinstance(v[0], (str, int)) and isinstance(v[1], int)


def text_field(node):
    for k in TEXT_KEYS:
        if isinstance(node["inputs"].get(k), str):
            return k
    return None


def upstream_text(wf, start, seen=None):
    """Follow the wires backwards from a node until reaching a box that holds prompt text."""
    seen = seen if seen is not None else set()
    node = wf.get(str(start))
    if node is None or str(start) in seen:
        return None
    seen.add(str(start))
    if text_field(node):
        return str(start)
    for v in node["inputs"].values():
        if is_link(v):
            found = upstream_text(wf, v[0], seen)
            if found:
                return found
    return None


def find_slots(wf):
    """Work out which boxes hold the prompt, the negative prompt, the input image and so on."""
    check_format(wf)
    ids = sorted(wf, key=lambda k: (not str(k).isdigit(), int(k) if str(k).isdigit() else 0, str(k)))
    slots = {"prompt": None, "negative": None, "images": [], "seeds": [], "loras": [],
             "seconds": [], "lyrics": []}
    for nid in ids:
        ins = wf[nid]["inputs"]
        # The sampler has two wires, "positive" (what you want) and "negative" (what to avoid).
        if is_link(ins.get("positive")) and not slots["prompt"]:
            slots["prompt"] = upstream_text(wf, ins["positive"][0])
        if is_link(ins.get("negative")) and not slots["negative"]:
            slots["negative"] = upstream_text(wf, ins["negative"][0])
        if wf[nid]["class_type"] == "LoadImage":
            slots["images"].append(nid)
        if wf[nid]["class_type"].startswith("LoraLoader") and "lora_name" in ins:
            slots["loras"].append(nid)
        for key in ("seed", "noise_seed"):
            if isinstance(ins.get(key), int) and not isinstance(ins.get(key), bool):
                slots["seeds"].append((nid, key))
        for key in ("seconds", "duration"):
            if isinstance(ins.get(key), (int, float)) and not isinstance(ins.get(key), bool):
                slots["seconds"].append((nid, key))
        if isinstance(ins.get("lyrics"), str):
            slots["lyrics"].append(nid)
    if slots["negative"] == slots["prompt"]:
        slots["negative"] = None
    if not slots["prompt"]:  # no sampler wiring to follow: fine if there is only one text box
        texts = [n for n in ids if text_field(wf[n])]
        if len(texts) == 1:
            slots["prompt"] = texts[0]
    return slots


def check_role(wf, role):
    """Make sure a workflow can do the job it is being saved for. Returns its slots."""
    slots = find_slots(wf)
    r = ROLES[role]
    if "prompt" in r["needs"] and not slots["prompt"]:
        raise ComfyError("I can't tell which box in this workflow holds the prompt. "
                         f"Start from {r['how']} and export it without rearranging the text boxes.")
    if "image" in r["needs"] and not slots["images"]:
        raise ComfyError(f"This workflow has no Load Image box, so it can't take a photo. Start from {r['how']}.")
    return slots


def patch(wf, prompt=None, negative=None, image=None, seed=None, lora=None, lora_strength=None,
          seconds=None, lyrics=None):
    """Return a copy of the workflow with your values written into the right boxes."""
    slots, wf = find_slots(wf), copy.deepcopy(wf)
    if prompt is not None:
        if not slots["prompt"]:
            raise ComfyError("I can't tell which box in this workflow holds the prompt.")
        wf[slots["prompt"]]["inputs"][text_field(wf[slots["prompt"]])] = prompt
    if negative is not None and slots["negative"]:
        wf[slots["negative"]]["inputs"][text_field(wf[slots["negative"]])] = negative
    if image is not None:
        if not slots["images"]:
            raise ComfyError("This workflow has no Load Image box, so it can't take a photo.")
        wf[slots["images"][0]]["inputs"]["image"] = image
    for nid, key in slots["seeds"]:
        wf[nid]["inputs"][key] = random.randrange(2 ** 48) if seed is None else seed
    if lora:
        if not slots["loras"]:
            raise ComfyError("This workflow has no Load LoRA box. In ComfyUI, add a \"Load LoRA\" node between "
                             "the model loader and the sampler, run it once, and export it again.")
        ins = wf[slots["loras"][0]]["inputs"]
        ins["lora_name"] = lora
        if lora_strength is not None:
            for key in ("strength_model", "strength_clip"):
                if key in ins:
                    ins[key] = lora_strength
    if seconds is not None:
        for nid, key in slots["seconds"]:
            wf[nid]["inputs"][key] = seconds
    if lyrics is not None:
        for nid in slots["lyrics"]:
            wf[nid]["inputs"]["lyrics"] = lyrics
    return wf


class Comfy:
    def __init__(self, base="http://127.0.0.1:8000"):
        self.base = base.rstrip("/")
        self.client = uuid.uuid4().hex

    def call(self, path, data=None, headers=None, timeout=60):
        req = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            raise ComfyError(f"ComfyUI refused the job: {explain(body) or e}") from None
        except (urllib.error.URLError, OSError) as e:
            raise ComfyError(f"Could not reach ComfyUI at {self.base} ({getattr(e, 'reason', e)}). Is ComfyUI "
                             f"open? If its address is different, change it under Create > Setup.") from None

    def alive(self):
        try:
            self.call("/system_stats", timeout=4)
            return True
        except ComfyError:
            return False

    def upload(self, path):
        """Send a photo to ComfyUI's input folder. Returns the name ComfyUI knows it by."""
        path = Path(path)
        boundary = uuid.uuid4().hex
        kind = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        safe = re.sub(r"[^\w.\-]", "_", path.name)
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="aihome_{safe}"\r\n'
                f"Content-Type: {kind}\r\n\r\n").encode() + path.read_bytes() + (
            f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n--{boundary}--\r\n').encode()
        got = json.loads(self.call("/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}))
        return (got.get("subfolder") + "/" if got.get("subfolder") else "") + got["name"]

    def run(self, wf, timeout=3600, on_wait=None):
        """Queue a workflow, wait for it, and return its results as [(file name, bytes)]."""
        got = json.loads(self.call("/prompt", json.dumps({"prompt": wf, "client_id": self.client}).encode(),
                                   {"Content-Type": "application/json"}))
        pid = got.get("prompt_id")
        if not pid:
            raise ComfyError("ComfyUI did not accept the job: " + (explain(json.dumps(got)) or "no reason given"))
        deadline, waited = time.time() + timeout, 0
        while True:
            entry = json.loads(self.call("/history/" + pid)).get(pid)
            if entry:
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise ComfyError("ComfyUI hit an error while running it: " + (run_error(status) or "see ComfyUI's window"))
                if entry.get("outputs") or status.get("completed"):
                    break
            if time.time() > deadline:
                raise ComfyError(f"ComfyUI was still working after {timeout // 60} minutes, so I stopped waiting.")
            time.sleep(min(2.0, 0.25 * (waited + 1)))
            waited += 1
            if on_wait:
                on_wait(waited)
        files = []
        for out in entry.get("outputs", {}).values():
            for group in out.values():
                for f in group if isinstance(group, list) else []:
                    if isinstance(f, dict) and f.get("filename") and f.get("type", "output") != "temp":
                        q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f.get("subfolder", ""),
                                                    "type": f.get("type", "output")})
                        files.append((f["filename"], self.call("/view?" + q, timeout=300)))
        if not files:
            raise ComfyError("The workflow finished but saved nothing. Make sure it ends in a Save box "
                             "(Save Image, Save Video or Save Audio).")
        return files


def explain(body):
    """Turn ComfyUI's error JSON into one readable sentence."""
    try:
        data = json.loads(body)
    except ValueError:
        return body.strip()[:300]
    parts = []
    err = data.get("error")
    if isinstance(err, dict):
        parts.append(str(err.get("message", "")))
    elif err:
        parts.append(str(err))
    for nid, info in (data.get("node_errors") or {}).items():
        for e in info.get("errors", []):
            parts.append(f"{info.get('class_type', 'box ' + str(nid))}: {e.get('message', '')} {e.get('details', '')}".strip())
    text = "; ".join(p for p in parts if p)
    if "not in" in text and ("lora" in text.lower() or "ckpt" in text.lower() or "unet" in text.lower()):
        text += " (a model file this workflow names is not on this PC: open the workflow in ComfyUI and download it)"
    return text[:600]


def run_error(status):
    for msg in status.get("messages", []):
        if isinstance(msg, list) and len(msg) == 2 and msg[0] == "execution_error":
            d = msg[1]
            return f"{d.get('node_type', 'a box')}: {d.get('exception_message', '').strip()}"[:500]
    return ""


# ---------------------------------------------------------------- LoRAs

# A LoRA is a small add-on file that teaches an image or video model one new thing: a person,
# a drawing style, an object. It sits in ComfyUI's models/loras folder.
LORA_HOSTS = ("huggingface.co", "civitai.com")


def lora_dir(models_dir):
    return Path(models_dir) / "loras"


def list_loras(models_dir):
    d = lora_dir(models_dir)
    if not d.is_dir():
        return []
    return [{"name": f.name, "mb": round(f.stat().st_size / 1e6)} for f in sorted(d.glob("*.safetensors"))]


def lora_path(models_dir, name):
    if not re.fullmatch(r"[\w.\- ()\[\]]+\.safetensors", name or ""):
        raise ComfyError("That isn't a LoRA file name. It should end in .safetensors.")
    return lora_dir(models_dir) / name


def lora_url(url):
    u = urllib.parse.urlparse(url.strip())
    host = (u.hostname or "").removeprefix("www.")
    if u.scheme != "https" or host not in LORA_HOSTS:
        raise ComfyError("Paste a download link from huggingface.co or civitai.com (it must start with https://).")
    if host == "huggingface.co":
        url = url.strip().replace("/blob/", "/resolve/")
    return url


def download_lora(models_dir, url, log, token=None, opener=None, chunk=1 << 20):
    """Download a LoRA into ComfyUI's loras folder. Only the safe .safetensors format is accepted:
    older formats (.ckpt, .pt) can carry hidden program code that runs when loaded."""
    url = lora_url(url)
    d = lora_dir(models_dir)
    if not Path(models_dir).is_dir():
        raise ComfyError(f"ComfyUI's models folder was not found at {models_dir}. Set it under Create > Setup.")
    d.mkdir(exist_ok=True)
    headers = {"User-Agent": "ai-home/1.0"}
    if token and "civitai.com" in url:
        headers["Authorization"] = "Bearer " + token
    try:
        r = (opener or urllib.request.urlopen)(urllib.request.Request(url, headers=headers), timeout=60)
    except urllib.error.HTTPError as e:
        hint = " Civitai needs you to be signed in for this file: add your Civitai key under Create > Setup." if e.code in (401, 403) and "civitai" in url else ""
        raise ComfyError(f"The site refused the download ({e.code}).{hint}") from None
    except (urllib.error.URLError, OSError) as e:
        raise ComfyError(f"Could not download it: {getattr(e, 'reason', e)}") from None
    with r:
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', r.headers.get("Content-Disposition") or "")
        name = urllib.parse.unquote(m.group(1)) if m else urllib.parse.unquote(urllib.parse.urlparse(r.geturl()).path.rsplit("/", 1)[-1])
        name = re.sub(r"[^\w.\- ()\[\]]", "_", name)
        if not name.lower().endswith(".safetensors"):
            raise ComfyError(f"That link points to \"{name}\", which is not a .safetensors file. For safety, only "
                             f".safetensors LoRAs are downloaded.")
        target, part = d / name, d / (name + ".part")
        total, done, shown = int(r.headers.get("Content-Length") or 0), 0, -1
        with open(part, "wb") as f:
            while True:
                block = r.read(chunk)
                if not block:
                    break
                f.write(block)
                done += len(block)
                pct = int(100 * done / total) // 10 * 10 if total else -1
                if pct != shown and total:
                    log(f"{pct}% of {total / 1e6:.0f} MB")
                    shown = pct
        part.replace(target)
    log(f"Saved {name}. In ComfyUI press R to refresh its list.")
    return name
