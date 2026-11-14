# 01. The five ideas you need

You can run local AI without understanding any of this. But these five ideas explain almost every "why is it slow?" and "why won't it load?" you will ever hit.

## 1. A model is a big file of numbers

A language model is one file, usually 5 to 20 GB. "Running" it means loading that file into memory and doing arithmetic on it. A model's size is given in **parameters**: a "12B" model has 12 billion numbers. More parameters generally means smarter, and bigger.

## 2. VRAM is the limit that matters

Your graphics card has its own memory, called **VRAM**. Yours has 16 GB. A model runs fast only when the whole thing sits in VRAM.

- **Fits in VRAM:** fast. Text appears quicker than you can read.
- **Doesn't fit:** it still runs, but the overflow goes to ordinary memory (RAM), and it gets several times slower.

So the question for every model is: *does it fit in 16 GB?* That is what `tools\fit.py` answers.

## 3. Quantization: the same model, squeezed

A 20B model at full precision needs about 40 GB. To fit home hardware, people publish squeezed versions that store each number with fewer bits. This is **quantization**, and it shows up in file names:

| Name | Bits per number | What to expect |
|---|---|---|
| `Q8_0` | 8 | Nearly identical to the original. Large. |
| `Q6_K` | 6 | Very close to the original. |
| **`Q4_K_M`** | 4 | **The usual choice.** Small loss, about half the size of Q8. |
| `Q3_…`, `Q2_…` | 3, 2 | Noticeably worse. Makes more mistakes. |

**Rule of thumb:** a smaller model at Q4 usually beats a bigger model at Q2 or Q3.

**GGUF** is the file format these squeezed models come in. Ollama needs GGUF. On Hugging Face, look for "GGUF" in the repo name.

## 4. Context is the model's short-term memory

**Context length** is how much text a model can keep in mind at once: your question, the conversation so far, and any documents you gave it. It is counted in **tokens**; a token is about three quarters of a word.

Context uses VRAM too. The same model needs more memory at 32,000 tokens than at 8,000. This is why a model can fit for a quick chat but not for the app builder, which needs a long context. `fit.py` takes this into account with `--context`.

## 5. One big job at a time

Your 16 GB is shared by everything: the chat model, the image model, the video model. They don't fit together. Ollama keeps a model loaded for five minutes after you last used it, so if you chat and then immediately start a video, the video model has no room and crawls.

The fix is simple: before a heavy image or video job, unload the chat model.

```powershell
ollama stop gpt-oss:20b
```

`ollama ps` shows what is loaded right now.

---

Next: [02. Install](02-install.md)
