# 06. Voices and audiobooks

The voice engine is **Kokoro**, a small text-to-speech model. It is small enough to run on your processor instead of the graphics card, so it never competes with your chat or video models for VRAM.

## Hearing chat answers

In the chat page, click the **speaker icon** under any answer. This is already connected: `compose.yaml` points Open WebUI at Kokoro.

To change the voice, go to **Admin Panel → Settings → Audio** and edit **TTS Voice**.

> If the speaker icon stays silent, check those Audio settings show engine **OpenAI**, address `http://kokoro:8880/v1` and model `kokoro`. Open WebUI stores these after its first start, so later edits to `compose.yaml` are ignored; change them on that settings page instead.

## Turning a book into an audiobook

```powershell
python tools\audiobook.py "C:\Books\my-book.epub"
```

It creates a folder next to the book with one MP3 per chapter:

```
my-book (audiobook)\
    001 Chapter One.mp3
    002 Chapter Two.mp3
```

Copy that folder to your iPhone (iCloud Drive or the Files app) and play it in any audiobook or music app.

### Options

| Option | Example | What it does |
|---|---|---|
| `--voices` | `python tools\audiobook.py --voices` | Lists every voice |
| `--voice` | `--voice bm_george` | Picks a voice. The default is `af_heart` |
| `--speed` | `--speed 1.1` | Reads faster or slower |
| `--out` | `--out "D:\Audiobooks\Title"` | Saves somewhere else |

**Reading voice names:** the first letter is the accent (`a` American, `b` British) and the second is `f` or `m`. So `bm_george` is a British male voice.

### What it can read

- **`.epub`** files without copy protection: public-domain books (for example from Project Gutenberg or Standard Ebooks) and ebooks sold DRM-free.
- **`.txt`** files. Lines starting "Chapter 1", "Part II" and so on become separate files.
- **Not** store-bought ebooks with copy protection (most Kindle and Apple Books purchases). The tool says so and stops.

### If it gets interrupted

Run the same command again. Finished chapters are skipped, and a half-made chapter is redone from its start.

### How long it takes

Roughly a minute of audio per 900 characters of text. On a processor, expect a long book to take hours to convert, so start it and walk away. If you want it faster, Kokoro has a GPU version: in `compose.yaml`, change the image to `ghcr.io/remsky/kokoro-fastapi-gpu:latest`. That needs Docker's GPU support set up, which this kit doesn't do for you.

## What isn't included

**Copying a specific person's voice** (voice cloning) is not set up here. Tools for it exist, but only clone a voice with that person's permission.

---

Next: [07. Using it from your iPhone](07-iphone.md)
