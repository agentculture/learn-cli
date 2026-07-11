"""``learn site export`` — the static content bundle the Astro site consumes.

Emits the **pinned** export format (coordinated with the `org`/Astro site build):

* ``meta.json`` — ``{contract_version, schema_version, subjects:[names]}``
  (subjects in registry order).
* ``subjects.json`` — one record per registered subject: ``{name, display_name,
  description, repo, available, modules}``; ``modules`` is best-effort from the
  subject's ``overview`` payload (``[]`` if the subject is unavailable or has no
  modules).
* ``stories-<subject>.json`` — ``{subject, stories:[…]}`` for each **available**
  subject; each story is the full object from ``story read`` (falling back to the
  ``story list`` summary if a read fails). Unavailable subjects are skipped.
* ``docs/<slug>.md`` — every doc page registered in the App.

The export is **deterministic** — JSON is written with sorted keys, lists follow
registry / story-list order, and nothing reads the wall clock — so re-running it
over unchanged inputs yields byte-identical files. It **never fails because a
subject is missing**: an uninstalled subject is listed with ``available: false``
and skipped for stories.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentfront.app import App

from learn.cli._errors import CliError
from learn.contract import CONTRACT_VERSION
from learn.front import build_app
from learn.front._driver import drive
from learn.subjects import SubjectEntry, is_available, load_registry


def _write_json(path: Path, obj: Any) -> None:
    """Write *obj* as deterministic JSON (sorted keys, trailing newline)."""
    text = json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def _module_record(module: dict[str, Any]) -> dict[str, Any]:
    """Best-effort ``{id, title, summary, lessons}`` from an overview module."""
    lessons = module.get("lessons", 0)
    try:
        lessons_int = int(lessons)
    except (TypeError, ValueError):
        lessons_int = 0
    return {
        "id": str(module.get("id", "")),
        "title": str(module.get("title", "")),
        "summary": str(module.get("summary", "")),
        "lessons": lessons_int,
    }


def _subject_modules(entry: SubjectEntry, source: str | None) -> list[dict[str, Any]]:
    """Modules from the subject's ``overview`` payload, or ``[]`` if unavailable."""
    if not is_available(entry):
        return []
    try:
        overview = drive(entry, ("overview",), registry_source=source)
    except CliError:
        return []
    modules = overview.get("modules", [])
    if not isinstance(modules, list):
        return []
    return [_module_record(m) for m in modules if isinstance(m, dict)]


def _subject_record(entry: SubjectEntry, source: str | None) -> dict[str, Any]:
    return {
        "name": entry.name,
        "display_name": entry.display_name,
        "description": entry.description,
        "repo": entry.repo,
        "available": is_available(entry),
        "modules": _subject_modules(entry, source),
    }


def _subject_stories(entry: SubjectEntry, source: str | None) -> list[dict[str, Any]]:
    """Full story objects from ``story list`` + ``story read`` (list-order)."""
    try:
        listing = drive(entry, ("story", "list"), registry_source=source)
    except CliError:
        return []
    stories: list[dict[str, Any]] = []
    for summary in listing.get("stories", []):
        if not isinstance(summary, dict):
            continue
        story_id = summary.get("id")
        # Subject repos ship `dev-` prefixed stories as in-repo test fixtures;
        # they are not learner content, so the public export excludes them.
        if isinstance(story_id, str) and story_id.startswith("dev-"):
            continue
        full: dict[str, Any] | None = None
        if isinstance(story_id, str) and story_id:
            try:
                read = drive(entry, ("story", "read"), extra=(story_id,), registry_source=source)
            except CliError:
                read = {}
            candidate = read.get("story")
            if isinstance(candidate, dict):
                full = candidate
        stories.append(full if full is not None else summary)
    return stories


def export_site(
    out_dir: str | Path,
    *,
    app: App | None = None,
    registry_source: str | None = None,
) -> dict[str, Any]:
    """Write the pinned content-export bundle into *out_dir*; return a summary.

    ``app`` defaults to :func:`learn.front.build_app` (docs come from it);
    ``registry_source`` overrides the subject registry (mirrors
    ``LEARN_SUBJECTS_REGISTRY``), used by tests to point at a fixture subject.
    """
    app = app or build_app()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    entries = load_registry(registry_source)

    _write_json(
        out / "meta.json",
        {
            "contract_version": CONTRACT_VERSION,
            "schema_version": CONTRACT_VERSION,
            "subjects": [e.name for e in entries],
        },
    )

    _write_json(out / "subjects.json", [_subject_record(e, registry_source) for e in entries])

    story_files: list[str] = []
    for entry in entries:
        if not is_available(entry):
            continue
        stories = _subject_stories(entry, registry_source)
        name = f"stories-{entry.name}.json"
        _write_json(out / name, {"subject": entry.name, "stories": stories})
        story_files.append(name)

    docs_dir = out / "docs"
    docs_dir.mkdir(exist_ok=True)
    doc_files: list[str] = []
    for doc in app.list_docs():
        (docs_dir / f"{doc.slug}.md").write_text(doc.text, encoding="utf-8")
        doc_files.append(f"docs/{doc.slug}.md")

    return {
        "out": str(out),
        "contract_version": CONTRACT_VERSION,
        "schema_version": CONTRACT_VERSION,
        "subjects": [e.name for e in entries],
        "files": ["meta.json", "subjects.json", *sorted(story_files), *sorted(doc_files)],
    }
