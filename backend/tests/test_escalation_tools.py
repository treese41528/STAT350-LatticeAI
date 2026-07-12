"""Escalation tool construction — guards against SDK-signature drift like the
`make_http_get(name=...)` crash that silently broke 'dig deeper'."""

from __future__ import annotations

from genai_studio.agents.tools import make_kb_search_tool
from genai_studio.agents.tools.general import calculator
from genai_studio.agents.tools.http import make_http_get

from app.escalation.tools import make_course_tools


def _tool_name(t) -> str:
    spec = getattr(t, "spec", None)
    return getattr(spec, "name", None) or getattr(t, "name", "?")


def test_course_tools_build_and_are_named(resolver):
    tools = make_course_tools(resolver, term="SPRING 2026", syllabi={})
    names = {_tool_name(t) for t in tools}
    assert {"get_current_term", "get_lecture_url", "get_syllabus_and_schedule",
            "get_exam_info"} <= names


def test_http_get_tool_builds_and_is_named_http_get(resolver):
    # make_http_get takes NO `name` kwarg; the tool is named "http_get". The
    # escalation TOOL_LABELS + prompt must match this name.
    tool = make_http_get(allow_hosts=["treese41528.github.io"])
    assert _tool_name(tool) == "http_get"


def test_the_escalation_tool_set_assembles(resolver):
    # mirror build_agent's tool list (minus the gateway-bound kb_search/client)
    from app.escalation.agent_runner import TOOL_LABELS
    tools = [*make_course_tools(resolver, term="SPRING 2026", syllabi={}),
             calculator, make_http_get(allow_hosts=["x.example"])]
    names = {_tool_name(t) for t in tools}
    # every tool name the agent can emit has a friendly status label
    assert names <= set(TOOL_LABELS) | {"calculator"}
    assert "http_get" in TOOL_LABELS and "get_current_term" in TOOL_LABELS
