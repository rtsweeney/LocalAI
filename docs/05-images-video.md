# 05. Images and video

**ComfyUI** is the standard program for making images and video on your own card. It is not installed by `setup.ps1`, because its own installer does a better job of matching your graphics card.

> **Not tested as part of this kit.** The model names below are what guides were recommending for 16 GB cards in November 2026. This area changes monthly, so trust ComfyUI's own template list over this page.

## Install

1. Download **ComfyUI Desktop** from [comfy.org/download](https://www.comfy.org/download).
2. Run it and choose **NVIDIA** when asked about your graphics card.
3. Let it pick the default folder. Models go there, and they are large.

## Free the card first

Before a big image or video job, unload the chat model so ComfyUI gets all 16 GB ([why](01-concepts.md#5-one-big-job-at-a-time)):

```powershell
ollama ps
```

```powershell
ollama stop gpt-oss:20b
```

## Your first image

ComfyUI works with **workflows**: diagrams of boxes joined by lines, where each box does one step. You don't need to build one. Use a ready-made template:

1. Open **Workflow → Browse Templates**.
2. Pick an image template.
3. If it says models are missing, click to download them. This is the slow part, once per model.
4. Type what you want in the **prompt** box and press **Run**.

## What fits in 16 GB

| For | Look for templates named | Notes |
|---|---|---|
| Fast images | Z-Image Turbo, SDXL | Seconds per image |
| Best images | FLUX.2 (the smaller "klein" versions) | Slower; check each model's license |
| Video, lighter | Wan 2.2 5B | The safest place to start |
| Video, best | LTX-2.3 (an "FP8" version) | FP8 is a squeezed version, like [quantization](01-concepts.md#3-quantization-the-same-model-squeezed). Guides suggest 64 GB of ordinary RAM as well |

**Set expectations for video.** A few seconds of footage takes minutes to make, and 16 GB is the low end. Start with short, low-resolution clips to learn what works, then scale up.

## If it runs out of memory

- Unload the chat model (above).
- Close browsers and games; they use VRAM too.
- Choose a smaller resolution or fewer frames.
- Choose a template marked FP8 or GGUF, which are the squeezed versions.

## Licenses

Each image and video model has its own license, and several forbid commercial use. Check before using generated images on your news site.

---

Next: [06. Voices and audiobooks](06-voices-audiobooks.md)
