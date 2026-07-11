"""``learn site`` — the HTTP face of the portal, plus the static-site export.

* ``site serve [--host --port]`` — run the agent-readable HTTP site: the portal's
  docs as markdown (``/<slug>``, ``/sitemap.xml``, ``/llms.txt``, ``/front``),
  derived from the same App registry the CLI and MCP faces read.
* ``site export --out <dir>`` — write the pinned static content bundle
  (``meta.json``, ``subjects.json``, ``stories-<subject>.json``, ``docs/<slug>.md``)
  that the Astro site build consumes. Deterministic; never reads the wall clock.
* ``site overview`` — describe the noun (the rubric requires ``overview`` on any
  noun with action-verbs).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from learn.cli._commands.overview import emit_overview
from learn.cli._errors import EXIT_SUCCESS
from learn.cli._output import emit_diagnostic, emit_result


def _site_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "Verbs",
            "items": [
                "site serve [--host --port] — serve the portal docs as an agent-readable "
                "markdown site",
                "site export --out <dir> — write the static content bundle for the web build",
                "site overview — describe this noun (you are here)",
            ],
        },
        {
            "title": "HTTP routes",
            "items": [
                "GET /<slug> — a doc page as markdown (portal, subject-plugin-contract, "
                "subjects)",
                "GET /sitemap.xml — every doc; GET /llms.txt — the agent entry point",
                "GET /front — the live-cockpit view as markdown",
            ],
        },
        {
            "title": "Export format (consumed by the Astro site)",
            "items": [
                "meta.json — {contract_version, schema_version, subjects}",
                "subjects.json — [{name, display_name, description, repo, available, modules}]",
                "stories-<subject>.json — {subject, stories:[...]} per available subject",
                "docs/<slug>.md — every registered doc page",
            ],
        },
    ]


def cmd_site_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "learn site",
        _site_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return EXIT_SUCCESS


def _serve_http(server: object) -> None:
    """Blocking HTTP serve — a seam tests replace so they never block forever."""
    server.serve_forever()  # type: ignore[attr-defined]


def cmd_site_serve(args: argparse.Namespace) -> int:
    from agentfront.http_surface import serve

    from learn.front import build_app

    app = build_app()
    server = serve(app, args.host, args.port)
    host, port = server.server_address[0], server.server_address[1]
    emit_diagnostic(
        f"learn site serve: http://{host}:{port}/ "
        f"({len(app.list_docs())} docs, /sitemap.xml, /llms.txt, /front); Ctrl-C to stop"
    )
    try:
        _serve_http(server)
    except KeyboardInterrupt:  # pragma: no cover - interactive stop
        emit_diagnostic("learn site serve: stopped")
    finally:
        server.server_close()
    return EXIT_SUCCESS


def cmd_site_export(args: argparse.Namespace) -> int:
    from learn.front._export import export_site

    json_mode = bool(getattr(args, "json", False))
    summary = export_site(Path(args.out))
    if json_mode:
        emit_result(summary, json_mode=True)
    else:
        lines = [
            f"learn site export → {summary['out']}",
            f"  contract_version: {summary['contract_version']}",
            f"  subjects: {', '.join(summary['subjects']) or '(none)'}",
            f"  files ({len(summary['files'])}):",
        ]
        lines += [f"    {f}" for f in summary["files"]]
        emit_result("\n".join(lines), json_mode=False)
    return EXIT_SUCCESS


def _no_verb(args: argparse.Namespace) -> int:
    # `learn site` with no sub-verb prints the noun's overview.
    return cmd_site_overview(args)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "site",
        help="The HTTP face + static export (see 'learn site overview').",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=_no_verb, json=False)
    noun_sub = p.add_subparsers(dest="site_command", parser_class=type(p))

    ov = noun_sub.add_parser("overview", help="Describe the site noun, routes, and export format.")
    ov.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ov.set_defaults(func=cmd_site_overview)

    serve = noun_sub.add_parser("serve", help="Serve the portal docs as a markdown HTTP site.")
    serve.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1).")
    serve.add_argument("--port", type=int, default=8080, help="Bind port (default 8080; 0 = any).")
    serve.add_argument("--json", action="store_true", help="Emit structured JSON.")
    serve.set_defaults(func=cmd_site_serve)

    export = noun_sub.add_parser(
        "export",
        help="Write the pinned static content bundle for the Astro site build.",
    )
    export.add_argument("--out", required=True, help="Output directory (created if absent).")
    export.add_argument("--json", action="store_true", help="Emit structured JSON.")
    export.set_defaults(func=cmd_site_export)
