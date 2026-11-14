"""One way to ask any model a question: local (Ollama), Claude, or anything on OpenRouter.

A model is named by a short spec:

    gemma4:12b                         a local model in Ollama
    claude:claude-opus-5-5             a Claude model, using your Anthropic API key
    openrouter:google/gemini-pro       any model on OpenRouter, using your OpenRouter key

Local models keep everything on this PC. Cloud models send your prompt (and any image you
attach) to that company, and cost money per use.
"""
import base64
import json
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path

CLAUDE_DEFAULT = "claude-opus-5-5"
# Shown if the live list can't be fetched. The panel normally asks the API for the current list.
CLAUDE_KNOWN = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2"]
# Models that can hand a declined request to another model inside the same call.
CLAUDE_FALLBACK = ("claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")
OPENROUTER = "https://openrouter.ai/api/v1"
KEY_NAMES = {"anthropic": "Claude (Anthropic)", "openrouter": "OpenRouter", "civitai": "Civitai (for LoRA downloads)"}


class ModelError(Exception):
    """A problem worth showing the user as-is."""


class Keys:
    """Your API keys, kept in a file on this PC and never sent back to the browser."""

    def __init__(self, path):
        self.path = Path(path)

    def all(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def get(self, name):
        return self.all().get(name) or None

    def set(self, name, value):
        if name not in KEY_NAMES:
            raise ModelError("Unknown key.")
        keys = self.all()
        value = (value or "").strip()
        if value:
            keys[name] = value
        else:
            keys.pop(name, None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(keys), encoding="utf-8")
        tmp.replace(self.path)

    def view(self):
        """What the page may see: whether each key is set and its last four characters."""
        keys = self.all()
        return [{"id": k, "name": v, "set": bool(keys.get(k)), "tail": keys[k][-4:] if keys.get(k) else ""}
                for k, v in KEY_NAMES.items()]


def split(spec):
    for prefix in ("claude", "openrouter"):
        if spec.startswith(prefix + ":"):
            return prefix, spec[len(prefix) + 1:]
    return "ollama", spec


def image_b64(path):
    kind = mimetypes.guess_type(str(path))[0] or "image/png"
    return kind, base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")


def http_json(url, body=None, headers=None, timeout=600):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


class Providers:
    def __init__(self, keys, ollama, anthropic_base=None, openrouter_base=OPENROUTER):
        # anthropic_base exists only so tests can point the SDK at a pretend server.
        self.keys, self.ollama, self.anthropic_base, self.openrouter_base = keys, ollama, anthropic_base, openrouter_base

    # ---------------------------------------------------------------- asking

    def chat(self, spec, prompt, images=(), system=None, timeout=1800):
        """Ask one question, fresh, and return the answer as text."""
        provider, model = split(spec)
        if provider == "claude":
            return self.ask_claude(model or CLAUDE_DEFAULT, prompt, images, system)
        if provider == "openrouter":
            return self.ask_openrouter(model, prompt, images, system, timeout)
        return self.ask_ollama(model, prompt, images, system, timeout)

    def ask_ollama(self, model, prompt, images, system, timeout):
        msg = {"role": "user", "content": prompt}
        if images:
            msg["images"] = [image_b64(p)[1] for p in images]
        messages = ([{"role": "system", "content": system}] if system else []) + [msg]
        try:
            r = http_json(self.ollama + "/api/chat", {"model": model, "stream": False, "messages": messages}, timeout=timeout)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise ModelError(f"Ollama could not run {model}: {detail or e}") from None
        except (urllib.error.URLError, OSError) as e:
            raise ModelError(f"Could not reach Ollama ({getattr(e, 'reason', e)}). Is it running?") from None
        return (r.get("message", {}).get("content") or "").strip()

    def claude_client(self):
        key = self.keys.get("anthropic")
        if not key:
            raise ModelError("No Claude API key yet. Add one on the Models tab.")
        try:
            import anthropic
        except ImportError:
            raise ModelError("The Claude library isn't installed yet. On the Models tab, save your Claude key "
                             "again and wait for the install to finish.") from None
        extra = {"base_url": self.anthropic_base} if self.anthropic_base else {}
        return anthropic, anthropic.Anthropic(api_key=key, **extra)

    def ask_claude(self, model, prompt, images, system):
        anthropic, client = self.claude_client()
        content = [{"type": "image", "source": {"type": "base64", "media_type": kind, "data": data}}
                   for kind, data in map(image_b64, images)] + [{"type": "text", "text": prompt}]
        params = {"model": model, "max_tokens": 16000, "thinking": {"type": "adaptive"},
                  "messages": [{"role": "user", "content": content}]}
        if system:
            params["system"] = system
        try:
            if model in CLAUDE_FALLBACK:
                # If the model declines a request, let the API retry it on another Claude model.
                response = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                                       fallbacks="default", **params)
            else:
                response = client.messages.create(**params)
        except anthropic.AuthenticationError:
            raise ModelError("Claude rejected the API key. Check it on the Models tab.") from None
        except anthropic.PermissionDeniedError:
            raise ModelError("This Claude API key isn't allowed to use that model.") from None
        except anthropic.NotFoundError:
            raise ModelError(f"Claude doesn't know a model called {model}.") from None
        except anthropic.RateLimitError:
            raise ModelError("Claude says you've hit a rate limit. Try again in a minute.") from None
        except anthropic.BadRequestError as e:
            raise ModelError(f"Claude refused the request: {e.message}") from None
        except anthropic.APIStatusError as e:
            raise ModelError(f"Claude's servers returned an error ({e.status_code}). Try again later.") from None
        except anthropic.APIConnectionError:
            raise ModelError("Could not reach Claude. Check the internet connection.") from None
        if response.stop_reason == "refusal":
            raise ModelError("Claude declined this request.")
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if response.stop_reason == "max_tokens":
            text += "\n\n(The answer was cut off because it reached the length limit.)"
        return text

    def ask_openrouter(self, model, prompt, images, system, timeout):
        key = self.keys.get("openrouter")
        if not key:
            raise ModelError("No OpenRouter key yet. Add one on the Models tab.")
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": f"data:{kind};base64,{data}"}} for kind, data in map(image_b64, images)]
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": content if images else prompt}]
        try:
            r = http_json(self.openrouter_base + "/chat/completions", {"model": model, "messages": messages},
                          {"Authorization": "Bearer " + key, "X-Title": "AI Home"}, timeout)
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("error", {}).get("message", "")
            except ValueError:
                detail = ""
            reason = {401: "OpenRouter rejected the key. Check it on the Models tab.",
                      402: "Your OpenRouter account is out of credit.",
                      404: f"OpenRouter doesn't know a model called {model}.",
                      429: "OpenRouter says you've hit a rate limit. Try again in a minute."}.get(e.code)
            raise ModelError(reason or f"OpenRouter returned an error ({e.code}): {detail}") from None
        except (urllib.error.URLError, OSError) as e:
            raise ModelError(f"Could not reach OpenRouter ({getattr(e, 'reason', e)}).") from None
        if r.get("error"):
            raise ModelError("OpenRouter returned an error: " + str(r["error"].get("message", r["error"])))
        try:
            return (r["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            raise ModelError("OpenRouter sent back an answer I couldn't read.") from None

    # ---------------------------------------------------------------- listing

    def claude_models(self):
        if not self.keys.get("anthropic"):
            return []
        try:
            _, client = self.claude_client()
            return [m.id for m in client.models.list()][:40] or CLAUDE_KNOWN
        except Exception:
            return CLAUDE_KNOWN

    def openrouter_models(self, query=""):
        """OpenRouter's catalog, filtered by a search word. The list is public; no key needed."""
        try:
            rows = http_json(self.openrouter_base + "/models", timeout=30).get("data", [])
        except Exception as e:
            raise ModelError(f"Could not read OpenRouter's model list ({e}).") from None
        q = query.lower().strip()
        return [{"id": m["id"], "name": m.get("name", m["id"])} for m in rows
                if not q or q in m["id"].lower() or q in str(m.get("name", "")).lower()][:30]

    def vision_models(self):
        """Local models that can look at images, found by asking Ollama about each one."""
        out = []
        try:
            for m in http_json(self.ollama + "/api/tags", timeout=5).get("models", []):
                info = http_json(self.ollama + "/api/show", {"model": m["name"]}, timeout=10)
                if "vision" in (info.get("capabilities") or []):
                    out.append(m["name"])
        except Exception:
            pass
        return out
