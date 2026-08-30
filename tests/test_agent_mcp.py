"""AGENT-MCP — MCP client (discover/call), policy gating, loop integration. No network."""
from __future__ import annotations

from glitch_signal.agent.loop import run
from glitch_signal.agent.loop.policy import Policy
from glitch_signal.agent.mcp import MCPManager, ServerSpec, parse_servers


# ── config parsing ────────────────────────────────────────────────────
def test_parse_servers_valid():
    raw = '[{"name":"heygen","url":"https://mcp.heygen.com/mcp","headers":{"X-Api-Key":"k"}}]'
    servers = parse_servers(raw)
    assert servers == [ServerSpec("heygen", "https://mcp.heygen.com/mcp", {"X-Api-Key": "k"})]


def test_parse_servers_empty_and_bad():
    assert parse_servers("") == []
    assert parse_servers("not json") == []
    assert parse_servers('[{"name":"x"}]') == []          # missing url → dropped


# ── MCPManager discover + call (fake connector) ───────────────────────
class _Tool:
    def __init__(self, name, desc):
        self.name = name
        self.description = desc


class _ToolsResp:
    def __init__(self, tools):
        self.tools = tools


class _Block:
    def __init__(self, text):
        self.text = text


class _CallResult:
    def __init__(self, text, is_error=False):
        self.content = [_Block(text)]
        self.isError = is_error


class _Session:
    def __init__(self, tools):
        self._tools = tools
        self.called = []

    async def initialize(self):
        pass

    async def list_tools(self):
        return _ToolsResp(self._tools)

    async def call_tool(self, name, arguments):
        self.called.append((name, arguments))
        if name == "boom":
            return _CallResult("it failed", is_error=True)
        return _CallResult(f"ran {name}")


def _connector_with(tools):
    async def _c(spec, stack):
        return _Session(tools)
    return _c


async def test_manager_discovers_and_namespaces_tools():
    mgr = MCPManager([ServerSpec("heygen", "http://x")],
                     connector=_connector_with([_Tool("list_avatars", "list em")]))
    async with mgr:
        desc = mgr.tool_descriptions()
        assert "mcp__heygen__list_avatars" in desc
        assert mgr.has("mcp__heygen__list_avatars")
        out = await mgr.call("mcp__heygen__list_avatars", {})
    assert out == "ran list_avatars"                       # namespaced → underlying tool name


async def test_manager_reports_tool_error():
    mgr = MCPManager([ServerSpec("s", "http://x")], connector=_connector_with([_Tool("boom", "d")]))
    async with mgr:
        out = await mgr.call("mcp__s__boom", {})
    assert out.startswith("ERROR")


async def test_manager_one_bad_server_does_not_kill_others():
    async def _c(spec, stack):
        if spec.name == "bad":
            raise RuntimeError("unreachable")
        return _Session([_Tool("ok_tool", "d")])

    mgr = MCPManager([ServerSpec("bad", "http://b"), ServerSpec("good", "http://g")], connector=_c)
    async with mgr:
        assert mgr.has("mcp__good__ok_tool")               # good server still discovered
        assert not any(k.startswith("mcp__bad__") for k in mgr.tool_descriptions())


# ── policy gating of MCP tools ────────────────────────────────────────
def test_policy_allows_benign_mcp_tool():
    assert Policy().check("mcp__heygen__list_avatars", {}, "b").allow is True


def test_policy_denies_side_effect_mcp_tool():
    d = Policy(publish_enabled=False).check("mcp__heygen__delete_avatar", {}, "b")
    assert d.allow is False and "not allowlisted" in d.reason


def test_policy_default_denies_unknown_write_mcp_tool():
    # #93: a create/write tool with no matching denylist verb is DENIED by default (leaky-denylist fix)
    d = Policy(publish_enabled=False).check("mcp__notion__notion-create-pages", {}, "b")
    assert d.allow is False
    assert Policy(publish_enabled=False).check("mcp__heygen__get_video", {}, "b").allow is True  # read-only ok


def test_policy_publishing_on_permits_mcp_side_effects():
    assert Policy(publish_enabled=True).check("mcp__heygen__create_video_agent", {}, "b").allow is True


def test_policy_mcp_allowlist_overrides_deny():
    p = Policy(mcp_allow={"b": frozenset({"mcp__x__send_email"})})
    assert p.check("mcp__x__send_email", {}, "b").allow is True         # allowlisted
    assert p.check("mcp__x__send_email", {}, "other").allow is False    # not for other brand


# ── loop uses MCP tools, gated (native tool use) ──────────────────────
def _use(name, inp=None, tid="t1"):
    return {"stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp or {}}]}


def _done(text):
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}


class _LLM:
    def __init__(self, responses):
        self.responses = list(responses)

    async def __call__(self, messages, *, tools=None, system=None):
        return self.responses.pop(0) if self.responses else _done("(out)")


class _Exec:
    def __init__(self):
        self.calls = []

    async def __call__(self, tool, args, brand_id):
        self.calls.append((tool, args))
        return {"recall": "[]"}.get(tool, f"ran {tool}")


class _FakeMCP:
    def __init__(self, tools):
        self._tools = tools                                 # {ns: description}
        self.calls = []

    def tool_descriptions(self):
        return self._tools

    def tool_defs(self):
        return [{"name": ns, "description": d, "input_schema": {"type": "object"}}
                for ns, d in self._tools.items()]

    def has(self, n):
        return n in self._tools

    async def call(self, n, args):
        self.calls.append((n, args))
        return f"mcp:{n}"


async def test_loop_calls_benign_mcp_tool():
    llm = _LLM([_use("mcp__heygen__list_avatars", {}), _done("listed")])
    mcp = _FakeMCP({"mcp__heygen__list_avatars": "list", "mcp__heygen__delete_avatar": "del"})
    res = await run("glitch_executor", "list avatars", llm=llm, execute=_Exec(), mcp=mcp, scope="full")
    assert res["final"] == "listed"
    assert mcp.calls and mcp.calls[0][0] == "mcp__heygen__list_avatars"


async def test_loop_denies_side_effect_mcp_tool():
    llm = _LLM([_use("mcp__heygen__delete_avatar", {}), _done("stopped")])
    mcp = _FakeMCP({"mcp__heygen__delete_avatar": "del"})
    res = await run("glitch_executor", "delete it", llm=llm, execute=_Exec(), mcp=mcp, scope="full")
    assert res["transcript"][0]["observation"].startswith("DENIED")
    assert not mcp.calls                                    # never executed
