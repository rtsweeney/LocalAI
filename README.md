# Your AI home

Everything here runs on your own PC: chat, an app builder, images, bulk photo edits, video, music, 3D models, voices, audiobooks, plugins for your agents, and a first-pass news desk for your site. Nothing is sent to a cloud service unless you add a cloud model yourself, and there are no subscriptions.

It is set up for **Windows with a 16 GB NVIDIA graphics card**.

> **Read this first: what has and hasn't been tested.**
> This was written on a Linux server with no graphics card, so:
> - **Tested:** the three Python tools (model-fit checker, audiobook maker, news desk) and the AI Home control panel. Together they have 70 automated tests. The model-fit checker and the news reader were also run against the real Hugging Face and real news sites. The plugin hub was tested with the official MCP library, and the Claude connection with Anthropic's official library.
> - **Tested against pretend services only:** image, photo-edit, video, music and 3D jobs ran against stand-ins for ComfyUI and OpenSCAD, and cloud models against stand-ins for Claude and OpenRouter. None has touched the real thing.
> - **Tested against a pretend PC only:** the control panel's install, remove and schedule buttons were clicked through in a real browser, but the "PC" behind them was a stand-in that imitates Windows' installer, Docker and Ollama.
> - **Checked but not run:** the Docker file is valid and its three images exist, but the containers have never been started.
> - **Not tested at all:** `Start AI Home.bat` and the three scripts in `scripts\`. They have been proofread, not run. If one fails, the error message and [troubleshooting](docs/09-troubleshooting.md) are the place to start.

## What you get

| You want to… | You use | Where it runs | Guide |
|---|---|---|---|
| **Manage everything from one page**: install, remove, open, schedule | **AI Home** | `http://localhost:3010` | [10](docs/10-control-panel.md) |
| Run jobs at set times | AI Home's Schedule tab | Same page | [10](docs/10-control-panel.md#scheduled-jobs) |
| Edit a whole folder of photos with one instruction | AI Home's Create tab | Same page | [11](docs/11-create.md#edit-a-whole-folder-of-photos) |
| Use LoRAs, and build a character from photos | AI Home's Create tab | Same page | [11](docs/11-create.md#loras) |
| Design 3D-printable parts (CAD) | AI Home's Create tab + OpenSCAD | Same page | [11](docs/11-create.md#3d-models-cad) |
| Make music | AI Home's Music tab | Same page | [11](docs/11-create.md#music) |
| Give agents plugins (like REA) and vision | AI Home's Plugins tab | Same page | [12](docs/12-plugins-and-cloud.md) |
| Use Claude or any OpenRouter model | AI Home's Models tab | Same page | [12](docs/12-plugins-and-cloud.md#cloud-models-claude-and-openrouter) |
| Chat with a model, from the PC or iPhone | Open WebUI | `http://localhost:3000` | [02](docs/02-install.md) |
| Pick any model from Hugging Face that fits your card | Ollama + `tools\fit.py` | A terminal | [03](docs/03-models.md) |
| Build an app from one sentence and let it run | OpenHands Agent Canvas | `http://localhost:3001/canvas` | [04](docs/04-app-builder.md) |
| Make images and video | ComfyUI Desktop | Its own window | [05](docs/05-images-video.md) |
| Hear answers read aloud; turn books into audiobooks | Kokoro + `tools\audiobook.py` | Built into the chat page; a terminal | [06](docs/06-voices-audiobooks.md) |
| Use it all from your iPhone | Tailscale | Safari on the phone | [07](docs/07-iphone.md) |
| Draft "Latest" entries for your news site | `newsdesk\newsdesk.py` | A terminal | [08](docs/08-news-desk.md) |

New to all this? Read [01: the five ideas you need](docs/01-concepts.md) first. It takes five minutes and makes everything else make sense.

## How the pieces fit

```
                        your iPhone
                             |
                  Tailscale (private, encrypted)
                             |
  +--------------------- your PC ------------------------------+
  |                                                            |
  |  In Docker (ordinary web pages, no graphics card needed)   |
  |    Chat home page :3000    App builder :3001    Voice :8880|
  |          |                      |                          |
  |          +----------+-----------+                          |
  |                     v                                      |
  |  On Windows directly (these use the graphics card)         |
  |    Ollama :11434  (runs the language models)               |
  |    ComfyUI        (makes images and video)                 |
  |                                                            |
  |  In this folder (plain Python)                             |
  |    AI Home :3010  (the control panel; installs, removes,   |
  |                    opens and schedules everything above)   |
  |    fit.py    audiobook.py    newsdesk.py                   |
  +------------------------------------------------------------+
```

**Why split it this way?** Giving a graphics card to a program inside Docker on Windows is fiddly. So the two programs that need the card are installed the normal Windows way, and everything else, which is just web pages, goes in Docker where one command starts and stops it all.

## Quick start

You need about **150 GB of free disk space** (models are big) and an up-to-date NVIDIA driver.

1. **Get this folder onto the PC.** On the GitHub page, click **Code → Download ZIP**, and unzip it somewhere simple like `C:\LocalAI`.
2. **Double-click `Start AI Home.bat`.** The first time, it installs Python and asks you to double-click it again. Then the control panel opens in your browser.
3. On **Install & remove**, click **Install** on **Ollama**, then on **Docker Desktop**.
4. **Restart the PC.** Open **Docker Desktop** once from the Start menu and wait for "Engine running". Open **Ollama** from the Start menu too.
5. Double-click `Start AI Home.bat` again. Click **Install** on **Chat home page**, and on any optional parts you want.
6. On **Models**, click **Download** on the starter models. This is about 25 GB, so go and make a coffee.
7. On **Home**, click **Open** on the chat page and create your account. The first account is the owner.

[10: the control panel](docs/10-control-panel.md) explains every button. If you would sooner type commands than click, `scripts\setup.ps1` and `scripts\start.ps1` do the same setup; see [02](docs/02-install.md).

## Good to know before you start

- **One big job at a time.** 16 GB holds one large model. Chatting while a video renders will make both crawl. [01](docs/01-concepts.md) explains why, and [05](docs/05-images-video.md) shows how to free the card.
- **Local models are weaker than the big cloud ones.** They are good at chat, summaries and small apps. They make things up more often. That is why the news desk checks every number and name, and why nothing it writes is published without you.
- **Why not just install Locally Uncensored?** You can; it is a free app that bundles these same engines behind one window, and it may suit you. This kit uses the engines directly instead, because each is a large, widely used project on its own, and because your news desk and audiobook tools need to talk to them from scripts.

## Checking the tools work

```powershell
python -m unittest discover tests
```

This runs the tests with a pretend model and a pretend PC, so it works before anything is installed. A few tests need two extra libraries and are skipped without them; to run all 70:

```powershell
python -m pip install mcp anthropic
```
