# 10. AI Home: the control panel

**AI Home** is one page that manages everything else. Double-click **`Start AI Home.bat`** and it opens at `http://localhost:3010`.

> **What has been tested.** The panel was driven in a real browser against a *pretend* PC: a stand-in that answers the way Windows' installer, Docker and Ollama would. 21 automated tests cover installing, removing, models, schedules and security. It has **not** been run on real Windows, so the first real install is the true test. `Start AI Home.bat` itself has never been run.

## The tabs

| Tab | What you do there |
|---|---|
| **Home** | See what is running, open each part, unload models from the graphics card, read the guides |
| **Install & remove** | One click to install, start, stop or uninstall each part |
| **Models** | Download the starter models, check any Hugging Face model against your card, delete models |
| **Create** | Images, bulk photo edits, video, LoRAs, characters and 3D models ([11](11-create.md)) |
| **Music** | Make music from a description and lyrics ([11](11-create.md#music)) |
| **Plugins** | Give your agents new tools, and connect them to the plugin hub ([12](12-plugins-and-cloud.md)) |
| **Schedule** | Make jobs that run by themselves at set times |
| **Activity** | Watch progress and read the log of everything the panel did |

## Installing and removing

Each part is a card with a status and buttons.

**Required** (install in this order):

1. **Ollama**: runs the models.
2. **Docker Desktop**: runs the web pages. **Restart the PC after this one**, then open Docker Desktop once from the Start menu.
3. **Chat home page**: needs the two above running.

**Optional:** Voice engine, App builder, ComfyUI, Tailscale, Git, OpenSCAD (for 3D models), and Node.js and uv (for plugins). Add or remove any of them at any time.

### What each button really does

| Button | For Windows programs | For the web pages in Docker |
|---|---|---|
| **Install** | Asks Windows' installer (winget) to install it. Windows may show a permission prompt. | Downloads it and starts it |
| **Start / Stop** | Not available: open or close these from the Start menu | Starts or stops it. Nothing is deleted. |
| **Uninstall** | Asks Windows to remove the program | Removes it and its download, **keeps your data** |
| **Uninstall and delete data** | | Also deletes your chats, accounts and settings. **Cannot be undone.** |

Anything that deletes something asks you to confirm first. That is one extra click on purpose.

**Two things uninstall does not remove:**

- **Uninstalling Ollama leaves your downloaded models on disk.** Delete them on the Models tab first if you want the space back.
- **Uninstalling ComfyUI leaves its image and video models.** Delete its folder by hand.

## Models

- **Starter models:** one click each.
- **On this PC:** every model, its size, and a Delete button.
- **Get another model:** type search words, click a result, and you get a table of every version marked **Fits**, **Tight** or **Too big** for your card, each with a Download button. This is the same check as `tools\fit.py` ([03](03-models.md)).

## Scheduled jobs

A job has a name, something to do, and a time.

### What a job can do

| Kind | What happens | Where the result goes |
|---|---|---|
| **Ask a model** | Sends your question to a model you pick | Saved, and shown under the job |
| **Run the news desk** | Reads the feeds and drafts entries ([08](08-news-desk.md)) | A banner on the Home tab links to the review page |
| **Run a command** | Runs any command line, for example the audiobook maker | The command's output is saved |

### Saying when

Type it in plain words. The page shows the first run time as you type, so you can check it understood.

| You type | It runs |
|---|---|
| `every 2h` | Every two hours, counted from when you save |
| `every 30m` | Every thirty minutes |
| `daily at 5am` | Every day at 5:00 |
| `weekdays at 6:30` | Monday to Friday at 6:30 |
| `mon,wed,fri at 8pm` | Those three days at 20:00 |
| `in 45m` | Once, 45 minutes from now |
| `once 2026-12-01 14:00` | Once, at that date and time |
| `0 5 * * *` | Cron lines work too, if you know them |

### How jobs behave

- **Each run starts fresh.** A model job has no memory of earlier runs or of your chats. Write the request so it makes sense alone.
- **One at a time.** If two jobs are due together, the second waits. This stops them fighting over the graphics card.
- **No pile-ups.** A job that is still running when its next time arrives skips that turn.
- **If the PC was off,** a missed job runs once when AI Home next starts, not once for every time it missed.
- **The last 50 results** of each job are kept.

### Keeping schedules alive

Jobs only run while AI Home is running. On **Install & remove**, tick **Start AI Home quietly when I sign in to Windows**. It then starts in the background after every restart, with no window. The PC must also be awake ([07](07-iphone.md#keep-the-pc-awake)).

## Safety

- **This PC only.** The panel can install and delete things, so it is not shared with your iPhone or your network. It listens only on the PC itself.
- **Other websites can't press its buttons.** Every button press must carry a secret that only the page AI Home served knows. A site open in another tab doesn't have it.
- **"Run a command" jobs run with your Windows permissions.** Only schedule commands you understand.

## Stopping it

Close the black window that opened with it. If it was started at sign-in there is no window: open Task Manager, find **pythonw**, and end it.

---

Next: [11. Create](11-create.md)
