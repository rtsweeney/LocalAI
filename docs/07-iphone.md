# 07. Using it from your iPhone

You will reach your PC through **Tailscale**. It builds a private, encrypted link between your own devices and nobody else's.

> **Not tested as part of this kit.** These are Tailscale's standard commands, but they have not been run against this setup.

## Why Tailscale, and not "opening a port"

The old way to reach a home PC was to open a port on your router, which exposes it to the whole internet. Don't. Your own site plan says the same: *never open ports on your router*.

With Tailscale, the pages stay invisible to the internet. Only devices signed in to **your** Tailscale account can see them, at home or away.

## Set it up (about ten minutes)

**On the PC**

1. Open **Tailscale** from the Start menu and sign in. Signing in creates your account; the free plan is enough.
2. In PowerShell, share the chat page with your own devices:
   ```powershell
   tailscale serve --bg 3000
   ```
3. The first time, it prints a link to switch on HTTPS for your account. Open it, approve, and run the command again.
4. It prints an address like `https://your-pc.tail1234.ts.net`. That is your AI home's address.

**On the iPhone**

1. Install **Tailscale** from the App Store and sign in with the **same account**.
2. Turn the connection on inside the app.
3. Open your address in **Safari** and sign in with your chat account.
4. Tap **Share → Add to Home Screen**. You now have an icon that opens like an app.

## Reaching the other pages

Tailscale can share three pages at once, on three ports:

| Page | Run on the PC | Open on the iPhone |
|---|---|---|
| Chat | `tailscale serve --bg 3000` | `https://your-pc.tail1234.ts.net` |
| App builder | `tailscale serve --bg --https=8443 3001` | `https://your-pc.tail1234.ts.net:8443/canvas` |
| ComfyUI | `tailscale serve --bg --https=10000 8000` | `https://your-pc.tail1234.ts.net:10000` |

The last number in each command is the port on your PC. ComfyUI Desktop normally uses 8000; check the address it shows if that doesn't work.

To see what is shared: `tailscale serve status`. To stop sharing everything: `tailscale serve reset`.

## Keep the PC awake

Your phone can only reach a PC that is on.

- **Settings → System → Power**: set **Sleep** to **Never** when plugged in. Letting the screen turn off is fine.
- Leave Docker Desktop and Ollama running.

## Keeping it safe

- **Keep the chat sign-in.** Tailscale decides which devices can connect; the chat password decides who can use it. Two locks are better than one.
- **Never use `tailscale funnel`.** It looks similar to `serve` but publishes the page to the entire internet.
- **Lost phone?** Sign in at [login.tailscale.com](https://login.tailscale.com), open **Machines**, and remove it. It loses access immediately.
- **Be careful sharing the app builder.** It can run commands on your PC inside its container. Share it only if you need it away from home.

---

Next: [08. The news desk](08-news-desk.md)
