"""Tests for the plugin hub.

The important ones use the official MCP library (pip install mcp) on BOTH sides: its client
connects to the hub, and a plugin built with it runs underneath the hub. That checks the hub
against the real protocol, not just against itself. They are skipped if the library is absent.
"""
import asyncio
import json
import sys
import tempfile
import textwrap
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "home"))
import gateway as g  # noqa: E402

try:
    from mcp import ClientSession
    import mcp.client.streamable_http as mcp_http
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False


def failed(result):
    return getattr(result, "is_error", None) if hasattr(result, "is_error") else result.isError


def open_client(url, token):
    """The library renamed its client between versions 1 and 2; support both."""
    headers = {"Authorization": "Bearer " + token}
    if hasattr(mcp_http, "streamable_http_client"):
        return mcp_http.streamable_http_client(url, http_client=mcp_http.create_mcp_http_client(headers=headers))
    return mcp_http.streamablehttp_client(url, headers=headers)

PLUGIN = textwrap.dedent('''
    try:
        from mcp.server.mcpserver import MCPServer as Server   # library version 2
    except ImportError:
        from mcp.server.fastmcp import FastMCP as Server       # library version 1
    m = Server("demo")
    @m.tool()
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b
    @m.tool()
    def shout(text: str) -> str:
        """Make text loud."""
        return text.upper() + "!"
    m.run()
''')
HELLO = {"name": "hello", "description": "Say hello", "inputSchema": {"type": "object", "properties": {"who": {"type": "string"}}},
         "run": lambda a: "hello " + a.get("who", "you")}
BOOM = {"name": "boom", "description": "Always fails", "inputSchema": {"type": "object"},
        "run": lambda a: (_ for _ in ()).throw(RuntimeError("it broke"))}


class HubBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "plug.py").write_text(PLUGIN)
        self.hub = g.Hub(self.dir / "data", builtins=[HELLO, BOOM])
        self.addCleanup(self.hub.stop_all)
        self.server = g.serve_hub(self.hub, 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}/mcp"

    def demo(self):
        return self.hub.add("Demo", command=f'"{sys.executable}" "{self.dir / "plug.py"}"')

    def post(self, body, token=None, host=None, path="/mcp"):
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + (token or self.hub.token)}
        if host:
            headers["Host"] = host
        req = urllib.request.Request(self.url.replace("/mcp", path), json.dumps(body).encode(), headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            return e.code, None


@unittest.skipUnless(HAVE_MCP, "pip install mcp to run the real-protocol tests")
class RealProtocolTest(HubBase):
    def session(self, work):
        async def main():
            async with open_client(self.url, self.hub.token) as streams:
                async with ClientSession(streams[0], streams[1]) as s:
                    init = await s.initialize()
                    return await work(s, init)
        return asyncio.run(main())

    def test_official_client_sees_and_calls_builtin_and_plugin_tools(self):
        self.demo()

        async def work(s, init):
            self.assertEqual((getattr(init, "server_info", None) or init.serverInfo).name, "ai-home")
            names = [t.name for t in (await s.list_tools()).tools]
            self.assertEqual(names, ["hello", "boom", "demo__add", "demo__shout"])
            add = await s.call_tool("demo__add", {"a": 2, "b": 40})
            self.assertEqual((add.content[0].text, bool(failed(add))), ("42", False))
            self.assertEqual((await s.call_tool("hello", {"who": "Ryan"})).content[0].text, "hello Ryan")
            boom = await s.call_tool("boom", {})
            self.assertTrue(failed(boom))  # a failing tool reports the failure; the session survives
            self.assertIn("it broke", boom.content[0].text)
            self.assertTrue(failed(await s.call_tool("nope", {})))
            self.assertEqual((await s.call_tool("hello", {})).content[0].text, "hello you")
        self.session(work)

    def test_on_demand_mode_hides_tools_behind_find_and_use(self):
        p = self.demo()
        self.hub.connect(p)
        self.hub.change(p["id"], "on_demand")

        async def work(s, init):
            names = [t.name for t in (await s.list_tools()).tools]
            self.assertEqual(names, ["hello", "boom", "find_tools", "use_tool"])
            found = json.loads((await s.call_tool("find_tools", {"query": "loud text"})).content[0].text)
            self.assertEqual(found[0]["name"], "demo__shout")
            self.assertIn("text", found[0]["arguments"])
            used = await s.call_tool("use_tool", {"name": "demo__shout", "arguments": {"text": "hi"}})
            self.assertEqual(used.content[0].text, "HI!")
            self.assertIn("No tools matched", (await s.call_tool("find_tools", {"query": "zzz"})).content[0].text)
        self.session(work)

    def test_plugin_that_dies_is_restarted_on_next_use(self):
        p = self.demo()
        self.hub.connect(p)
        self.hub.live[p["id"]].proc.kill()
        self.hub.live[p["id"]].proc.wait()
        self.assertFalse(self.hub.view()[0]["running"])
        out = self.hub.call("demo__add", {"a": 1, "b": 1})
        self.assertEqual(out["content"][0]["text"], "2")

    def test_big_plugins_default_to_on_demand(self):
        p = self.demo()
        self.hub.connect(p)
        self.assertFalse(self.hub.is_on_demand(p))  # 2 tools: listed normally
        self.hub.tools[p["id"]] = [{"name": f"t{i}", "description": ""} for i in range(g.ON_DEMAND_ABOVE + 1)]
        self.assertTrue(self.hub.is_on_demand(p))   # a REA-sized plugin: on demand without being told


class HubRulesTest(HubBase):
    def test_wrong_key_wrong_host_and_wrong_path_are_refused(self):
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        self.assertEqual(self.post(init, token="wrong")[0], 401)
        self.assertEqual(self.post(init, host="evil.example")[0], 401)
        self.assertEqual(self.post(init, path="/other")[0], 404)
        self.assertEqual(self.post(init)[0], 200)
        self.assertEqual(self.post(init, host="host.docker.internal:3011")[0], 200)  # from a Docker container

    def test_protocol_basics_without_the_library(self):
        code, r = self.post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}})
        self.assertEqual(r["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(self.post({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999"}})[1]["result"]["protocolVersion"], g.PROTOCOL)
        self.assertEqual(self.post({"jsonrpc": "2.0", "method": "notifications/initialized"}), (202, None))
        self.assertEqual(self.post({"jsonrpc": "2.0", "id": 3, "method": "ping"})[1]["result"], {})
        self.assertEqual(self.post({"jsonrpc": "2.0", "id": 4, "method": "resources/list"})[1]["error"]["code"], -32601)

    def test_broken_plugin_is_reported_and_does_not_hide_the_working_tools(self):
        bad = self.hub.add("Broken", command="this-program-does-not-exist --x")
        names = [t["name"] for t in self.hub.list_tools()]
        self.assertEqual(names, ["hello", "boom"])
        view = self.hub.view()[0]
        self.assertEqual((view["running"], view["tools"]), (False, None))
        self.assertIn("not installed", view["error"])
        self.hub.change(bad["id"], "remove")
        self.assertEqual(self.hub.view(), [])

    def test_plugins_are_saved_and_instructions_reach_the_agent(self):
        self.hub.add("REA", command="npx -y rea-agents@6.7.0 mcp", instructions="Ask before running anything.")
        again = g.Hub(self.dir / "data")
        self.assertEqual([(p["id"], p["command"]) for p in again.plugins], [("rea", "npx -y rea-agents@6.7.0 mcp")])
        self.assertEqual(again.token, self.hub.token)  # agents stay connected across restarts
        self.assertIn("REA: Ask before running anything.", again.instructions())
        again.change("rea", "toggle")
        self.assertNotIn("Ask before", again.instructions())

    def test_bad_plugin_entries_are_refused(self):
        for kw in ({"name": ""}, {"name": "x"}, {"name": "x", "command": "a", "url": "http://b"},
                   {"name": "x", "url": "ftp://b"}):
            with self.assertRaises(g.PluginError):
                self.hub.add(**kw)
        a, b = self.hub.add("Same Name", url="http://127.0.0.1:1/mcp"), self.hub.add("Same Name", url="http://127.0.0.1:2/mcp")
        self.assertNotEqual(a["id"], b["id"])


if __name__ == "__main__":
    unittest.main()
