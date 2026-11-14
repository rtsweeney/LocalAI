# 09. Troubleshooting

Find the symptom, try the fixes in order.

## Setup and starting

| Symptom | Likely cause | Fix |
|---|---|---|
| "running scripts is disabled on this system" | Windows blocks downloaded scripts | Run it as `powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1` |
| "winget is missing" | Older Windows 10 | Install **App Installer** from the Microsoft Store |
| "Docker is not running" | Docker Desktop isn't open | Open it from the Start menu and wait for "Engine running" |
| Docker Desktop asks about WSL, or won't start | WSL is missing or old | In PowerShell run `wsl --update`, then restart the PC |
| "Ollama is not running" | It isn't in the tray | Open **Ollama** from the Start menu |
| A page says **NOT YET** | First start is still downloading | Wait a few minutes, run `start.ps1` again. Then check `docker compose logs --tail 50` |
| "required variable WEBUI_SECRET_KEY is missing" | No `.env` file | Run `setup.ps1` |
| "port is already allocated" | Another program uses 3000, 3001 or 8880 | In `compose.yaml`, change the middle number, for example `127.0.0.1:3005:8080`, and use that port instead |

## AI Home (the control panel)

| Symptom | Likely cause | Fix |
|---|---|---|
| Double-clicking `Start AI Home.bat` flashes and closes | Python was only just installed | Double-click it again. If it still closes, restart the PC |
| Windows warns the file came from the internet | It was downloaded in a ZIP | Click **More info → Run anyway**, or right-click the file → Properties → tick **Unblock** |
| A part stays "Not installed" after Install | The install failed or needs a restart | Open the **Activity** tab and read that job's log |
| "Docker isn't running" when installing a part | Docker Desktop is closed, or the PC wasn't restarted | Restart, open Docker Desktop, wait for "Engine running" |
| Page says "AI Home stopped answering" | Its window was closed | Double-click `Start AI Home.bat` again |
| "Reload the page" errors | AI Home was restarted while the page was open | Reload the page |
| A scheduled job didn't run | AI Home or the PC was off at that time | Tick "Start AI Home quietly when I sign in"; set Sleep to Never |
| A model job fails straight away | Ollama is off, or that model was deleted | Start Ollama; edit the job and pick a model you have |

## Chat

| Symptom | Likely cause | Fix |
|---|---|---|
| No models in the list | The chat page can't reach Ollama | Check `ollama list` shows models. Then in the chat page: **Admin Panel → Settings → Connections**, Ollama address `http://host.docker.internal:11434` |
| Answers are very slow | The model doesn't fit in VRAM | Run `ollama ps`. If the PROCESSOR column shows any CPU share, the model has spilled into RAM. Use a smaller model or version ([03](03-models.md)) |
| Slow only sometimes | Something else is on the GPU | Close games and ComfyUI; check `ollama ps` for a second loaded model |
| The model forgets earlier messages | Conversation exceeded the context | Start a new chat |
| No sound from the speaker icon | Voice settings were saved differently | See the note in [06](06-voices-audiobooks.md) |

## App builder

| Symptom | Likely cause | Fix |
|---|---|---|
| "Connection error" or no reply | Wrong Base URL | It must be `http://host.docker.internal:11434/v1`, not `localhost` |
| It forgets its instructions or stops early | Context too small | Run `ollama ps` while it works; the CONTEXT column should show 32768. If not, restart the PC so the setting from `setup.ps1` applies |
| "Model not found" | Name mismatch | Custom Model must be `openai/` plus the exact name from `ollama list` |
| It repeats the same failing fix | The model is stuck | Stop it, start a new conversation, describe a smaller step |

## Images and video

| Symptom | Likely cause | Fix |
|---|---|---|
| "out of memory" or "CUDA out of memory" | VRAM is full | `ollama stop` your chat model, close other programs, lower the resolution or frame count |
| A template lists missing models | Not downloaded yet | Click to download them from the template's prompt |

## iPhone

| Symptom | Likely cause | Fix |
|---|---|---|
| Address won't load on the phone | Tailscale is off on the phone | Open the Tailscale app and switch it on |
| Worked yesterday, not today | The PC is asleep or off | Set Sleep to Never ([07](07-iphone.md)) |
| "serve" printed a link instead of an address | HTTPS isn't enabled yet | Open the link, approve, run the command again |

## Tools in this folder

| Symptom | Likely cause | Fix |
|---|---|---|
| "python is not recognized" | The terminal was open during install | Close PowerShell and open it again |
| `fit.py`: "Could not read … from Hugging Face" | Typo, or a private repo | Copy the `owner/name` from the top of the model's page |
| `fit.py`: "has no .gguf files" | Not a GGUF repo | Run `fit.py search` with the model's name |
| `audiobook.py`: "Could not reach the voice engine" | Kokoro isn't running | Run `start.ps1` |
| `newsdesk.py`: "Could not reach Ollama" | Ollama is off, or the model is missing | Start Ollama; run `ollama pull qwen3-embedding:0.6b` |
| `newsdesk.py`: "0 stories are covered by 2+ outlets" | Similarity threshold too strict | Lower `same_story_similarity` in `config.json` ([08](08-news-desk.md)) |

## Starting over

To reset the chat page and app builder completely, **deleting all chats and accounts**:

```powershell
docker compose down -v
```

Your downloaded models are not affected. Delete those one at a time with `ollama rm NAME`.

## Updating

```powershell
docker compose pull
```

```powershell
docker compose up -d
```

Ollama, Docker Desktop and ComfyUI update themselves or prompt you.

---

Next: [10. AI Home, the control panel](10-control-panel.md)
