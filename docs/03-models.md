# 03. Choosing models from Hugging Face

[Hugging Face](https://huggingface.co) is where almost every open model is published. You can run nearly any of them, as long as it comes in **GGUF** format and fits your card. (Both terms are explained in [01](01-concepts.md).)

## The starter models

`start.ps1` downloads these three. They were chosen by running `fit.py` against the real files on Nov. 14, 2026:

| Model | Used for | File size | Needs, at a normal chat context | Needs, at the app builder's 32k context |
|---|---|---|---|---|
| `gpt-oss:20b` | Main chat, app builder | 10.8 GB | 12.3 GB | 13.8 GB (fits) |
| `gemma4:12b` | Quick chat, news desk | 6.6 GB | 8.1 GB | 9.6 GB (fits) |
| `qwen3-embedding:0.6b` | Grouping news headlines | under 1 GB | | |

Those sizes are for the standard `Q4_K_M` versions on Hugging Face. The copy Ollama downloads under the short name can differ a little.

**Why not something bigger?** OpenHands' own documentation recommends Qwen 3.6 35B for the app builder. On 16 GB its standard version needs about 23.6 GB, so it would spill into RAM and crawl. Only a heavily squeezed 3-bit version fits, and that makes more mistakes. A 20B model at full quality is the better trade on your card.

## Finding and checking a model

**1. Search:**

```powershell
python tools\fit.py search "qwen coder"
```

This lists GGUF repos, most downloaded first.

**2. Check one:**

```powershell
python tools\fit.py unsloth/gemma-4-12b-it-GGUF
```

You get a table of every version in the repo:

```
  version          file    needs   verdict
  Q4_K_M          6.6GB    8.1GB   FITS
  Q6_K            9.1GB   10.6GB   FITS
  Q8_0           11.8GB   13.3GB   FITS
  BF16           22.2GB   23.7GB   TOO BIG

Suggested version: Q4_K_M. Download and chat with it:

  ollama run hf.co/unsloth/gemma-4-12b-it-GGUF:Q4_K_M
```

**3. Copy the last line and run it.** Ollama downloads the model straight from Hugging Face. It then appears in the chat page's model list.

### How the verdict is worked out

```
memory needed = the file's size
              + working memory for the conversation (0.5 GB per 8,192 tokens of context)
              + 1 GB that Windows keeps for your screen
```

It is an estimate. The middle number really depends on each model's design, so treat **TIGHT** as "try it and see".

### Useful options

| Option | When to use it |
|---|---|
| `--context 32768` | Checking a model for the app builder, which needs a long context |
| `--vram 24` | If you upgrade your card |
| `--reserve 0.5` | If nothing else is using the GPU |

## Managing what you've downloaded

| Command | What it does |
|---|---|
| `ollama list` | Shows every model on disk and its size |
| `ollama ps` | Shows what is loaded on the GPU right now |
| `ollama stop NAME` | Unloads a model from the GPU |
| `ollama rm NAME` | Deletes a model from disk |

## Things to watch for

- **Read the license.** Each model's Hugging Face page states one. Apache-2.0 and MIT allow nearly anything. Others restrict commercial use, which matters for a news site that may carry ads.
- **Download counts aren't quality scores.** Prefer the original publisher or a well-known converter (for example `unsloth`, `bartowski`, `lmstudio-community`).
- **Modified models.** Hugging Face has many models altered to remove their refusals (often labeled "abliterated" or "uncensored"). They run the same way. The alteration can also make a model less accurate, so don't use one for the news desk.

---

Next: [04. The app builder](04-app-builder.md)
