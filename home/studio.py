"""The creative jobs: images, bulk photo edits, video, music, characters and 3D models.

Images, video and music are made by ComfyUI, using workflows you exported from it (see comfy.py).
3D models are made by a language model writing OpenSCAD code, which OpenSCAD turns into a file
you can 3D print. Character datasets are prepared here and trained in a separate trainer.

Uses only Python's standard library.
"""
import datetime as dt
import hashlib
import json
import re
import shutil
import struct
from pathlib import Path

import comfy

DEFAULTS = {"comfy_url": "http://127.0.0.1:8000", "models_dir": "", "vision_model": "", "cad_model": "gpt-oss:20b"}
CAD_SYSTEM = """You write OpenSCAD code for 3D printing.
Rules:
- Answer with one ```openscad code block and nothing else.
- Units are millimetres. Put the key sizes in named variables at the top with a short comment each.
- The result must be one solid, printable object: parts must overlap slightly where they join, with no
  floating pieces and no zero-thickness walls.
- Set $fn = 64; for smooth curves.
- Use only built-in OpenSCAD. No include, use, import or surface, and no external libraries."""
CAPTION = ("Describe this photo in one plain sentence for training an image model. Cover the pose, the camera "
           "angle and distance, the clothing, the expression, the background and the lighting. Do not describe "
           "the person's face, hair, skin or body shape, and do not guess who they are or their name. "
           "Begin exactly with: a photo of {trigger}")


class StudioError(Exception):
    """A problem worth showing the user as-is."""


def slug(text, limit=40):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].rstrip("-") or "untitled"


def image_size(path):
    """Width and height of a PNG or JPEG, read from the file's header. None if it can't tell."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    marker = f.read(4)
                    if len(marker) < 4 or marker[0] != 0xFF:
                        return None
                    length = struct.unpack(">H", marker[2:4])[0]
                    if 0xC0 <= marker[1] <= 0xCF and marker[1] not in (0xC4, 0xC8, 0xCC):
                        h, w = struct.unpack(">HH", f.read(5)[1:5])
                        return w, h
                    f.seek(length - 2, 1)
    except (OSError, struct.error):
        pass
    return None


def photos_in(folder):
    folder = Path(folder)
    if not folder.is_dir():
        raise StudioError(f"There is no folder at {folder}. Paste the full path, like C:\\Users\\you\\Pictures\\Trip.")
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in comfy.IMAGE_TYPES)


class Studio:
    def __init__(self, root, data, providers, system):
        self.root, self.data, self.providers, self.sys = Path(root), Path(data), providers, system
        (self.data / "workflows").mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- settings and workflows

    def settings(self):
        try:
            saved = json.loads((self.data / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        s = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
        if not s["models_dir"]:
            guess = Path.home() / "Documents" / "ComfyUI" / "models"
            s["models_dir"] = str(guess) if guess.is_dir() else ""
        return s

    def save_settings(self, new):
        s = self.settings()
        for k in DEFAULTS:
            if k in new:
                s[k] = str(new[k]).strip()
        if not re.match(r"https?://[\w.\-]+(:\d+)?/?$", s["comfy_url"]):
            raise StudioError("ComfyUI's address looks like http://127.0.0.1:8000")
        if s["models_dir"] and not Path(s["models_dir"]).is_dir():
            raise StudioError(f"There is no folder at {s['models_dir']}.")
        (self.data / "settings.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
        return s

    def comfy(self):
        return comfy.Comfy(self.settings()["comfy_url"])

    def models_dir(self):
        d = self.settings()["models_dir"]
        if not d:
            raise StudioError("Tell AI Home where ComfyUI keeps its models: Create > Setup > ComfyUI models folder.")
        return d

    def save_workflow(self, role, text):
        if role not in comfy.ROLES:
            raise StudioError("Unknown kind of workflow.")
        try:
            wf = json.loads(text)
        except ValueError:
            raise StudioError("That file isn't a workflow. In ComfyUI choose Workflow > Export (API).") from None
        try:
            slots = comfy.check_role(wf, role)
        except comfy.ComfyError as e:
            raise StudioError(str(e)) from None
        (self.data / "workflows" / f"{role}.json").write_text(json.dumps(wf), encoding="utf-8")
        return {"lora": bool(slots["loras"]), "seconds": bool(slots["seconds"]), "lyrics": bool(slots["lyrics"])}

    def workflow(self, role):
        f = self.data / "workflows" / f"{role}.json"
        if not f.exists():
            r = comfy.ROLES[role]
            raise StudioError(f"No workflow saved for \"{r['title']}\" yet. In ComfyUI, open {r['how']}, run it "
                              f"once to check it works, choose Workflow > Export (API), and add that file under "
                              f"Create > Setup.")
        return json.loads(f.read_text(encoding="utf-8"))

    def workflows_view(self):
        out = []
        for role, r in comfy.ROLES.items():
            f = self.data / "workflows" / f"{role}.json"
            slots = comfy.find_slots(json.loads(f.read_text(encoding="utf-8"))) if f.exists() else None
            out.append({"role": role, "title": r["title"], "how": r["how"], "saved": bool(slots),
                        "lora": bool(slots and slots["loras"])})
        return out

    def out_dir(self, kind):
        d = self.root / "outputs" / kind
        d.mkdir(parents=True, exist_ok=True)
        return d

    def run(self, role, log, **values):
        try:
            wf = comfy.patch(self.workflow(role), **values)
            return self.comfy().run(wf, on_wait=lambda n: n % 30 == 0 and log("Still working..."))
        except comfy.ComfyError as e:
            raise StudioError(str(e)) from None

    def save_all(self, files, folder, stem):
        paths = []
        for i, (name, data) in enumerate(files):
            ext = Path(name).suffix.lower() or ".png"
            target = Path(folder) / (f"{stem}{'' if i == 0 else f'-{i + 1}'}{ext}")
            n = 2
            while target.exists():  # never overwrite an earlier result
                target = Path(folder) / f"{stem}-{n}{ext}"
                n += 1
            target.write_bytes(data)
            paths.append(target)
        return paths

    # ---------------------------------------------------------------- images, video, music

    def generate_image(self, log, prompt, lora=None, strength=None):
        if not prompt.strip():
            raise StudioError("Describe the image you want.")
        log("Asking ComfyUI for an image")
        files = self.run("image", log, prompt=prompt, lora=lora or None, lora_strength=strength)
        paths = self.save_all(files, self.out_dir("images"), f"{dt.datetime.now():%Y%m%d-%H%M%S} {slug(prompt, 30)}")
        log("Saved " + ", ".join(str(p) for p in paths))
        return paths

    def edit_image(self, log, image, prompt, folder=None, lora=None, strength=None):
        image = Path(image)
        if not image.is_file():
            raise StudioError(f"There is no photo at {image}.")
        try:
            uploaded = self.comfy().upload(image)
        except comfy.ComfyError as e:
            raise StudioError(str(e)) from None
        files = self.run("edit", log, prompt=prompt, image=uploaded, lora=lora or None, lora_strength=strength)
        return self.save_all(files[:1], folder or self.out_dir("edits"), image.stem)[0]

    def bulk_edit(self, log, folder, prompt, lora=None, strength=None):
        """Apply one instruction to every photo in a folder. Originals are never changed:
        results go into a new folder beside them."""
        if not prompt.strip():
            raise StudioError("Say what to change, like: make it look like a watercolor painting.")
        photos = photos_in(folder)
        if not photos:
            raise StudioError(f"No photos found in {folder} (looked for .jpg, .png and .webp files).")
        self.workflow("edit")  # fail now, with setup instructions, if there's no workflow
        if not self.comfy().alive():
            raise StudioError(f"ComfyUI isn't answering at {self.settings()['comfy_url']}. Open ComfyUI first.")
        out = Path(folder) / f"AI edits {dt.datetime.now():%Y-%m-%d %H%M}"
        out.mkdir(exist_ok=True)
        log(f"Editing {len(photos)} photos. Originals stay untouched; results go to:\n{out}")
        done, failed = 0, []
        for i, photo in enumerate(photos, 1):
            try:
                self.edit_image(log, photo, prompt, out, lora, strength)
                done += 1
                log(f"[{i}/{len(photos)}] {photo.name}: done")
            except StudioError as e:
                failed.append(photo.name)
                log(f"[{i}/{len(photos)}] {photo.name}: FAILED: {e}")
                if done == 0 and i >= 2:  # nothing is working: stop instead of failing a thousand times
                    log("The first photos all failed, so I stopped. Fix the problem above and try again.")
                    break
        (out / "what was done.txt").write_text(
            f"Instruction: {prompt}\nLoRA: {lora or 'none'}\nEdited: {done}\nFailed: {', '.join(failed) or 'none'}\n", encoding="utf-8")
        log(f"Finished: {done} edited, {len(failed)} failed.")
        if done == 0:
            raise StudioError("No photos could be edited.")
        return out

    def make_video(self, log, image, prompt):
        image = Path(image)
        if not image.is_file():
            raise StudioError(f"There is no image at {image}.")
        log("Asking ComfyUI for a video. This can take many minutes.")
        try:
            uploaded = self.comfy().upload(image)
        except comfy.ComfyError as e:
            raise StudioError(str(e)) from None
        files = self.run("video", log, prompt=prompt, image=uploaded)
        paths = self.save_all(files, self.out_dir("video"), f"{dt.datetime.now():%Y%m%d-%H%M%S} {slug(prompt, 30)}")
        log("Saved " + ", ".join(str(p) for p in paths))
        return paths

    def make_music(self, log, style, lyrics="", seconds=60):
        if not style.strip():
            raise StudioError("Describe the style, like: upbeat acoustic folk, female vocals, 110 bpm.")
        seconds = max(5, min(int(seconds or 60), 600))
        log(f"Asking ComfyUI for {seconds} seconds of music")
        files = self.run("music", log, prompt=style, lyrics=lyrics if lyrics.strip() else "[instrumental]", seconds=seconds)
        paths = self.save_all(files, self.out_dir("music"), f"{dt.datetime.now():%Y%m%d-%H%M%S} {slug(style, 30)}")
        log("Saved " + ", ".join(str(p) for p in paths))
        return paths

    # ---------------------------------------------------------------- vision

    def vision_model(self):
        chosen = self.settings()["vision_model"]
        if chosen:
            return chosen
        local = self.providers.vision_models()
        if not local:
            raise StudioError("No model that can see images is available. On the Models tab download gemma4:12b, "
                              "or pick a cloud model under Create > Setup > Vision model.")
        return local[0]

    def look(self, image, question="Describe this image."):
        image = Path(image)
        if not image.is_file() or image.suffix.lower() not in comfy.IMAGE_TYPES:
            raise StudioError(f"There is no image at {image}.")
        return self.providers.chat(self.vision_model(), question, images=[image])

    # ---------------------------------------------------------------- characters

    def character_prepare(self, log, name, folder, trigger="", consent=False):
        """Turn a folder of photos of one person into a training set for a character LoRA."""
        if not consent:
            raise StudioError("Only build a character from photos of yourself, or of someone who has agreed to it. "
                              "Tick the box to confirm.")
        if not name.strip():
            raise StudioError("Give the character a name.")
        photos = photos_in(folder)
        seen, unique = set(), []
        for p in photos:
            digest = hashlib.sha1(p.read_bytes()).hexdigest()
            if digest not in seen:
                seen.add(digest)
                unique.append(p)
        if len(unique) < 8:
            raise StudioError(f"Found {len(unique)} different photos. A character needs at least 8, and 20 to 30 "
                              f"works best: different angles, distances, outfits, expressions and backgrounds.")
        trigger = re.sub(r"[^a-z0-9]", "", (trigger or slug(name).replace("-", "") + "chr").lower())
        home = self.root / "characters" / slug(name)
        ds = home / "dataset"
        if ds.exists():
            shutil.rmtree(ds)
        ds.mkdir(parents=True)
        notes = []
        if len(photos) != len(unique):
            notes.append(f"Skipped {len(photos) - len(unique)} exact duplicate(s).")
        if len(unique) < 15:
            notes.append(f"Only {len(unique)} photos. It will work, but 20 to 30 varied photos give a better likeness.")
        if len(unique) > 60:
            notes.append("More than 60 photos. Fewer, more varied photos usually train better than many similar ones.")
        small = [p.name for p in unique if min(image_size(p) or (9999, 9999)) < 768]
        if small:
            notes.append(f"{len(small)} photo(s) are under 768 pixels on the short side and may train blurry: " + ", ".join(small[:5]))
        try:
            model = self.vision_model()
        except StudioError:
            model = None
            notes.append("No vision model was available, so every caption is just the trigger word. Captions that "
                         "describe pose and setting train better: download gemma4:12b and run this again.")
        log(f"Preparing {len(unique)} photos" + (f", captioning with {model}" if model else ""))
        for i, p in enumerate(unique, 1):
            target = ds / f"{i:03d}{p.suffix.lower()}"
            shutil.copy2(p, target)
            caption = f"a photo of {trigger}"
            if model:
                try:
                    got = re.sub(r"\s+", " ", self.providers.chat(model, CAPTION.format(trigger=trigger), images=[p])).strip()
                    if got:
                        caption = got if trigger in got.lower() else f"a photo of {trigger}, {got[0].lower()}{got[1:]}"
                except Exception as e:
                    notes.append(f"{p.name}: could not caption ({e})")
            target.with_suffix(".txt").write_text(caption, encoding="utf-8")
            log(f"[{i}/{len(unique)}] {p.name}")
        (home / "character.json").write_text(json.dumps({"name": name.strip(), "trigger": trigger, "photos": len(unique),
                                                          "made": dt.datetime.now().isoformat(timespec="minutes")}), encoding="utf-8")
        (home / "NEXT STEPS.txt").write_text(
            f"Character: {name.strip()}\nTrigger word: {trigger}\nPhotos: {len(unique)}\nDataset folder: {ds}\n\n"
            "1. Read a few of the .txt captions and fix anything wrong. Each one should describe the pose and\n"
            "   setting, not the person's looks: the trigger word stands for the person.\n"
            "2. Train a LoRA on this dataset folder in a trainer. See docs/11-create.md, \"Characters\".\n"
            f"3. Put the finished .safetensors file in ComfyUI's models/loras folder.\n"
            f"4. Use it: pick the LoRA in AI Home and include \"{trigger}\" in your prompt.\n", encoding="utf-8")
        for n in notes:
            log("Note: " + n)
        log(f"Ready. Dataset: {ds}\nTrigger word: {trigger}\nNext steps are in: {home / 'NEXT STEPS.txt'}")
        return {"folder": str(ds), "trigger": trigger, "photos": len(unique), "notes": notes}

    def characters(self):
        out = []
        for f in sorted((self.root / "characters").glob("*/character.json")):
            try:
                out.append({**json.loads(f.read_text(encoding="utf-8")), "folder": str(f.parent / "dataset")})
            except ValueError:
                pass
        return out

    # ---------------------------------------------------------------- 3D models (CAD)

    def openscad(self):
        for name in ("openscad", "openscad.com", "OpenSCAD"):
            found = shutil.which(name)
            if found:
                return found
        for p in (r"C:\Program Files\OpenSCAD\openscad.com", r"C:\Program Files\OpenSCAD (Nightly)\openscad.com",
                  "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"):
            if Path(p).exists():
                return p
        raise StudioError("OpenSCAD isn't installed. Install it on the Install & remove tab, then try again.")

    def make_3d(self, log, description, model=None, tries=3):
        """Describe an object; get OpenSCAD code and a 3D-printable STL file."""
        if not description.strip():
            raise StudioError("Describe the object, with sizes, like: a 60 mm wide phone stand tilted back 20 degrees.")
        exe = self.openscad()
        model = model or self.settings()["cad_model"]
        folder = self.out_dir("3d") / f"{dt.datetime.now():%Y%m%d-%H%M%S} {slug(description, 30)}"
        folder.mkdir(parents=True)
        scad, stl, png = folder / "model.scad", folder / "model.stl", folder / "preview.png"
        ask = f"Design this object:\n{description.strip()}"
        for attempt in range(1, tries + 1):
            log(f"Attempt {attempt}: asking {model} to write the design")
            answer = self.providers.chat(model, ask, system=CAD_SYSTEM)
            m = re.search(r"```(?:openscad|scad)?\s*\n(.*?)```", answer, re.S)
            code = (m.group(1) if m else answer).strip()
            if re.search(r"^\s*(include|use)\s*<|\b(import|surface)\s*\(", code, re.M):
                problem = "The code used include, use, import or surface, which are not allowed."
            elif not code:
                problem = "No code was returned."
            else:
                scad.write_text(code + "\n", encoding="utf-8")
                stl.unlink(missing_ok=True)
                rc, out = self.sys.run([exe, "-o", str(stl), str(scad)], timeout=600)
                errors = "\n".join(ln for ln in out.splitlines() if re.search(r"error|warning", ln, re.I))[:1500]
                if rc == 0 and stl.exists() and stl.stat().st_size > 100:
                    self.sys.run([exe, "-o", str(png), "--autocenter", "--viewall", "--imgsize=800,600", str(scad)], timeout=300)
                    log(f"Built it. Files are in:\n{folder}")
                    return {"folder": str(folder), "stl": str(stl), "scad": str(scad), "preview": str(png) if png.exists() else None}
                problem = errors or out.strip()[-800:] or "OpenSCAD produced an empty model (nothing to print)."
            log(f"Attempt {attempt} didn't build: {problem.splitlines()[0][:200]}")
            ask = (f"Design this object:\n{description.strip()}\n\nYour previous code failed in OpenSCAD:\n{problem}\n\n"
                   f"Previous code:\n```openscad\n{code}\n```\nFix it and send the complete corrected code.")
        raise StudioError(f"{model} couldn't produce a working design in {tries} attempts. Try a simpler description, "
                          f"or pick a stronger model under Create > Setup. The last attempt is in {folder}.")

    # ---------------------------------------------------------------- tools offered to agents

    def shared(self, path):
        """Agents may only touch files in the shared apps folder (called /projects inside the app builder)."""
        base = (self.root / "apps").resolve()
        rel = str(path).replace("\\", "/")
        rel = re.sub(r"^/?projects/", "", rel).lstrip("/")
        full = (base / rel).resolve()
        if full != base and base not in full.parents:
            raise StudioError("Agents can only use files inside the shared apps folder.")
        return full

    def hand_over(self, paths):
        """Copy results into the shared folder so the agent that asked can use them."""
        dest = self.root / "apps" / "generated"
        dest.mkdir(parents=True, exist_ok=True)
        out = []
        for p in paths:
            target = dest / Path(p).name
            shutil.copy2(p, target)
            out.append(f"/projects/generated/{target.name}")
        return "Saved: " + ", ".join(out) + f"  (on the PC: {dest})"

    def tools(self):
        quiet = lambda *_: None  # noqa: E731
        obj = lambda props, req: {"type": "object", "properties": props, "required": req}  # noqa: E731
        s = {"type": "string"}
        return [
            {"name": "look_at_image", "description": "Look at an image file in the shared folder and answer a question about it. "
             "Use this whenever you need to see a picture, screenshot, chart or photo.",
             "inputSchema": obj({"path": {**s, "description": "e.g. /projects/site/hero.png"}, "question": s}, ["path"]),
             "run": lambda a: self.look(self.shared(a.get("path", "")), a.get("question") or "Describe this image in detail.")},
            {"name": "generate_image", "description": "Create a new image from a text description. Returns the saved file's path.",
             "inputSchema": obj({"prompt": s, "lora": {**s, "description": "optional LoRA file name from list_loras"}}, ["prompt"]),
             "run": lambda a: self.hand_over(self.generate_image(quiet, a.get("prompt", ""), a.get("lora")))},
            {"name": "edit_image", "description": "Change an existing image in the shared folder by describing the edit "
             "(for example: remove the background, make it night time). Returns the new file's path; the original is kept.",
             "inputSchema": obj({"path": s, "prompt": s}, ["path", "prompt"]),
             "run": lambda a: self.hand_over([self.edit_image(quiet, self.shared(a.get("path", "")), a.get("prompt", ""))])},
            {"name": "list_loras", "description": "List the LoRA add-ons (styles and characters) available for generate_image.",
             "inputSchema": obj({}, []),
             "run": lambda a: json.dumps(comfy.list_loras(self.models_dir())) },
            {"name": "make_3d_model", "description": "Design a 3D-printable object from a description with sizes in millimetres. "
             "Returns paths to the STL file and the OpenSCAD source.",
             "inputSchema": obj({"description": s}, ["description"]),
             "run": lambda a: (lambda r: self.hand_over([r["stl"], r["scad"]] + ([r["preview"]] if r["preview"] else [])))(
                 self.make_3d(quiet, a.get("description", "")))},
            {"name": "make_music", "description": "Create a piece of music from a style description and optional lyrics.",
             "inputSchema": obj({"style": s, "lyrics": s, "seconds": {"type": "integer"}}, ["style"]),
             "run": lambda a: self.hand_over(self.make_music(quiet, a.get("style", ""), a.get("lyrics", ""), a.get("seconds", 60)))},
        ]
