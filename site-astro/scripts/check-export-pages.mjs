#!/usr/bin/env node
// Consistency gate between src/content-export/ (the pinned export format —
// see src/lib/content.ts for the fixture-vs-real-exporter note) and the
// built dist/ output. Fails nonzero when:
//   - a subject in the export has no dist/<subject>/index.html page,
//   - a subject's module doesn't show up anywhere in that subject's page,
//   - a story in the export has no dist/<subject>/stories/<id>/index.html
//     reader page,
//   - OR the reverse: dist/ has a subject/story directory with no matching
//     export entry (an orphan page nothing in the export backs).
//
// Run after `npm run build` (CI: .github/workflows/deploy-site.yml; local:
// `npm run check`, which does not build for you — build first).

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const siteRoot = path.resolve(scriptDir, "..");
const distDir = path.join(siteRoot, "dist");
const exportDir = path.join(siteRoot, "src/content-export");

function readJson(relPath) {
  const full = path.join(exportDir, relPath);
  return JSON.parse(readFileSync(full, "utf8"));
}

function fail(problems) {
  console.error(`check-export-pages: ${problems.length} problem(s) found\n`);
  for (const p of problems) {
    console.error(`  - ${p}`);
  }
  console.error(
    "\nEvery subject/module/story in src/content-export/ must have a built " +
      "page, and every subject/story directory under dist/ must be backed " +
      "by the export. Fix the export or the page templates in src/pages/."
  );
  process.exit(1);
}

if (!existsSync(distDir)) {
  console.error(
    `check-export-pages: ${path.relative(siteRoot, distDir)} does not exist.\n` +
      "Run `npm run build` first, then `npm run check`."
  );
  process.exit(1);
}

const meta = readJson("meta.json");
const subjects = readJson("subjects.json");

const problems = [];

// Landing page.
const landingHtml = path.join(distDir, "index.html");
if (!existsSync(landingHtml)) {
  problems.push("landing page missing: dist/index.html");
}

// meta.json's subject list must match subjects.json's entries 1:1.
const metaSubjectNames = new Set(meta.subjects ?? []);
const subjectNames = new Set(subjects.map((s) => s.name));
for (const name of metaSubjectNames) {
  if (!subjectNames.has(name)) {
    problems.push(`meta.json lists subject "${name}" with no entry in subjects.json`);
  }
}
for (const name of subjectNames) {
  if (!metaSubjectNames.has(name)) {
    problems.push(`subjects.json has subject "${name}" not listed in meta.json`);
  }
}

const storiesBySubject = new Map();
for (const subject of subjects) {
  const storiesPath = path.join(exportDir, `stories-${subject.name}.json`);
  if (!existsSync(storiesPath)) {
    problems.push(`missing content-export/stories-${subject.name}.json for subject "${subject.name}"`);
    storiesBySubject.set(subject.name, []);
    continue;
  }
  const storiesFile = JSON.parse(readFileSync(storiesPath, "utf8"));
  storiesBySubject.set(subject.name, storiesFile.stories ?? []);
}

// --- export -> page (every subject/module/story must have rendered output) ---
for (const subject of subjects) {
  const subjectHtmlPath = path.join(distDir, subject.name, "index.html");
  if (!existsSync(subjectHtmlPath)) {
    problems.push(`subject "${subject.name}" has no page: dist/${subject.name}/index.html`);
    continue;
  }
  const subjectHtml = readFileSync(subjectHtmlPath, "utf8");
  for (const mod of subject.modules ?? []) {
    if (!subjectHtml.includes(mod.title) && !subjectHtml.includes(mod.id)) {
      problems.push(
        `module "${mod.id}" (subject "${subject.name}") does not appear on its subject page`
      );
    }
  }

  const stories = storiesBySubject.get(subject.name) ?? [];
  for (const story of stories) {
    const storyHtmlPath = path.join(distDir, subject.name, "stories", story.id, "index.html");
    if (!existsSync(storyHtmlPath)) {
      problems.push(
        `story "${story.id}" (subject "${subject.name}") has no reader page: ` +
          `dist/${subject.name}/stories/${story.id}/index.html`
      );
    }
  }
}

// --- page -> export (no orphan directories dist/ builds that nothing backs) ---
function listDirs(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name);
}

// "terms"/"privacy" are t1's versioned policy pages (src/pages/terms/,
// src/pages/privacy/) — real top-level routes with no backing entry in the
// content-export, since they aren't subject content. "consent" is t10's
// pending-consent notice (src/pages/consent/) — same reasoning: a real
// top-level route, not subject content.
const KNOWN_NON_SUBJECT_DIRS = new Set(["_astro", "terms", "privacy", "consent"]);
for (const dirName of listDirs(distDir)) {
  if (KNOWN_NON_SUBJECT_DIRS.has(dirName)) continue;
  if (!subjectNames.has(dirName)) {
    problems.push(`orphan top-level page dist/${dirName}/ has no matching subject in the export`);
  }
}

for (const subject of subjects) {
  const storiesDir = path.join(distDir, subject.name, "stories");
  if (!existsSync(storiesDir)) continue;
  const exportedIds = new Set((storiesBySubject.get(subject.name) ?? []).map((s) => s.id));
  for (const idDir of listDirs(storiesDir)) {
    if (!exportedIds.has(idDir)) {
      problems.push(
        `orphan story page dist/${subject.name}/stories/${idDir}/ has no matching story in ` +
          `stories-${subject.name}.json`
      );
    }
  }
}

if (problems.length > 0) {
  fail(problems);
}

const totalModules = subjects.reduce((sum, s) => sum + (s.modules?.length ?? 0), 0);
const totalStories = [...storiesBySubject.values()].reduce((sum, arr) => sum + arr.length, 0);
console.log(
  `check-export-pages: OK — ${subjects.length} subject page(s), ${totalModules} module(s) ` +
    `accounted for, ${totalStories} story page(s), all backed by the export.`
);
