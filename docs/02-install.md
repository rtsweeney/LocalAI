# 02. Install, step by step

**The easy way is the control panel:** double-click `Start AI Home.bat` and use its buttons ([10](10-control-panel.md)). This page is the same setup done by typing commands instead, and it explains what each step does. Use whichever you like; they install the same things.

## Before you start

- **Disk space:** about 150 GB free. The starter chat models take about 25 GB; each image or video model adds 5 to 30 GB.
- **NVIDIA driver:** up to date, from [nvidia.com/drivers](https://www.nvidia.com/drivers) or the NVIDIA app.
- **Find your VRAM:** press Ctrl+Shift+Esc, then **Performance → GPU → Dedicated GPU memory**.

## Step 1. Run setup

Open PowerShell in the LocalAI folder (in File Explorer, click the address bar, type `powershell`, press Enter), then:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

**What `-ExecutionPolicy Bypass` means:** Windows refuses to run downloaded scripts by default. This allows this one script, this one time. It does not change the setting for anything else.

Setup installs five programs. Windows will ask for permission for each:

| Program | What it is for |
|---|---|
| **Ollama** | Loads AI models onto your graphics card and answers questions |
| **Docker Desktop** | Runs the chat page, voice engine and app builder in sealed boxes called containers |
| **Python** | Runs the three small tools in this folder |
| **Git** | Lets you download updates to this folder later |
| **Tailscale** | Makes a private link between your PC and your iPhone |

It also creates a file called `.env` holding a random secret that keeps you signed in. Don't share that file.

## Step 2. Restart, then open Docker Desktop once

Docker needs a restart to finish installing. Afterwards, open **Docker Desktop** from the Start menu, accept the terms (you can skip the sign-in), and wait until the bottom-left corner says **Engine running**.

If Docker asks to install or update **WSL**, say yes. WSL is the part of Windows that Docker runs on.

## Step 3. Start everything

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

You should see three stages:

1. **Ollama** downloads three models (about 25 GB the first time).
2. **Docker** downloads and starts three containers.
3. Each page is checked and marked **READY**.

## Step 4. First chat

1. Open `http://localhost:3000`.
2. Create an account. **The first account is the owner.** It lives only on your PC.
3. Pick `gemma4:12b` in the model list at the top and say hello.

The first answer takes a few seconds while the model loads into VRAM. After that it is quick.

## Every day after

| To… | Do this |
|---|---|
| Start | Run `scripts\start.ps1`. It takes seconds after the first time. |
| Stop | Run `scripts\stop.ps1`. Chats and settings are kept. |
| See what's loaded on the GPU | `ollama ps` |
| See what Docker is running | Open Docker Desktop, or run `docker compose ps` in this folder |

Ollama starts with Windows. Docker Desktop does too if **Start Docker Desktop when you sign in** is ticked under its **Settings → General**. The containers restart themselves once Docker is up, so after a reboot everything normally comes back without you doing anything.

---

Next: [03. Choosing models](03-models.md)
