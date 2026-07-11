"""``learn mcp`` — the MCP face of the portal.

``mcp serve`` runs agentfront's single-dispatch MCP server over stdio: one
``run`` tool whose catalog is every tool in the portal's App registry
(:func:`learn.front.build_app`), so an agent can drive a full learning loop
(list subjects, read a story, get a lesson, record a result) over MCP without
learn-cli writing any MCP-protocol code.

``mcp overview`` describes the noun — the agent-first rubric requires an
``overview`` on any noun with action-verbs.
"""

from __future__ import annotations

import argparse

from learn.cli._commands.overview import emit_overview
from learn.cli._errors import EXIT_ENV_ERROR, EXIT_SUCCESS, CliError
from learn.cli._output import emit_diagnostic

#: Shared ``--json`` help text (repeated per subparser below).
_JSON_HELP = "Emit structured JSON."


def _mcp_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "Verbs",
            "items": [
                "mcp serve — run the MCP server over stdio (single 'run' dispatch tool)",
                "mcp overview — describe this noun (you are here)",
            ],
        },
        {
            "title": "How the MCP face works",
            "items": [
                "one App registry backs the CLI, MCP, and HTTP faces — they cannot drift",
                "the server exposes ONE 'run' tool; its description embeds the command catalog",
                "an agent calls run({command:[...], args:{...}}) to drive a subject verb",
                "tools: subjects_list, subject_doctor, story_list, story_read, progress, "
                "advice, lesson_next, practice, record",
            ],
        },
        {
            "title": "Conventions",
            "items": [
                "stdio transport (blocking); wire it into an MCP client's server config",
                "results are the subject's --json payloads; errors carry {code, message, "
                "remediation}",
                "needs agentfront's 'mcp' extra (a runtime dependency of learn-cli)",
            ],
        },
    ]


def cmd_mcp_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "learn mcp",
        _mcp_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return EXIT_SUCCESS


def _serve_stdio(app: object) -> None:
    """Blocking stdio MCP serve — a seam tests replace so they never block on stdin."""
    from agentfront.mcp_surface import serve_stdio

    serve_stdio(app)


def cmd_mcp_serve(args: argparse.Namespace) -> int:
    from learn.front import build_app

    app = build_app()
    emit_diagnostic(
        f"learn mcp serve: {len(app.list_tools())} tools over stdio "
        "(single 'run' dispatch tool); Ctrl-C to stop"
    )
    try:
        _serve_stdio(app)
    except ModuleNotFoundError as err:
        if (getattr(err, "name", "") or "").split(".", 1)[0] != "mcp":
            raise
        raise CliError(
            code=EXIT_ENV_ERROR,
            message="the MCP face needs agentfront's 'mcp' extra, which is not installed",
            remediation="install it with: uv add 'agentfront[mcp]'",
        ) from err
    except KeyboardInterrupt:  # pragma: no cover - interactive stop
        emit_diagnostic("learn mcp serve: stopped")
    return EXIT_SUCCESS


def _no_verb(args: argparse.Namespace) -> int:
    # `learn mcp` with no sub-verb prints the noun's overview.
    return cmd_mcp_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "mcp",
        help="The MCP face — serve the portal's tools over MCP (see 'learn mcp overview').",
    )
    p.add_argument("--json", action="store_true", help=_JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="mcp_command", parser_class=type(p))

    ov = noun_sub.add_parser("overview", help="Describe the MCP noun and its tools.")
    ov.add_argument("--json", action="store_true", help=_JSON_HELP)
    ov.set_defaults(func=cmd_mcp_overview)

    serve = noun_sub.add_parser(
        "serve",
        help="Run the MCP server over stdio (single 'run' dispatch tool).",
    )
    serve.add_argument("--json", action="store_true", help=_JSON_HELP)
    serve.set_defaults(func=cmd_mcp_serve)
