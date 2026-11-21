"""Generate and score reference answers through the API or the Claude Code subscription.

    uv run python -m evals.run           # every reference project
    uv run python -m evals.run shop      # only the named ones

Each generation consumes API credits or subscription quota; pytest and CI use fake agents.
Answers, records and scores are checkpointed in `<CODEARCHEO_CACHE_DIR>/evals/`.
Use `python -m evals.rescore REPORT.json` to regrade saved answers without generation.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
import tomllib
import uuid
from contextlib import nullcontext
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codearcheo import evidence, features, git
from codearcheo.agent.limits import SessionLimits
from codearcheo.agent.runner import AgentError
from codearcheo.agent.usage import UsageSummary
from codearcheo.analyzers import scan
from codearcheo.config import Settings
from codearcheo.features import Session
from codearcheo.sources import Project, parse_github
from codearcheo.store import Store
from evals.artifacts import fingerprint, save_report
from evals.fixtures import build_fixture
from evals.scoring import Check, score_answer, score_decisions

CASES = Path(__file__).with_name("cases.toml")
_SHA = re.compile(r"^[0-9a-f]{40}$")
# Claude Code's usage-limit messages ("You've hit your session limit", "…your 5-hour limit",
# "out of usage credits"): every later case would fail the same way.
QUOTA_ERROR = re.compile(r"hit your [\w -]*limit|out of usage credits|usage limit", re.IGNORECASE)
REPAIR_COMMANDS = {"ask", "why"}


def load_cases() -> list[dict[str, Any]]:
    specs = tomllib.loads(CASES.read_text(encoding="utf-8"))["projects"]
    validate_cases(specs)
    return specs


def validate_cases(specs: list[dict[str, Any]]) -> None:
    """Validate every reference offline; real repository checks happen after checkout."""
    projects, cases = set(), set()
    for spec in specs:
        name = spec["name"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name) or name in projects:
            raise ValueError(f"Invalid or duplicate project name: {name}")
        projects.add(name)
        if not spec.get("language"):
            raise ValueError(f"{name}: language is required")
        if spec["source"] not in {"synthetic", "synthetic-github"}:
            if not parse_github(spec["source"]) or not _SHA.fullmatch(spec.get("ref", "")):
                raise ValueError(f"{name}: a GitHub source requires an immutable full SHA")
        elif spec.get("fixture", "shop") not in {"shop", "shop-injection", "github-rationale"}:
            raise ValueError(f"{name}: unknown fixture")
        for case in spec["cases"]:
            case_id, command = case["id"], case["command"]
            if case_id in cases or command not in {"ask", "decisions", "why", "review"}:
                raise ValueError(f"Invalid or duplicate case: {case_id}")
            cases.add(case_id)
            if command == "ask" and not case.get("question"):
                raise ValueError(f"{case_id}: ask requires a question")
            if command == "why" and not case.get("target"):
                raise ValueError(f"{case_id}: why requires a target")
            files = list(case.get("cite_any_file", []))
            for group in case.get("cite_file_groups", {}).values():
                if not group:
                    raise ValueError(f"{case_id}: citation groups must contain at least one file")
                files.extend(group)
            for path in files:
                if Path(path).is_absolute() or ".." in Path(path).parts:
                    raise ValueError(f"{case_id}: evidence must stay inside the reference project")


def prepare(spec: dict[str, Any], workdir: Path) -> Project:
    """The reference project on disk: rebuilt when synthetic, else cloned at its pinned commit."""
    root = workdir / spec["name"]
    if spec["source"] == "synthetic-github":
        from evals.github_project import build_github_project

        shutil.rmtree(root, ignore_errors=True)
        return Project(root=build_github_project(root), name=spec["name"])
    if spec["source"] == "synthetic":
        shutil.rmtree(root, ignore_errors=True)
        fixture = spec.get("fixture", "shop")
        return Project(root=build_fixture(root, fixture), name=spec["name"])

    if not parse_github(spec["source"]) or not _SHA.match(spec["ref"]):
        raise ValueError(f"{spec['name']} : source GitHub ou ref (sha complet) invalide")
    if not (root / ".git").exists():
        workdir.mkdir(parents=True, exist_ok=True)
        git.run(workdir, "clone", "--quiet", spec["source"], spec["name"])
    try:
        git.run(root, "checkout", "--quiet", "--detach", spec["ref"])
    except git.GitError:  # pinned after the clone was made
        git.run(root, "fetch", "--quiet", "origin")
        git.run(root, "checkout", "--quiet", "--detach", spec["ref"])
    return Project(root=root, name=spec["name"], origin=spec["source"])


def run_case(
    session: Session, case: dict[str, Any], canary: str | None,
    *, capture: dict[str, Any] | None = None,
) -> list[Check]:
    """Score a generation and optionally retain its exact output for offline regrading."""
    capture = capture if capture is not None else {}
    root = session.project.root
    try:
        if case["command"] == "decisions":
            answer = features.decisions(session)
            records = session.store.load_decisions()
            capture.update(answer=answer, decisions=[record.model_dump() for record in records])
            return score_decisions(records, case, root, canary, answer=answer)
        elif case["command"] == "ask":
            answer = features.ask(session, case["question"])
        elif case["command"] == "why":
            answer = features.why(session, case["target"])
        elif case["command"] == "review":
            answer = features.review(session, path=case.get("path"))
            capture["recommendations"] = [
                record.model_dump() for record in session.store.load_recommendations()
            ]
        else:
            raise ValueError(f"Unknown evaluation command: {case['command']}")
        capture["answer"] = answer
        return score_answer(answer, case, root, canary)
    except AgentError as exc:
        capture["error"] = str(exc)
        return [Check("réponse obtenue", False, str(exc))]


def select_cases(
    specs: list[dict[str, Any]], names: list[str], case_ids: list[str],
) -> list[dict[str, Any]]:
    """Resolve selectors before preparing a checkout or spending tokens."""
    unknown_names = set(names) - {spec["name"] for spec in specs}
    unknown_cases = set(case_ids) - {case["id"] for spec in specs for case in spec["cases"]}
    if unknown_names or unknown_cases:
        unknown = ", ".join(sorted(unknown_names | unknown_cases))
        raise ValueError("Projets ou cas inconnus : " + unknown)
    selected = []
    for spec in specs:
        if names and spec["name"] not in names:
            continue
        cases = [case for case in spec["cases"] if not case_ids or case["id"] in case_ids]
        if cases:
            selected.append({**spec, "cases": cases})
    if not selected:
        raise ValueError("Aucun cas ne correspond à la sélection de projets et de cas.")
    return selected


def compare_citation_repair(
    metadata: dict[str, Any], case: dict[str, Any], root: Path, canary: str | None
) -> dict[str, Any] | None:
    """Grade the same initial answer and its selected repair, without a second task run."""
    original, final = metadata.get("original_answer"), metadata.get("final_answer")
    if not isinstance(original, str) or not isinstance(final, str):
        return None
    baseline = score_answer(original, case, root, canary)
    selected = score_answer(final, case, root, canary)
    before, after = evidence.verify(original, root), evidence.verify(final, root)
    return {
        "attempted": bool(metadata.get("attempted")),
        "accepted": bool(metadata.get("accepted")),
        "reason": metadata.get("reason"),
        "original_answer": original,
        "final_answer": final,
        "before": {
            "passed": all(check.ok for check in baseline),
            "citations": len(before.citations), "invalid": len(before.problems),
            "checks": [asdict(check) for check in baseline],
        },
        "after": {
            "passed": all(check.ok for check in selected),
            "citations": len(after.citations), "invalid": len(after.problems),
            "checks": [asdict(check) for check in selected],
        },
    }


def citation_repair_available() -> bool:
    """Refuse a requested mode before API calls if its Session integration is unavailable."""
    return (
        "repair_citations" in getattr(Session, "__dataclass_fields__", {})
        and hasattr(Session, "last_repair")
    )


def select_repair_cases(
    specs: list[dict[str, Any]], *, explicit_cases: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Only measure commands whose text repair is integrated; reject unsupported case IDs."""
    skipped = [
        case["id"] for spec in specs for case in spec["cases"]
        if case["command"] not in REPAIR_COMMANDS
    ]
    if skipped and explicit_cases:
        raise ValueError(
            "Correction/comparaison indisponible pour : " + ", ".join(skipped)
            + ". Utiliser --case avec des cas ask/why, ou retirer les options de correction."
        )
    selected = []
    for spec in specs:
        cases = [case for case in spec["cases"] if case["command"] in REPAIR_COMMANDS]
        if cases:
            selected.append({**spec, "cases": cases})
    if not selected:
        raise ValueError("Aucun cas ask/why disponible pour mesurer la correction des citations.")
    return selected, skipped


def main(
    names: list[str], *, repair_citations: bool = False, compare_citations: bool = False,
    max_requests: int | None = None, max_output_tokens: int | None = None,
    backend: str | None = None, case_ids: list[str] | None = None,
) -> int:
    if (repair_citations or compare_citations) and not citation_repair_available():
        print(
            "Citation repair is not implemented; evaluation cancelled before any API call. "
            "Run without --repair-citations/--compare-citations for the baseline (issue #11).",
            file=sys.stderr,
        )
        return 2
    try:
        settings = Settings.from_env(
            max_requests=max_requests, max_output_tokens=max_output_tokens, backend=backend
        )
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    skipped = []
    try:
        specs = select_cases(load_cases(), names, case_ids or [])
        if repair_citations or compare_citations:
            specs, skipped = select_repair_cases(specs, explicit_cases=bool(case_ids))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if skipped:
        print(
            "– Cas ignorés, correction non implémentée (decisions/review) : " + ", ".join(skipped),
            file=sys.stderr,
        )
    limits = (
        SessionLimits.from_settings(settings)
        if settings.max_requests is not None or settings.max_output_tokens != 16_000 else None
    )
    workdir = settings.cache_dir / "evals"
    results = []
    quota_hit = False
    quota_skipped: list[str] = []
    measurements = []
    workdir.mkdir(parents=True, exist_ok=True)
    output = workdir / f"results-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.json"
    code_root = Path(__file__).resolve().parents[1]
    code_revision = git.head(code_root)
    report = {
        "schema_version": 2, "created_at": datetime.now(UTC).isoformat(), "complete": False,
        "code_revision": code_revision,
        "code_dirty": bool(git.run(code_root, "status", "--porcelain")) if code_revision else None,
        "settings": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in asdict(settings).items()
        },
        "model": settings.model, "effort": settings.effort, "backend": settings.backend,
        "repair_citations": repair_citations or compare_citations,
        "compare_citations": compare_citations,
        "selected_cases": [case["id"] for spec in specs for case in spec["cases"]],
        "projects": measurements, "results": results, "skipped": skipped,
    }
    save_report(output, report)
    print(f"Résultats : {output}", flush=True)
    for spec in specs:
        if settings.backend == "claude-code" and spec["source"] == "synthetic-github":
            # The GitHub replay patches this process; Claude Code's tools run in `codearcheo serve`.
            skipped += [case["id"] for case in spec["cases"]]
            print(f"– {spec['name']} ignoré : son rejeu GitHub ne passe pas par Claude Code",
                  file=sys.stderr)
            save_report(output, report)
            continue
        if quota_hit:
            quota_skipped.extend(case["id"] for case in spec["cases"])
            continue
        started = time.perf_counter()
        project = prepare(spec, workdir)
        prepared = time.perf_counter()
        profile = scan(project)
        scanned = time.perf_counter()
        minimum = spec.get("minimum_commits", 0)
        if profile.commits < minimum:
            raise ValueError(f"{spec['name']}: expected at least {minimum} commits, "
                             f"got {profile.commits} (full history is required)")
        measurements.append({
            "project": spec["name"], "sha": profile.head, "commits": profile.commits,
            "worktree_fingerprint": fingerprint(project.root),
            "files": profile.files, "preparation_seconds": prepared - started,
            "scan_seconds": scanned - prepared,
        })
        save_report(output, report)
        session = Session(project, profile, Store(project.root), settings, limits=limits)
        session.repair_citations = repair_citations or compare_citations
        for case in spec["cases"]:
            if quota_hit:
                quota_skipped.append(case["id"])
                continue
            usage = []

            def record_usage(summary: UsageSummary, *, sink: list[dict] = usage) -> None:
                sink.append(asdict(summary))
                print(summary.format(), file=sys.stderr)

            session.on_usage = record_usage
            started = time.perf_counter()
            context = nullcontext()
            if spec["source"] == "synthetic-github":
                from evals.github_project import replay_github

                context = replay_github()
            with context:
                captured: dict[str, Any] = {}
                checks = run_case(session, case, spec.get("canary"), capture=captured)
            comparison = None
            if ("error" not in captured and session.repair_citations
                    and case["command"] in REPAIR_COMMANDS):
                metadata = getattr(session, "last_repair", None)
                if compare_citations and metadata:
                    comparison = compare_citation_repair(
                        metadata, case, project.root, spec.get("canary")
                    )
                captured["citation_repair_verified"] = bool(metadata) and (
                    not compare_citations or comparison is not None
                )
                if not captured["citation_repair_verified"]:
                    checks.append(Check(
                        "correction/comparaison disponible", False,
                        "Métadonnées de correction absentes ; le mode demandé n'a pas été vérifié.",
                    ))
            passed = all(check.ok for check in checks)
            status = "error" if "error" in captured else ("passed" if passed else "failed")
            if status == "error" and QUOTA_ERROR.search(captured["error"]):
                status, quota_hit = "quota", True
            results.append(
                {"case": case["id"], "project": spec["name"], "passed": passed,
                 "status": status,
                 "case_definition": case, "canary": spec.get("canary"), **captured,
                 "elapsed_seconds": time.perf_counter() - started,
                 "usage": usage,
                 **({"citation_repair": comparison} if compare_citations else {}),
                 "estimated_cost_usd": (
                     sum(item["estimated_cost_usd"] for item in usage)
                     if usage and all(item["estimated_cost_usd"] is not None for item in usage)
                     else None
                 ),
                 "checks": [asdict(c) for c in checks]}
            )
            save_report(output, report)
            print(f"{'✓' if passed else '✗'} {case['id']}")
            for check in checks:
                if not check.ok:
                    print(f"    ✗ {check.name}" + (f" : {check.detail}" if check.detail else ""))

    passed = sum(result["passed"] for result in results)
    print(f"\n{passed}/{len(results)} cas réussis · {settings.model}, effort {settings.effort}, "
          f"moteur {settings.backend}")
    errors = sum(result["status"] in ("error", "quota") for result in results)
    if errors:
        print(f"Qualité : {passed}/{len(results) - errors} réponses évaluables ; "
              f"{errors} réponse(s) indisponible(s).")
    if quota_hit:
        resume = [results[-1]["case"], *quota_skipped]
        report["quota_skipped"] = quota_skipped
        print("Quota Claude atteint : évaluation arrêtée. Reprendre après la réinitialisation avec "
              + " ".join(f"--case {case}" for case in resume), file=sys.stderr)
        save_report(output, report)
        return 3
    report["complete"] = True
    save_report(output, report)
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="Reference project names; empty selects all.")
    parser.add_argument("--case", dest="case_ids", action="append", default=[],
                        help="Run only this case ID; repeat the option to select several.")
    parser.add_argument("--repair-citations", action="store_true",
                        help="Correct ask/why citations; skip structured cases unless explicitly "
                             "selected with --case (then reject them before generation).")
    parser.add_argument(
        "--compare-citations", action="store_true",
        help="Compare original/repaired ask/why answers from the same task; other commands "
             "follow --repair-citations selection rules (consumes API/subscription quota).",
    )
    parser.add_argument("--max-requests", type=int,
                        help="Generation HTTP attempt cap shared across the entire evaluation.")
    parser.add_argument(
        "--backend", choices=["api", "claude-code"],
        help="claude-code runs on the Claude subscription through `claude -p` (no API key).",
    )
    parser.add_argument("--max-output-tokens", type=int,
                        help="Maximum generated output tokens in each request.")
    options = parser.parse_args()
    sys.exit(main(options.names, repair_citations=options.repair_citations,
                  compare_citations=options.compare_citations,
                  max_requests=options.max_requests, max_output_tokens=options.max_output_tokens,
                  backend=options.backend, case_ids=options.case_ids))
