#!/usr/bin/env python3
"""Turn a book into an audiobook with your local voice engine (Kokoro).

    python tools/audiobook.py "C:\\Books\\my-book.epub"
    python tools/audiobook.py notes.txt --voice am_michael --speed 1.1
    python tools/audiobook.py --voices                      list the voices you can use

It writes one MP3 per chapter into a folder next to the book. If it is interrupted, run the
same command again: finished chapters are skipped.

Works with .epub files that have no copy protection (DRM) and with plain .txt files. Only use
books you have the right to copy; a protected store-bought ebook will not open.

Uses only Python's standard library, so there is nothing to install.
"""
import argparse
import html
import json
import posixpath
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path

# A sentence end: . ! ? or …, an optional closing quote or bracket, then a space.
SENTENCE_END = re.compile(r"([.!?…][\"'”’)]?)\s+")
CHUNK = 1200  # characters sent to the voice engine at a time; small pieces keep it reliable


class Text(HTMLParser):
    BLOCK = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.title, self.in_h = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        self.in_h = tag in ("h1", "h2", "h3") and not self.title

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.skip:
            self.skip -= 1
        if tag in self.BLOCK:
            self.out.append("\n")
        self.in_h = False

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)
            if self.in_h:
                self.title = (self.title + data).strip()


def tidy(text):
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def local(tag):
    return tag.rsplit("}", 1)[-1]


def read_epub(path):
    """An EPUB is a zip of web pages plus a list (the "spine") giving their reading order."""
    chapters = []
    with zipfile.ZipFile(path) as z:
        if "META-INF/encryption.xml" in z.namelist() and b"EncryptedData" in z.read("META-INF/encryption.xml"):
            sys.exit("This EPUB is copy-protected (DRM), so its text can't be read.")
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = next(e.get("full-path") for e in container.iter() if local(e.tag) == "rootfile")
        opf = ET.fromstring(z.read(opf_path))
        files = {e.get("id"): e.get("href") for e in opf.iter() if local(e.tag) == "item"}
        order = [e.get("idref") for e in opf.iter() if local(e.tag) == "itemref"]
        base = posixpath.dirname(opf_path)
        for ref in order:
            href = files.get(ref)
            if not href:
                continue
            name = posixpath.normpath(posixpath.join(base, urllib.parse.unquote(href.split("#")[0])))
            try:
                page = z.read(name).decode("utf-8", errors="replace")
            except KeyError:
                continue
            t = Text()
            t.feed(page)
            body = tidy("".join(t.out))
            if len(body) >= 200:  # skips the cover, blank pages and the copyright stub
                chapters.append((t.title or f"Part {len(chapters) + 1}", body))
    return chapters


def read_txt(path):
    text = tidy(Path(path).read_text(encoding="utf-8", errors="replace"))
    parts = re.split(r"\n(?=(?:chapter|part)\s+[\divxlc]+\b)", text, flags=re.I)
    parts = [p for p in parts if p.strip()]
    if len(parts) < 2:
        return [("Full text", text)] if text else []
    return [(p.split("\n", 1)[0][:60], p) for p in parts]


def chunks(text, size=CHUNK):
    """Split at sentence ends so the voice never stops mid-sentence."""
    out, cur = [], ""
    for para in text.split("\n"):
        for sentence in SENTENCE_END.sub(r"\1\n", para).split("\n"):
            while len(sentence) > size:  # one giant sentence: cut at a space
                cut = sentence.rfind(" ", 0, size)
                cut = cut if cut > 0 else size
                if cur:
                    out.append(cur)
                    cur = ""
                out.append(sentence[:cut])
                sentence = sentence[cut:].strip()
            if cur and len(cur) + 1 + len(sentence) > size:
                out.append(cur)
                cur = sentence
            else:
                cur = f"{cur} {sentence}".strip()
    if cur:
        out.append(cur)
    return [c for c in out if re.search(r"\w", c)]


def speak(text, a):
    body = json.dumps({"model": a.model, "voice": a.voice, "input": text, "speed": a.speed,
                       "response_format": "mp3"}).encode()
    req = urllib.request.Request(a.url.rstrip("/") + "/audio/speech", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer not-needed"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def safe(name):
    return re.sub(r"[^\w\- ]+", "", html.unescape(name)).strip()[:50] or "chapter"


def list_voices(a):
    req = urllib.request.Request(a.url.rstrip("/") + "/audio/voices")
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    names = data.get("voices", data) if isinstance(data, dict) else data
    names = [v.get("id") or v.get("name") if isinstance(v, dict) else v for v in names]
    print("Voices (the first letter is the accent, the second is f or m: af = American female):\n")
    print("  " + "\n  ".join(sorted(str(n) for n in names)))


def main(argv=None):
    p = argparse.ArgumentParser(description="Turn a .epub or .txt book into MP3 files.")
    p.add_argument("book", nargs="?")
    p.add_argument("--voice", default="af_heart")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--model", default="kokoro")
    p.add_argument("--url", default="http://127.0.0.1:8880/v1", help="the voice engine's address")
    p.add_argument("--out", help="output folder (default: next to the book)")
    p.add_argument("--voices", action="store_true", help="list available voices and stop")
    a = p.parse_args(argv)
    try:
        if a.voices:
            return list_voices(a)
        if not a.book:
            p.error("give the path to a .epub or .txt file")
        book = Path(a.book)
        if not book.exists():
            sys.exit(f"File not found: {book}")
        chapters = read_epub(book) if book.suffix.lower() == ".epub" else read_txt(book)
        if not chapters:
            sys.exit("No readable text found in that file.")
        out = Path(a.out) if a.out else book.with_name(book.stem + " (audiobook)")
        out.mkdir(parents=True, exist_ok=True)
        total = sum(len(body) for _, body in chapters)
        print(f"{len(chapters)} chapter(s), about {total // 900} minutes of audio. Saving to:\n  {out}\n")
        for n, (title, body) in enumerate(chapters, 1):
            target = out / f"{n:03d} {safe(title)}.mp3"
            if target.exists():
                print(f"[{n}/{len(chapters)}] already done: {target.name}")
                continue
            pieces = chunks(body)
            part = target.with_suffix(".part")  # only renamed to .mp3 once the chapter is complete
            with open(part, "wb") as f:
                for i, piece in enumerate(pieces, 1):
                    f.write(speak(piece, a))
                    print(f"\r[{n}/{len(chapters)}] {title[:40]}: {i}/{len(pieces)}", end="", flush=True)
            part.replace(target)
            print()
        print("\nFinished.")
    except urllib.error.URLError as e:
        sys.exit(f"\nCould not reach the voice engine at {a.url}: {e}\n"
                 f"Is Docker Desktop running? Start everything with:  .\\scripts\\start.ps1")


if __name__ == "__main__":
    main()
