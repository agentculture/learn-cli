"""``learn site export`` — the pinned static bundle the Astro site consumes.

Locks the export to the exact shape t13 builds against: the four file kinds,
their keys, registry-order subjects, best-effort modules, available-only story
files, determinism (byte-identical re-run), and the never-fail-on-missing-subject
guarantee.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from learn.front._export import export_site
from tests.conftest import entry


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _stub(tmp_path: Path, name: str, body: str) -> dict:
    """Write an executable subject stub and return its registry entry dict."""
    path = tmp_path / f"{name}.py"
    path.write_text("#!/usr/bin/env python3\nimport sys, json\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return entry(name, [str(path)])


@pytest.fixture
def mixed_registry(install_registry, conformant_prefix):
    """One installed subject (the conformant fixture) + one uninstalled subject."""
    return install_registry(
        [
            entry("fourthlang", conformant_prefix),
            entry("french", ["definitely-not-installed-xyz"]),
        ]
    )


def test_meta_json_shape_and_order(tmp_path, mixed_registry) -> None:
    export_site(tmp_path)
    meta = _load(tmp_path / "meta.json")
    assert meta == {
        "contract_version": "1.0",
        "schema_version": "1.0",
        "subjects": ["fourthlang", "french"],  # registry order, both listed
    }


def test_subjects_json_shape(tmp_path, mixed_registry) -> None:
    export_site(tmp_path)
    subjects = _load(tmp_path / "subjects.json")
    assert [s["name"] for s in subjects] == ["fourthlang", "french"]

    installed = subjects[0]
    assert installed["available"] is True
    # display_name comes from the REGISTRY entry (metadata), not the subject overview.
    assert installed["display_name"] == "Fourthlang"
    assert installed["repo"]
    assert installed["description"]
    # Modules best-effort from the subject's overview payload.
    assert installed["modules"] == [
        {
            "id": "m1",
            "title": "First Module",
            "summary": "The survival core of the fourth language.",
            "lessons": 0,
        }
    ]

    uninstalled = subjects[1]
    assert uninstalled["available"] is False
    assert uninstalled["modules"] == []  # [] when unavailable


def test_every_subject_record_has_the_pinned_keys(tmp_path, mixed_registry) -> None:
    export_site(tmp_path)
    for row in _load(tmp_path / "subjects.json"):
        assert set(row) == {
            "name",
            "display_name",
            "description",
            "repo",
            "available",
            "modules",
        }
        for module in row["modules"]:
            assert set(module) == {"id", "title", "summary", "lessons"}
            assert isinstance(module["lessons"], int)


def test_stories_file_only_for_available_subjects(tmp_path, mixed_registry) -> None:
    export_site(tmp_path)
    # Available subject → stories file present.
    assert (tmp_path / "stories-fourthlang.json").exists()
    # Unavailable subject → skipped.
    assert not (tmp_path / "stories-french.json").exists()

    stories = _load(tmp_path / "stories-fourthlang.json")
    assert stories["subject"] == "fourthlang"
    # The fixture lists two stories, but `dev-` prefixed ids are in-repo test
    # fixtures, not learner content — the public export excludes them.
    assert len(stories["stories"]) == 1
    assert all(not s["id"].startswith("dev-") for s in stories["stories"])
    story = stories["stories"][0]
    # Full story object from `story read` (not just the list summary): has a body.
    assert story["id"] == "s1"
    assert story["kind"] == "story"
    assert story["body"]
    assert story["exercises"]


# --- t3 acceptance criterion 5: no cloze items -> export is untouched ------


def test_export_unchanged_for_a_subject_declaring_no_cloze_items(tmp_path, mixed_registry) -> None:
    """The t3 cloze contract change (learn/contract/schemas/*.json's optional
    `text`/`blanks` fields, learn/subjects/conformance.py's `cloze-items`
    check) touches NEITHER `export_site` nor the exported bytes for a subject
    that declares no cloze items — the fixture subject predates t3 and ships
    none. This locks the export's exercise object to its EXACT pre-t3 shape:
    no `text`/`blanks` keys anywhere, proving the item_id join-key rules and
    every other exercise field are untouched.
    """
    export_site(tmp_path)
    story = _load(tmp_path / "stories-fourthlang.json")["stories"][0]
    exercise = story["exercises"][0]
    # Semantically identical to the exact pre-t3 payload the conformant
    # fixture has always emitted (tests/fixtures/subjects/conformant_subject.py).
    assert exercise == {
        "id": "s1-q1",
        "type": "multiple_choice",
        "item_id": "greetings",
        "prompt": "What does the character say first?",
        "choices": ["Hello", "Goodbye"],
        "answer": "Hello",
    }
    assert "text" not in exercise
    assert "blanks" not in exercise


def test_export_is_byte_stable_across_repeated_runs_with_no_cloze_content(
    tmp_path, mixed_registry
) -> None:
    # Re-run export_site twice more; the stories file must be byte-identical
    # every time — the cloze contract addition changed nothing here.
    export_site(tmp_path / "run1")
    export_site(tmp_path / "run2")
    a = (tmp_path / "run1" / "stories-fourthlang.json").read_bytes()
    b = (tmp_path / "run2" / "stories-fourthlang.json").read_bytes()
    assert a == b


def test_docs_exported(tmp_path, mixed_registry) -> None:
    export_site(tmp_path)
    docs_dir = tmp_path / "docs"
    assert (docs_dir / "portal.md").exists()
    assert (docs_dir / "subject-plugin-contract.md").exists()
    assert (docs_dir / "subjects.md").exists()
    # The subjects catalog doc is generated from the (overridden) registry.
    assert "fourthlang" in (docs_dir / "subjects.md").read_text(encoding="utf-8")


def test_export_is_deterministic(tmp_path, mixed_registry) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    export_site(a)
    export_site(b)
    files = sorted(p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file())
    assert files  # sanity
    for rel in files:
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), f"non-deterministic: {rel}"


def test_export_never_fails_on_missing_subject(tmp_path, install_registry) -> None:
    # Registry of only-uninstalled subjects: export must still succeed.
    install_registry(
        [
            entry("french", ["definitely-not-installed-xyz"]),
            entry("spanish", ["also-not-installed-xyz"]),
        ]
    )
    summary = export_site(tmp_path)
    assert summary["subjects"] == ["french", "spanish"]
    subjects = _load(tmp_path / "subjects.json")
    assert all(s["available"] is False for s in subjects)
    # No stories files for any subject.
    assert not list(tmp_path.glob("stories-*.json"))


def test_summary_lists_written_files(tmp_path, mixed_registry) -> None:
    summary = export_site(tmp_path)
    assert "meta.json" in summary["files"]
    assert "subjects.json" in summary["files"]
    assert "stories-fourthlang.json" in summary["files"]
    assert "docs/portal.md" in summary["files"]


def test_export_is_robust_to_broken_but_installed_subjects(tmp_path, install_registry) -> None:
    reg_dir = tmp_path / "stubs"
    reg_dir.mkdir()

    # overview ok (non-int lessons), story list has a junk entry + one real story
    # whose `story read` fails → the summary is used as the fallback story object.
    flaky = _stub(
        reg_dir,
        "flaky",
        "toks = [t for t in sys.argv[1:] if t != '--json']\n"
        "if toks[:1] == ['overview']:\n"
        "    print(json.dumps({'modules': [{'id': 'm1', 'title': 'M', "
        "'summary': 's', 'lessons': 'lots'}]})); sys.exit(0)\n"
        "if toks[:2] == ['story', 'list']:\n"
        "    print(json.dumps({'stories': ['junk', {'id': 's1', 'title': 'S', "
        "'level': 'beginner', 'summary': 'x', 'exercises': 1}]})); sys.exit(0)\n"
        "sys.stderr.write(json.dumps({'code': 1, 'message': 'no', 'remediation': 'x'}))\n"
        "sys.exit(1)\n",
    )
    # overview AND story list both fail → modules [] and stories [].
    dark = _stub(
        reg_dir,
        "dark",
        "sys.stderr.write(json.dumps({'code': 2, 'message': 'dark', 'remediation': 'x'}))\n"
        "sys.exit(2)\n",
    )
    # overview returns a non-list `modules` → modules [].
    weird = _stub(
        reg_dir,
        "weird",
        "toks = [t for t in sys.argv[1:] if t != '--json']\n"
        "if toks[:1] == ['overview']:\n"
        "    print(json.dumps({'modules': 'not-a-list'})); sys.exit(0)\n"
        "if toks[:2] == ['story', 'list']:\n"
        "    print(json.dumps({'stories': []})); sys.exit(0)\n"
        "sys.exit(1)\n",
    )
    install_registry([flaky, dark, weird])

    summary = export_site(tmp_path / "out")
    subjects = {s["name"]: s for s in _load(tmp_path / "out" / "subjects.json")}

    # flaky: overview parsed; non-int lessons coerced to 0.
    assert subjects["flaky"]["modules"] == [
        {"id": "m1", "title": "M", "summary": "s", "lessons": 0}
    ]
    # dark + weird: no usable modules.
    assert subjects["dark"]["modules"] == []
    assert subjects["weird"]["modules"] == []

    # flaky stories: junk skipped, real story falls back to its list summary.
    flaky_stories = _load(tmp_path / "out" / "stories-flaky.json")["stories"]
    assert [s["id"] for s in flaky_stories] == ["s1"]
    # dark's story list failed → empty; weird's story list is empty.
    assert _load(tmp_path / "out" / "stories-dark.json")["stories"] == []
    assert _load(tmp_path / "out" / "stories-weird.json")["stories"] == []
    assert summary["subjects"] == ["flaky", "dark", "weird"]


def test_subjects_doc_empty_when_no_subjects(tmp_path, install_registry) -> None:
    from learn.front import build_app

    install_registry([])
    doc = build_app().get_doc("subjects")
    assert doc is not None
    assert "No subjects registered" in doc.text
    # And the export still succeeds with an empty subject set.
    summary = export_site(tmp_path)
    assert summary["subjects"] == []
    assert _load(tmp_path / "meta.json")["subjects"] == []
