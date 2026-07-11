"""The new CLI verbs for the three faces: ``learn mcp`` and ``learn site``.

Covers the noun overviews (rubric: any noun with action-verbs exposes
``overview``), the two blocking serve verbs (through a test seam so they never
block), and ``site export`` end to end via ``main``.
"""

from __future__ import annotations

import json

import pytest

from learn.cli import main

# --- mcp overview -----------------------------------------------------------


def test_mcp_overview_text(capsys) -> None:
    rc = main(["mcp", "overview"])
    assert rc == 0
    assert "# learn mcp" in capsys.readouterr().out


def test_mcp_overview_json_shape(capsys) -> None:
    rc = main(["mcp", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "learn mcp"
    assert payload["sections"]


def test_mcp_bare_prints_overview(capsys) -> None:
    rc = main(["mcp"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


def test_mcp_serve_runs_stdio_seam(monkeypatch, capsys) -> None:
    seen = {}

    def fake_serve(app):
        seen["name"] = app.name
        seen["tools"] = len(app.list_tools())

    monkeypatch.setattr("learn.cli._commands.mcp._serve_stdio", fake_serve)
    rc = main(["mcp", "serve"])
    assert rc == 0
    assert seen == {"name": "learn", "tools": 9}
    # The launch note is a diagnostic → stderr, never stdout.
    captured = capsys.readouterr()
    assert "stdio" in captured.err
    assert captured.out == ""


# --- site overview ----------------------------------------------------------


def test_site_overview_text(capsys) -> None:
    rc = main(["site", "overview"])
    assert rc == 0
    assert "# learn site" in capsys.readouterr().out


def test_site_overview_json_shape(capsys) -> None:
    rc = main(["site", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "learn site"
    assert payload["sections"]


def test_site_bare_prints_overview(capsys) -> None:
    rc = main(["site"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


def test_site_serve_binds_and_runs_seam(monkeypatch, capsys) -> None:
    served = {}

    def fake_serve_http(server):
        served["address"] = server.server_address

    monkeypatch.setattr("learn.cli._commands.site._serve_http", fake_serve_http)
    # Port 0 → an ephemeral port, so the bind never conflicts.
    rc = main(["site", "serve", "--host", "127.0.0.1", "--port", "0"])
    assert rc == 0
    assert served["address"][0] == "127.0.0.1"
    assert served["address"][1] != 0  # a concrete bound port
    err = capsys.readouterr().err
    assert "http://127.0.0.1:" in err


# --- site export ------------------------------------------------------------


def test_site_export_writes_bundle(tmp_path, install_registry, conformant_prefix) -> None:
    from tests.conftest import entry

    install_registry([entry("fourthlang", conformant_prefix)])
    out = tmp_path / "export"
    rc = main(["site", "export", "--out", str(out)])
    assert rc == 0
    assert (out / "meta.json").exists()
    assert (out / "subjects.json").exists()
    assert (out / "stories-fourthlang.json").exists()
    assert (out / "docs" / "portal.md").exists()


def test_site_export_json_summary(tmp_path, install_registry, conformant_prefix, capsys) -> None:
    from tests.conftest import entry

    install_registry([entry("fourthlang", conformant_prefix)])
    out = tmp_path / "export"
    rc = main(["site", "export", "--out", str(out), "--json"])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["contract_version"] == "1.0"
    assert summary["subjects"] == ["fourthlang"]
    assert "meta.json" in summary["files"]


def test_site_export_requires_out(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["site", "export"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


# --- structured error routing for new nouns ---------------------------------


def test_site_overview_unknown_flag_structured_error(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["site", "overview", "--bogus"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


# --- explain entries for the new paths --------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ["mcp"],
        ["mcp", "overview"],
        ["mcp", "serve"],
        ["site"],
        ["site", "overview"],
        ["site", "serve"],
        ["site", "export"],
    ],
)
def test_explain_entries_for_new_paths(path, capsys) -> None:
    rc = main(["explain", *path])
    assert rc == 0
    assert capsys.readouterr().out.startswith("#")
