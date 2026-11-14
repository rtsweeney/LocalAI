# 11. Create: images, photo edits, video, LoRAs, characters, 3D and music

Everything here is on AI Home's **Create** and **Music** tabs.

> **What has been tested.** All of this was tested against a *pretend* ComfyUI and a *pretend* OpenSCAD that answer the way the real ones do. It has **never been run against real ComfyUI, a real image model or a real graphics card.** The parts that depend on ComfyUI's details (finding the right boxes in your workflow) are the most likely to need adjusting. If a job fails, the **Activity** tab shows ComfyUI's own explanation.

## How it works: workflows

Images, video and music are made by **ComfyUI** ([05](05-images-video.md)). ComfyUI describes each kind of job as a **workflow**: a set of boxes wired together, such as "load the model", "read the prompt", "save the image".

There are hundreds of image models and they change monthly, so AI Home doesn't ship its own workflows. You pick one that works on your card, once, and AI Home reuses it, writing your prompt, photo, LoRA and length into the right boxes each time.

### One-time setup, per kind of job

| Job | Start from a ComfyUI template like |
|---|---|
| Make an image | Z-Image Turbo or FLUX.2 klein text-to-image |
| Edit a photo (also used for whole folders) | FLUX.2 klein Image Edit or Qwen-Image-Edit |
| Image to video | Wan 2.2 or LTX image-to-video |
| Music | ACE-Step 1.5 text-to-music |

For each one:

1. In ComfyUI, open **Workflow → Browse Templates** and pick the template.
2. Let it download the models it asks for.
3. Press **Run** once and check you like the result. **If it doesn't work in ComfyUI, it won't work from AI Home.**
4. Choose **Workflow → Export (API)**. This saves a `.json` file. (If you don't see it, turn on *Dev mode* in ComfyUI's settings.)
5. In AI Home, open **Create → Setup** and add that file next to the matching job.

AI Home checks the file as you add it and tells you if it's the wrong kind, for example a normal save instead of an API export, or a text-to-image workflow where an edit workflow is needed.

**Also under Setup:** ComfyUI's address (normally `http://127.0.0.1:8000`) and its models folder (normally `Documents\ComfyUI\models`).

**Which editing model for 16 GB?** FLUX.2 klein 4B is the lightest (about 13 GB). Qwen-Image-Edit fits only in its squeezed "FP8" version. Start with klein.

## Make an image

Type a description and press **Make image**. Results appear in the gallery and in `outputs\images`.

## Edit a whole folder of photos

1. Paste the folder's path. (In File Explorer, click the address bar and copy.)
2. Say what to change: *"make it look like a watercolor painting"*, *"remove the background"*, *"make it night time"*.
3. Press **Edit all photos**.

What to know:

- **Your originals are never changed.** Results go into a new folder beside them called `AI edits` plus the date and time.
- **Only the photos directly in that folder** are edited, not ones in sub-folders.
- **One bad photo doesn't stop the rest.** If the first two both fail, it stops, since something is wrong with the setup.
- A file called `what was done.txt` records the instruction and anything that failed.
- **Try it on a folder of three photos first.** Each photo can take from seconds to a minute, so 500 photos is hours.

## Image to video

Give it an image file and say what should happen. Video is the heaviest job on a 16 GB card: unload your chat model first ([01](01-concepts.md#5-one-big-job-at-a-time)) and expect minutes per clip.

## LoRAs

A **LoRA** is a small add-on file, usually 20 to 300 MB, that teaches an image or video model one new thing: a particular person, a drawing style, a type of object. The big model stays as it is; the LoRA nudges it.

Three things to know:

| | |
|---|---|
| **Each LoRA fits one model family** | A LoRA made for FLUX won't work with SDXL. The page you download it from says which. |
| **Most need a trigger word** | A made-up word you put in your prompt to switch it on. Also on its page. |
| **Strength** | How hard it pushes. 1.0 is normal; 0.6 is subtler; above 1.2 usually distorts. |

**Getting one:** on the LoRAs card, paste a download link from huggingface.co or civitai.com. Civitai needs a free account key for many files: add it on the **Models** tab under Cloud models.

**Only `.safetensors` files are accepted.** Older formats (`.ckpt`, `.pt`) can carry hidden program code that runs when loaded.

**Using one:** your workflow needs a **Load LoRA** box. In ComfyUI, add one between the model loader and the sampler, run it once, and export it again. AI Home then shows that workflow as "takes a LoRA", and the LoRA you pick in a job is written into that box.

## Characters

A **character** is a LoRA trained on photos of one person, so that person can appear in new images and video.

**Only use photos of yourself, or of someone who has agreed.** AI Home asks you to confirm this. Don't make images or video that could be mistaken for something a real person did or said.

### Step 1. Prepare the photos (AI Home does this)

Gather **20 to 30 photos** of the person with variety: front, three-quarter and side views; close-ups and full body; different outfits, expressions, lighting and backgrounds. Variety matters more than quantity.

On the Characters card, give a name and the folder, tick the box, and press **Prepare character**. It:

- removes exact duplicates and warns about small photos,
- writes a caption for each photo with a vision model, describing the pose and setting but deliberately not the person's looks (the trigger word stands for the person),
- makes up a trigger word,
- lays everything out in `characters\<name>\dataset` the way trainers expect, with `NEXT STEPS.txt`.

Read a few captions and fix anything wrong. Bad captions make a worse character.

### Step 2. Train (a separate program; not automated here)

Training is done by a trainer. **This kit does not install or run one**, and no trainer has been tested with it. Guides in November 2026 most often recommend **AI-Toolkit** (by Ostris), and for a 16 GB card suggest training on **Z-Image** or **SDXL** rather than the larger FLUX models. Point the trainer at the `dataset` folder and give it your trigger word. Training takes roughly one to a few hours.

### Step 3. Use it

Put the finished `.safetensors` file in ComfyUI's `models\loras` folder. It then appears in AI Home's LoRA lists. Pick it and include the trigger word in your prompt.

### Putting a character in a video

The dependable route on a 16 GB card:

1. **Make an image** of your character in the scene you want, using the character LoRA.
2. **Image to video** with that image.

The first frame is your character, and the video model keeps them recognisable for a short clip. The likeness can drift as the clip gets longer or the person turns away. Training a LoRA directly for a video model holds better but is slow and tight on 16 GB; treat it as a later project.

## 3D models (CAD)

Describe an object with sizes and press **Design it**. A language model writes the design as **OpenSCAD** code, and OpenSCAD builds it. You get:

- `model.stl` to send to a 3D printer or slicer,
- `model.scad`, the editable design, with the key sizes as named numbers at the top,
- a preview picture when OpenSCAD can draw one.

Install **OpenSCAD** on the Install & remove tab first.

If the design doesn't build, OpenSCAD's error is sent back to the model and it tries again, up to three times.

**What to expect.** This suits brackets, stands, boxes, spacers, hooks and other shapes made of simple solids. It is poor at organic shapes (figurines, faces) and at anything needing precise engineering fits. **Always check the sizes before printing:** the model can produce something that builds perfectly and is the wrong shape. A stronger model helps a lot here; you can choose one, including a cloud model, under Setup.

## Music

On the **Music** tab: describe a style, optionally add lyrics, choose a length, and press **Make music**.

- **Style** is a list of traits: genre, instruments, mood, voice, tempo. *"Upbeat acoustic folk, female vocals, warm guitar, 110 bpm."*
- **Lyrics** are optional. Mark sections with `[verse]`, `[chorus]`, `[bridge]` on their own lines. Leave empty for an instrumental.
- **Length** is 5 to 600 seconds.

Tracks appear below with a player, and in `outputs\music`.

This is song generation from a description, not a multitrack studio: you can't edit individual instruments afterwards. Check the music model's license before publishing tracks.

## Where everything is saved

| What | Where (inside the LocalAI folder) |
|---|---|
| Images, video, music, 3D | `outputs\images`, `outputs\video`, `outputs\music`, `outputs\3d` |
| Bulk photo edits | A new `AI edits …` folder beside your originals |
| Character datasets | `characters\<name>\dataset` |

---

Next: [12. Plugins and cloud models](12-plugins-and-cloud.md)
