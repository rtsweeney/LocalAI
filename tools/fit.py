#!/usr/bin/env python3
"""Will this Hugging Face model fit on my GPU?

    python tools/fit.py search "qwen coder"        find GGUF repos on Hugging Face
    python tools/fit.py bartowski/SOME-REPO-GGUF   list every version in a repo, with a verdict
    python tools/fit.py REPO --vram 16 --context 32768

How the verdict is worked out (an estimate, not a guarantee):

    memory needed = size of the model file
                  + working memory for the conversation (grows with --context)
                  + what Windows itself keeps on the GPU for your screen (--reserve)

If that is under your VRAM, the whole model runs on the GPU and is fast. If it is over, Ollama
still runs it, but puts the overflow in ordinary RAM, which is several times slower.

Uses only Python's standard library, so there is nothing to install.
"""
import argparse
import json
import re
import sys
import urllib.parse
import urllib.request

API = "https://huggingface.co/api/models"
GB = 1024 ** 3
# Rough working memory per 8,192 tokens of context. The true figure depends on the model's
# internals, so this errs on the high side for models up to roughly 35B parameters.
CONTEXT_GB_PER_8K = 0.5
SPLIT = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.I)
QUANT = re.compile(r"(?:^|[-._])((?:IQ|Q)\d[A-Z0-9_]*|F16|F32|BF16)(?=[-._]|$)", re.I)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "localai-home-fit/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def variants(files):
    """Group a repo's file list into downloadable versions: [{quant, name, bytes, parts}]."""
    groups = {}
    for f in files:
        path = f.get("path", "")
        if f.get("type") != "file" or not path.lower().endswith(".gguf"):
            continue
        base = path.rsplit("/", 1)[-1]
        if "mmproj" in base.lower():  # the vision add-on file, not a model on its own
            continue
        key = SPLIT.sub(".gguf", path)  # split files (-00001-of-00003) count as one version
        size = (f.get("lfs") or {}).get("size") or f.get("size") or 0
        g = groups.setdefault(key, {"name": key, "bytes": 0, "parts": 0})
        g["bytes"] += size
        g["parts"] += 1
    out = []
    for g in groups.values():
        m = QUANT.search(g["name"].rsplit("/", 1)[-1][: -len(".gguf")])
        g["quant"] = m.group(1).upper() if m else "?"
        out.append(g)
    return sorted(out, key=lambda g: g["bytes"])


def bits(quant):
    """The number in a version name: Q4_K_M -> 4, IQ3_XXS -> 3, F16 -> 16. Unknown -> 0."""
    m = re.search(r"\d+", quant)
    return int(m.group()) if m else 0


def need_gb(file_bytes, context, reserve):
    return file_bytes / GB + CONTEXT_GB_PER_8K * context / 8192 + reserve


def verdict(need, vram):
    if need <= vram - 0.5:
        return "FITS"
    if need <= vram + 0.5:
        return "TIGHT"
    return "TOO BIG"


def cmd_repo(repo, vram, context, reserve):
    try:
        files = get(f"{API}/{repo}/tree/main?recursive=1")
    except Exception as e:  # network trouble, a typo in the name, or a private repo
        sys.exit(f"Could not read {repo} from Hugging Face: {e}\n"
                 f"Check the name is exactly 'owner/repo' as shown at the top of its page.")
    vs = variants(files)
    if not vs:
        sys.exit(f"{repo} has no .gguf files. Ollama needs the GGUF format.\n"
                 f"Try: python tools/fit.py search \"{repo.split('/')[-1]}\"")
    print(f"\n{repo}   (GPU: {vram:g} GB, context: {context:,} tokens, "
          f"kept for Windows: {reserve:g} GB)\n")
    print(f"  {'version':<12}{'file':>9}{'needs':>9}   verdict")
    fits = []
    for v in vs:
        need = need_gb(v["bytes"], context, reserve)
        ver = verdict(need, vram)
        if ver == "FITS":
            fits.append(v)
        label = v["quant"] if v["quant"] != "?" else v["name"].rsplit("/", 1)[-1][:28]
        print(f"  {label:<12}{v['bytes'] / GB:>7.1f}GB{need:>7.1f}GB   {ver}")
    print("\n  FITS    = runs fully on the GPU (fast)")
    print("  TIGHT   = may fit if you close other programs or lower --context")
    print("  TOO BIG = still runs, but spills into normal RAM and gets much slower")
    named = [v for v in fits if v["quant"] != "?"]
    if not named:
        print("\nNothing in this repo fits fully. Look for a smaller model, or lower --context.\n")
        return vs
    # Q4_K_M is the usual balance of quality and size. Above about Q6 the files keep growing
    # but the answers barely improve, so the pick is capped there.
    by_quant = {v["quant"]: v for v in named}
    capped = [v for v in named if bits(v["quant"]) <= 6]
    pick = by_quant.get("Q4_K_M") or (capped[-1] if capped else named[-1])
    print(f"\nSuggested version: {pick['quant']}. Download and chat with it:\n")
    print(f"  ollama run hf.co/{repo}:{pick['quant']}\n")
    if bits(pick["quant"]) < 4:
        print("  Note: versions below Q4 are squeezed hard and make more mistakes.\n"
              "  A smaller model at Q4 usually beats a bigger model at Q2 or Q3.\n")
    elif capped and capped[-1] is not pick and bits(capped[-1]["quant"]) > bits(pick["quant"]):
        print(f"  You have room for {capped[-1]['quant']} too: slightly better answers, "
              f"bigger download.\n")
    return vs


def cmd_search(words, limit):
    q = urllib.parse.urlencode({"search": words, "filter": "gguf", "sort": "downloads",
                                "direction": "-1", "limit": limit})
    rows = get(f"{API}?{q}")
    if not rows:
        sys.exit(f'No GGUF repos found for "{words}". Try fewer or different words.')
    print(f'\nGGUF repos matching "{words}", most downloaded first:\n')
    for r in rows:
        print(f"  {r['id']:<60} {r.get('downloads', 0):>10,} downloads")
    print(f"\nCheck one with:  python tools/fit.py {rows[0]['id']}\n")


def main(argv=None):
    p = argparse.ArgumentParser(description="Will this Hugging Face model fit on my GPU?")
    p.add_argument("target", help='a repo like "owner/name-GGUF", or the word "search"')
    p.add_argument("words", nargs="*", help="search words (only with: search)")
    p.add_argument("--vram", type=float, default=16, help="your GPU memory in GB (default 16)")
    p.add_argument("--context", type=int, default=8192,
                   help="context length in tokens (default 8192; the app builder needs 32768)")
    p.add_argument("--reserve", type=float, default=1.0,
                   help="GB Windows keeps on the GPU for the desktop (default 1.0)")
    p.add_argument("--limit", type=int, default=15, help="how many search results to show")
    a = p.parse_args(argv)
    if a.target == "search":
        if not a.words:
            sys.exit('Say what to search for, like: python tools/fit.py search "qwen coder"')
        cmd_search(" ".join(a.words), a.limit)
    else:
        repo = a.target.replace("https://huggingface.co/", "").replace("hf.co/", "").strip("/")
        cmd_repo(repo, a.vram, a.context, a.reserve)


if __name__ == "__main__":
    main()
