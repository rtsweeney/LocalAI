# 04. The app builder: one sentence in, an app out

**OpenHands Agent Canvas** is a coding agent. You describe what you want; it writes the files, runs them, reads the errors and fixes them, in a loop, until it thinks it is done.

> **Not tested on your setup.** The connection settings below come from OpenHands' documentation (read Nov. 14, 2026), but Agent Canvas has never been started as part of this kit. Its Docker instructions are written for Mac and Linux; it should behave the same in Docker Desktop on Windows, but that is unconfirmed. If it won't start, OpenHands also offers a Windows desktop installer on [its setup page](https://docs.openhands.dev/openhands/usage/agent-canvas/setup).

## One-time connection to your local model

1. Open `http://localhost:3001/canvas`.
2. Go to **Settings → LLM** and turn on **Advanced**.
3. Enter exactly:

| Field | Value | Why |
|---|---|---|
| Custom Model | `openai/gpt-oss:20b` | `openai/` means "speaks the OpenAI-style language", which Ollama does. The rest is the model's Ollama name. |
| Base URL | `http://host.docker.internal:11434/v1` | `host.docker.internal` is how a container says "the PC I'm running on", where Ollama lives. |
| API Key | `dummy` | Ollama needs no key, but the field can't be empty. |

## Your first app

Start small. Type something like:

> Build a single-page tip calculator in plain HTML, CSS and JavaScript. Save it in /projects/tip-calculator. Open index.html in a browser test to check the math before you finish.

Then leave it alone. When it finishes, the files are in the **`apps`** folder inside your LocalAI folder. Double-click `index.html` to use your app.

**Why `/projects`?** That is the only folder the builder can see. It maps to `apps` on your PC. The builder runs inside a container, so a mistake by the model can't touch your documents or the rest of Windows.

## What to expect from a 16 GB card

| Works well | Struggles |
|---|---|
| Single-page web apps and small sites | Large apps with many files that depend on each other |
| Python scripts and command-line tools | Unfamiliar or brand-new frameworks |
| Converting, renaming and tidying files | Long tasks where it must remember early decisions |
| Fixing a bug you can describe clearly | Vague requests ("make it better") |

Local models lose the thread on long jobs more than cloud models do. The habits that help most:

1. **One feature per request.** Build the basics, check them, then ask for the next thing.
2. **Say how to check the work.** "Run the tests", "open the page and confirm the total updates". An agent that can test itself fixes its own mistakes.
3. **Name the tools.** "Plain HTML and JavaScript, no frameworks" gives a weaker model less to get wrong.
4. **If it loops, stop it.** Repeating the same failed fix three times means it is stuck. Stop, and restate the problem more narrowly in a new conversation.

## Why setup changed Ollama's memory setting

The builder sends the model long instructions plus your files. Ollama's default context of 4,096 tokens is far too small for that, and OpenHands' documentation asks for at least 22,000. `setup.ps1` set it to 32,768 for your Windows account (`OLLAMA_CONTEXT_LENGTH`). `gpt-oss:20b` still fits on your card at that size (see [03](03-models.md)).

## Trying a different model

Check it fits at the long context first:

```powershell
python tools\fit.py unsloth/Devstral-Small-2-24B-Instruct-2512-GGUF --context 32768
```

Then download it and change **Custom Model** to `openai/` followed by the exact name `ollama list` shows.

---

Next: [05. Images and video](05-images-video.md)
