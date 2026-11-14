# 12. Plugins, vision on demand, and cloud models

## Plugins

A **plugin** gives your AI agents new abilities: reading web pages, driving a browser, taking software apart. Plugins speak a standard called **MCP** (Model Context Protocol), and most plugins made for other agent apps, such as Hermes Agent, are MCP plugins underneath.

> **What has been tested.** The hub was tested with the official MCP library on both sides: its client connecting to the hub, and a plugin built with it running under the hub. **REA itself was not run** (the test environment did not allow it), and the hub has **not been connected to the real chat page or app builder**. The connection steps below come from their documentation.

### The hub

Without a hub, you would add each plugin to each agent separately. AI Home runs one **plugin hub**: connect the chat page and the app builder to it once, and every plugin you add in AI Home reaches both.

```
chat page  ---+
app builder --+-->  the hub  --+--> built-in tools (vision, images, 3D, music)
                               +--> REA
                               +--> any other plugin you add
```

### Connect your agents (once)

The **Plugins** tab shows your hub's address and key with Copy buttons.

**Chat page (Open WebUI):**

1. Sign in as the owner. Open **Admin Settings → External Tools** and click **+**.
2. Set the type to **MCP (Streamable HTTP)**. Picking the wrong type here is the usual mistake.
3. Paste the address and the key (as a Bearer key). Save.
4. In a chat, click **+ → Tools** and switch it on.

The model must support **tool calling**. `gpt-oss:20b` does.

**App builder:** in its settings, add an MCP server of the HTTP kind with the same address and key.

### Built-in tools

These come with AI Home and are always on the hub:

| Tool | What an agent can do with it |
|---|---|
| `look_at_image` | Look at a picture and answer a question about it |
| `generate_image` | Make a new image from a description |
| `edit_image` | Change an existing image by describing the edit |
| `list_loras` | See which LoRAs are available |
| `make_3d_model` | Design a 3D-printable object |
| `make_music` | Make a piece of music |

So you can tell the app builder *"build a landing page and generate a hero image for it"*, and it can.

**Files go through the shared folder.** Agents can only read and write inside the `apps` folder (which the app builder calls `/projects`). Results are saved to `apps\generated`. An agent cannot use these tools to reach the rest of your PC.

### Vision when needed

`look_at_image` is how vision loads on demand. Your main model doesn't need to see images itself: when an agent needs to look at something, it calls the tool, the vision model loads, answers, and frees the graphics card again a few minutes later.

AI Home picks a vision-capable local model automatically (`gemma4:12b` is one). To choose a different one, or a cloud model, use **Create → Setup → Vision model**.

### Adding a plugin

The Plugins tab has ready-made entries:

| Plugin | What it does | Needs |
|---|---|---|
| **REA** | About 200 tools for reverse engineering programs, apps and firmware | Node.js, plus your own Ghidra or similar for deep analysis |
| **Web page reader** | Lets an agent read a page you point it at | uv |
| **Browser control** | Lets an agent click through websites | Node.js |

Install **Node.js** or **uv** on the Install & remove tab first, then click **Add**, then **Test**. The first start can take a minute while the plugin downloads.

To add any other plugin, give it a name and either the command that starts it (its page will say, often beginning `npx` or `uvx`) or its web address.

### "Always listed" or "on demand"

Every tool comes with a description the model must read, and descriptions use up the model's memory ([context](01-concepts.md#4-context-is-the-models-short-term-memory)).

| Mode | How it works | Good for |
|---|---|---|
| **Always listed** | Every tool is described to the model up front | Small plugins |
| **On demand** | The model sees two tools, `find_tools` and `use_tool`, and searches for what it needs | Big plugins |

REA has about 200 tools: far too many for a local model to hold at once. Plugins with more than 25 tools start in on-demand mode automatically. You can switch any plugin with one button.

### Safety

- **A plugin is a program that runs on your PC with your permissions.** Only add plugins you trust, from their official pages.
- **Some plugins act, not just read.** REA can run programs and overwrite files. Its entry tells agents to ask you first, but a local model may not always obey. Don't leave an agent with such a plugin running unattended.
- **Reverse engineer only software you have the right to examine.**
- The hub only answers this PC and its Docker containers, and only with the key.

## Cloud models: Claude and OpenRouter

You can use cloud models alongside your local ones.

**Two things change when you do:**

- **It is no longer private.** Your prompt, and any image you attach, is sent to that company.
- **It costs money**, charged per use to your account with them.

Local models stay the default everywhere. A cloud model is only used where you pick one.

### Add a key

On the **Models** tab, under **Cloud models**:

| Provider | Where to get a key | What you get |
|---|---|---|
| **Claude (Anthropic)** | platform.claude.com | Claude models, direct |
| **OpenRouter** | openrouter.ai | One key for hundreds of models from many companies, Claude included |

Paste the key and press **Save**. Keys are stored in a file on this PC and are never shown again on the page, only their last four characters. Saving a Claude key the first time also installs Anthropic's library, which takes a minute.

For OpenRouter, search for a model and click it to add it to your list. Press **Test** on any cloud model to check it answers.

### Where cloud models can be used

| Place | How |
|---|---|
| **Scheduled jobs** | Pick it in the Model list |
| **3D designs** | Create → Setup → Model that designs 3D objects. A stronger model makes noticeably better designs |
| **Vision** | Create → Setup → Vision model |
| **Chat page** | Add OpenRouter there separately: Admin Settings → Connections → OpenAI API, address `https://openrouter.ai/api/v1`, and your key. That gives the chat page every OpenRouter model, Claude included |
| **App builder** | Enter the model and key in its own LLM settings. A cloud model makes the biggest difference here, since building apps is what local 16 GB models find hardest |

The chat page and app builder keep their own settings, so a key saved in AI Home is not passed to them automatically.

---

Back to the [README](../README.md)
