# Your AI home

Everything here runs on your own PC: chat, an app builder, images, video, voices, audiobooks and a first-pass news desk for your site. Nothing is sent to a cloud service, and there are no subscriptions.

It is set up for **Windows with a 16 GB NVIDIA graphics card**.

> **Read this first: what has and hasn't been tested.**
> This was written on a Linux server with no graphics card, so:
> - **Tested:** the three Python tools (model-fit checker, audiobook maker, news desk). They have 16 automated tests, and the model-fit checker and the news reader were also run against the real Hugging Face and real news sites.
> - **Checked but not run:** the Docker file is valid and its three images exist, but the containers have never been started.
> - **Not tested at all:** the three Windows scripts in `scripts\`. They have been proofread, not run. If one fails, the error message and [troubleshooting](docs/09-troubleshooting.md) are the place to start.

## What you get

| You want to… | You use | Where it runs | Guide |
|---|---|---|---|
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
  |  Small tools in this folder (plain Python)                 |
  |    fit.py    audiobook.py    newsdesk.py                   |
  +------------------------------------------------------------+
```

**Why split it this way?** Giving a graphics card to a program inside Docker on Windows is fiddly. So the two programs that need the card are installed the normal Windows way, and everything else, which is just web pages, goes in Docker where one command starts and stops it all.

## Quick start

You need about **150 GB of free disk space** (models are big) and an up-to-date NVIDIA driver.

1. **Get this folder onto the PC.** On the GitHub page, click **Code → Download ZIP**, and unzip it somewhere simple like `C:\LocalAI`.
2. **Open a terminal in that folder.** In File Explorer, open the folder, click the address bar, type `powershell` and press Enter.
3. **Run the one-time setup:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
   ```
4. **Restart the PC**, open **Docker Desktop** once from the Start menu, and wait for "Engine running".
5. **Start everything:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
   ```
   The first start downloads about 25 GB of models. Go and make a coffee.
6. **Open `http://localhost:3000`** and create your account. The first account is the owner.

Then follow the guides in order. [02: install](docs/02-install.md) explains each of those steps and what you should see.

## Good to know before you start

- **One big job at a time.** 16 GB holds one large model. Chatting while a video renders will make both crawl. [01](docs/01-concepts.md) explains why, and [05](docs/05-images-video.md) shows how to free the card.
- **Local models are weaker than the big cloud ones.** They are good at chat, summaries and small apps. They make things up more often. That is why the news desk checks every number and name, and why nothing it writes is published without you.
- **Why not just install Locally Uncensored?** You can; it is a free app that bundles these same engines behind one window, and it may suit you. This kit uses the engines directly instead, because each is a large, widely used project on its own, and because your news desk and audiobook tools need to talk to them from scripts.

## Checking the tools work

```powershell
python -m unittest discover tests
```

This runs the 16 tests with a pretend model, so it works before any model is downloaded.
