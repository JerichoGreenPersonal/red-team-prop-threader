# Daily Review Prep Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an installed Windows app that prep’s the daily ShotGrid `layout_3` review queue (attachments + P4 CLs), then opens eligible DCC files via Cadet on first interactive session, with a dashboard for summary / Prepare / Open Again.

**Architecture:** One Python package shared by a scheduled worker CLI and a PySide6 dashboard. Domain logic (CL parser, route state, staging paths, orchestrator) is pure and unit-tested; adapters wrap ShotGrid, P4, 7-Zip, Credential Manager, Task Scheduler, and Cadet. SQLite is the local manifest. Interactive launches never run inside the non-interactive worker.

**Tech Stack:** Python 3.12+, pytest, PySide6, shotgun-api3, keyring (Windows Credential Manager), sqlite3, subprocess for `p4`/`7z`/Cadet, PyInstaller for packaging.

**Spec:** `docs/superpowers/specs/2026-07-09-daily-review-prep-assistant-design.md`

## Global Constraints

- Windows-only MVP; per-user install preferred; prep runs as the reviewing Windows user (never `SYSTEM`).
- Self-contained installer later — users must not need a separate Python install at runtime.
- ShotGrid auth: shared script key in Windows Credential Manager only (never plain config files).
- Worklist: trust page 12787 `layout_3` query results; no extra Windows-local date gate for selection.
- Archives: `.rar` + `.zip` via 7-Zip; CLs from comments; attachments for archives; both routes allowed on one card.
- P4: everyday client; skip unsafe files only; never force/clobber/revert.
- CL defaults: Source Art / Preflight / Unknown = Sync only; WIP = Sync and open.
- Cadet/`apex_r5dev` for interactive opens; MVP assumes Cadet is running — else log prompt, no auto-start.
- No launch concurrency cap (setting retained); open all recognized DCC files.
- Summary: dashboard auto-open when unacked; closing acknowledges; no toast/email/Slack.
- Schedule default 5:00 AM local + catch-up; staging retention N days (default forever).
- Slack worklist: out of scope.
- TDD: failing test → implement → pass → commit per task.
- ASCII-friendly code/comments unless the repo already uses otherwise.

---

## File Structure (create during Task 1)

```
review_prep/
  pyproject.toml
  README.md
  configs/
    default_shotgrid_query.json      # filled in Task 5 from layout_3
  src/review_prep/
    __init__.py
    models.py                        # enums + dataclasses
    cl_parser.py                     # labeled CL parsing
    paths.py                         # staging path sanitize + layout
    state.py                         # SQLite repository
    settings.py                      # load/save user settings
    credentials.py                   # keyring ShotGrid secret
    shotgun_adapter.py               # worklist, notes, attachments
    archive_extractor.py             # 7-Zip safe extract
    p4_adapter.py                    # preview/sync/safety
    file_classifier.py               # DCC recognition + patterns
    orchestrator.py                  # prep one card / full run
    launch_coordinator.py            # Cadet launch + leases
    scheduler_windows.py             # Task Scheduler registration
    retention.py                     # staging N-day cleanup
    worker_main.py                   # CLI entry for scheduled prep
    app_main.py                      # dashboard entry
    ui/
      __init__.py
      main_window.py
      summary_dialog.py
      settings_wizard.py
  tests/
    test_cl_parser.py
    test_paths.py
    test_state.py
    test_file_classifier.py
    test_archive_extractor.py
    test_p4_adapter.py
    test_orchestrator.py
    test_launch_coordinator.py
    test_retention.py
    test_settings.py
    fakes/
      fake_shotgun.py
      fake_p4.py
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `src/review_prep/__init__.py`
- Create: `src/review_prep/models.py`
- Create: `tests/test_models_smoke.py`

**Interfaces:**
- Produces: package `review_prep` installable editable; `RouteState`, `ClPolicy`, `DeliveryRouteKind` enums in `models.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "review-prep"
version = "0.1.0"
description = "Daily Review Prep Assistant"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
  "PySide6>=6.6",
  "shotgun-api3>=3.3.0",
  "keyring>=25.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-qt>=4.4"]

[project.scripts]
review-prep-worker = "review_prep.worker_main:main"
review-prep = "review_prep.app_main:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Create package + models**

```python
# src/review_prep/__init__.py
__version__ = "0.1.0"
```

```python
# src/review_prep/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RouteState(str, Enum):
    NOT_PREPARED = "not_prepared"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    SYNCING = "syncing"
    READY_TO_LAUNCH = "ready_to_launch"
    SYNCED_ONLY = "synced_only"
    LAUNCHED = "launched"
    SKIPPED = "skipped"
    PARTIAL = "partial"
    FAILED = "failed"


class ClPolicy(str, Enum):
    IGNORE = "ignore"
    SYNC_ONLY = "sync_only"
    SYNC_AND_OPEN = "sync_and_open"


class DeliveryRouteKind(str, Enum):
    ATTACHMENT_ARCHIVE = "attachment_archive"
    ATTACHMENT_LOOSE = "attachment_loose"
    P4_CL = "p4_cl"


DEFAULT_CL_POLICIES: dict[str, ClPolicy] = {
    "Source Art": ClPolicy.SYNC_ONLY,
    "Preflight": ClPolicy.SYNC_ONLY,
    "WIP": ClPolicy.SYNC_AND_OPEN,
}


@dataclass(frozen=True)
class ParsedCl:
    label: str
    number: int
    raw: str

    @property
    def policy_key(self) -> str:
        return self.label if self.label in DEFAULT_CL_POLICIES else "Unknown"
```

- [ ] **Step 3: Write smoke test**

```python
# tests/test_models_smoke.py
from review_prep.models import ClPolicy, DEFAULT_CL_POLICIES, RouteState


def test_wip_default_is_sync_and_open():
    assert DEFAULT_CL_POLICIES["WIP"] == ClPolicy.SYNC_AND_OPEN


def test_route_state_values_are_stable():
    assert RouteState.READY_TO_LAUNCH.value == "ready_to_launch"
```

- [ ] **Step 4: Install and run tests**

Run:
```bash
cd C:/Users/jgreen2/Documents/CURSOR/RED_Team_ReviewPrep
python -m pip install -e ".[dev]"
pytest tests/test_models_smoke.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md src/review_prep/__init__.py src/review_prep/models.py tests/test_models_smoke.py
git commit -m "chore: scaffold review-prep package and domain enums"
```

---

### Task 2: CL comment parser

**Files:**
- Create: `src/review_prep/cl_parser.py`
- Create: `tests/test_cl_parser.py`

**Interfaces:**
- Produces: `parse_cls_from_comment(text: str) -> list[ParsedCl]`; `is_delivery_comment(text: str) -> bool`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cl_parser.py
from review_prep.cl_parser import is_delivery_comment, parse_cls_from_comment


def test_parse_source_art_preflight_and_wip():
    text = (
        "Source Art CL is 11288616\n"
        "Preflight CL is 11288606\n"
        "WIP CL 11290000\n"
    )
    parsed = parse_cls_from_comment(text)
    assert [(p.label, p.number) for p in parsed] == [
        ("Source Art", 11288616),
        ("Preflight", 11288606),
        ("WIP", 11290000),
    ]


def test_unknown_label_still_parses():
    parsed = parse_cls_from_comment("Lighting CL is 555")
    assert len(parsed) == 1
    assert parsed[0].label == "Lighting"
    assert parsed[0].policy_key == "Unknown"


def test_internal_comment_is_not_delivery():
    assert is_delivery_comment("looks good, thanks") is False
    assert is_delivery_comment("Source Art CL is 1") is True
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest tests/test_cl_parser.py -v`  
Expected: FAIL (module not found)

- [ ] **Step 3: Implement parser**

```python
# src/review_prep/cl_parser.py
from __future__ import annotations

import re

from review_prep.models import ParsedCl

# Label + number; accepts "CL is N" or "CL N"
_CL_RE = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z0-9 /_-]*?)\s+CL(?:\s+is)?\s+(?P<number>\d+)",
    re.IGNORECASE,
)


def parse_cls_from_comment(text: str) -> list[ParsedCl]:
    results: list[ParsedCl] = []
    for match in _CL_RE.finditer(text or ""):
        label = " ".join(match.group("label").strip().split())
        # Normalize known casing
        known = {"source art": "Source Art", "preflight": "Preflight", "wip": "WIP"}
        label = known.get(label.lower(), label)
        results.append(
            ParsedCl(label=label, number=int(match.group("number")), raw=match.group(0))
        )
    return results


def is_delivery_comment(text: str) -> bool:
    return bool(parse_cls_from_comment(text))
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/test_cl_parser.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/review_prep/cl_parser.py tests/test_cl_parser.py
git commit -m "feat: parse labeled Perforce CLs from delivery comments"
```

---

### Task 3: Staging paths

**Files:**
- Create: `src/review_prep/paths.py`
- Create: `tests/test_paths.py`

**Interfaces:**
- Produces: `sanitize_asset_name(name: str) -> str`; `asset_staging_dir(root, local_date, asset_name, shotgrid_id) -> Path`; rejects mapped-drive-style roots only via `assert_local_or_unc(path)`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_paths.py
from datetime import date
from pathlib import Path

import pytest

from review_prep.paths import assert_local_or_unc, asset_staging_dir, sanitize_asset_name


def test_sanitize_strips_invalid_windows_chars():
    assert sanitize_asset_name('a<>:"/\\|?*b') == "a_________b"


def test_asset_staging_dir_layout():
    root = Path("D:/ReviewPrep")
    p = asset_staging_dir(root, date(2026, 7, 13), "destruction kit interior", 12345)
    assert p == Path("D:/ReviewPrep/MON_07_13_2026/destruction_kit_interior_12345")


def test_reject_mapped_drive_letter_only_relative_claim():
    # UNC and normal paths OK; empty rejected
    assert_local_or_unc(Path("D:/ReviewPrep"))
    assert_local_or_unc(Path("//server/share/ReviewPrep"))
    with pytest.raises(ValueError):
        assert_local_or_unc(Path(""))
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/test_paths.py -v`

- [ ] **Step 3: Implement**

```python
# src/review_prep/paths.py
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*]')


def sanitize_asset_name(name: str) -> str:
    cleaned = _INVALID.sub("_", name.strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned or "asset"


def asset_staging_dir(
    root: Path, local_date: date, asset_name: str, shotgrid_id: int
) -> Path:
    day = local_date.strftime("%a").upper()[:3]
    folder = f"{day}_{local_date.strftime('%m_%d_%Y')}"
    leaf = f"{sanitize_asset_name(asset_name)}_{shotgrid_id}"
    return Path(root) / folder / leaf


def assert_local_or_unc(path: Path) -> Path:
    p = Path(path)
    if not str(p).strip():
        raise ValueError("staging root must be a local or UNC path")
    return p
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/test_paths.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/review_prep/paths.py tests/test_paths.py
git commit -m "feat: staging path layout and Windows name sanitization"
```

---

### Task 4: SQLite state repository

**Files:**
- Create: `src/review_prep/state.py`
- Create: `tests/test_state.py`

**Interfaces:**
- Produces: `StateRepo(db_path: Path)` with:
  - `ensure_schema()`
  - `start_prep_run(local_date: str, trigger: str) -> int`
  - `upsert_route(...)` / `get_routes_for_card(card_id: int)`
  - `record_launch_lease(file_key: str, local_date: str) -> bool`  # False if already held
  - `ack_summary(prep_run_id: int)` / `latest_unacked_run() -> Optional[int]`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_state.py
from pathlib import Path

from review_prep.models import DeliveryRouteKind, RouteState
from review_prep.state import StateRepo


def test_launch_lease_is_exactly_once(tmp_path: Path):
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    assert repo.record_launch_lease("file-a", "2026-07-23") is True
    assert repo.record_launch_lease("file-a", "2026-07-23") is False
    assert repo.record_launch_lease("file-a", "2026-07-24") is True


def test_summary_ack(tmp_path: Path):
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    run_id = repo.start_prep_run("2026-07-23", "scheduled")
    assert repo.latest_unacked_run() == run_id
    repo.ack_summary(run_id)
    assert repo.latest_unacked_run() is None


def test_route_upsert_roundtrip(tmp_path: Path):
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    run_id = repo.start_prep_run("2026-07-23", "manual")
    repo.upsert_route(
        prep_run_id=run_id,
        card_sg_id=38811,
        route_kind=DeliveryRouteKind.P4_CL.value,
        route_key="WIP:11290000",
        state=RouteState.SYNCED_ONLY.value,
        detail="ok",
    )
    routes = repo.get_routes_for_card(38811)
    assert routes[0]["state"] == RouteState.SYNCED_ONLY.value
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/test_state.py -v`

- [ ] **Step 3: Implement `StateRepo`**

Implement `src/review_prep/state.py` with sqlite3, tables:

- `prep_runs(id, local_date, trigger, created_at, acked_at NULL)`
- `routes(id, prep_run_id, card_sg_id, route_kind, route_key, state, detail, updated_at)` unique on `(card_sg_id, route_kind, route_key)` for latest
- `launch_leases(file_key, local_date, created_at)` PRIMARY KEY `(file_key, local_date)`

`record_launch_lease` inserts; on IntegrityError return False.

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/test_state.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/review_prep/state.py tests/test_state.py
git commit -m "feat: SQLite manifest for routes, leases, and summary ack"
```

---

### Task 5: Settings + credentials + default ShotGrid query stub

**Files:**
- Create: `src/review_prep/settings.py`
- Create: `src/review_prep/credentials.py`
- Create: `configs/default_shotgrid_query.json`
- Create: `tests/test_settings.py`

**Interfaces:**
- Produces: `AppSettings` dataclass; `load_settings(path) / save_settings(path, settings)`; `ShotGridCredentials` via keyring service `review-prep` username `shotgrid-script`

- [ ] **Step 1: Write `configs/default_shotgrid_query.json` stub**

```json
{
  "site_url": "https://respawn.shotgunstudio.com",
  "reference_page": "https://respawn.shotgunstudio.com/page/12787?layout=layout_3",
  "sample_card": "https://respawn.shotgunstudio.com/page/12787#Asset_38811",
  "entity_type": "Asset",
  "filters": [],
  "fields": ["id", "code", "image", "sg_status_list"],
  "order": [{"field_name": "id", "direction": "asc"}],
  "notes": "Replace filters/fields during implementation by inspecting layout_3 while authenticated."
}
```

- [ ] **Step 2: Failing settings tests**

```python
# tests/test_settings.py
from pathlib import Path

from review_prep.models import ClPolicy
from review_prep.settings import AppSettings, load_settings, save_settings


def test_defaults_and_roundtrip(tmp_path: Path):
    path = tmp_path / "settings.json"
    s = AppSettings.defaults()
    assert s.schedule_hour == 5
    assert s.schedule_minute == 0
    assert s.retention_days is None
    assert s.cl_policies["WIP"] == ClPolicy.SYNC_AND_OPEN.value
    save_settings(path, s)
    loaded = load_settings(path)
    assert loaded.staging_root == s.staging_root
    assert loaded.cl_policies["Source Art"] == ClPolicy.SYNC_ONLY.value
```

- [ ] **Step 3: Implement settings + credentials**

`AppSettings` fields: `staging_root`, `retention_days: int | None`, `schedule_hour`, `schedule_minute`, `p4_client`, `p4_exe`, `seven_zip_exe`, `cadet_launch_templates: dict[str, str]`, `cl_policies: dict[str, str]`, `include_patterns`, `exclude_patterns`, `launch_concurrency: int | None` (None = uncapped), `shotgrid_script_name`, `shotgrid_query_path`.

`credentials.py`:

```python
import keyring

SERVICE = "review-prep"
USER = "shotgrid-script"

def set_shotgrid_api_key(api_key: str) -> None:
    keyring.set_password(SERVICE, USER, api_key)

def get_shotgrid_api_key() -> str | None:
    return keyring.get_password(SERVICE, USER)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_settings.py -v`

- [ ] **Step 5: Commit**

```bash
git add configs/default_shotgrid_query.json src/review_prep/settings.py src/review_prep/credentials.py tests/test_settings.py
git commit -m "feat: user settings defaults and Credential Manager helpers"
```

---

### Task 6: File classifier

**Files:**
- Create: `src/review_prep/file_classifier.py`
- Create: `tests/test_file_classifier.py`

**Interfaces:**
- Produces: `is_recognized_dcc(path: Path) -> bool`; `filter_launchable(paths, include_globs, exclude_globs) -> list[Path]`; `archive_kind(path) -> Literal['rar','zip',None]`

- [ ] **Step 1: Failing tests**

```python
from pathlib import Path
from review_prep.file_classifier import archive_kind, filter_launchable, is_recognized_dcc


def test_recognized_extensions():
    assert is_recognized_dcc(Path("a.ma"))
    assert is_recognized_dcc(Path("a.mb"))
    assert is_recognized_dcc(Path("a.ztl"))
    assert is_recognized_dcc(Path("a.spp"))
    assert not is_recognized_dcc(Path("a.png"))


def test_exclude_pattern():
    paths = [Path("hero_review.ma"), Path("hero_wip.ma")]
    out = filter_launchable(paths, include_globs=["*.ma"], exclude_globs=["*_wip.ma"])
    assert out == [Path("hero_review.ma")]


def test_archive_kind():
    assert archive_kind(Path("x.RAR")) == "rar"
    assert archive_kind(Path("x.zip")) == "zip"
    assert archive_kind(Path("x.ma")) is None
```

- [ ] **Step 2–4: Implement + pass + commit**

```bash
git commit -m "feat: DCC and archive file classification"
```

---

### Task 7: Safe 7-Zip archive extractor

**Files:**
- Create: `src/review_prep/archive_extractor.py`
- Create: `tests/test_archive_extractor.py`

**Interfaces:**
- Consumes: path to `7z.exe`
- Produces: `extract_archive(archive: Path, dest: Path, seven_zip: Path, max_files: int, max_bytes: int) -> list[Path]`  
  Raises `UnsafeArchiveError` on `..`, absolute paths, limits, bad exit

- [ ] **Step 1: Failing tests with a tiny zip built in-test**

```python
import zipfile
from pathlib import Path
import pytest
from review_prep.archive_extractor import UnsafeArchiveError, extract_archive, list_archive_entries


def _make_zip(path: Path, names: dict[str, bytes]):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in names.items():
            zf.writestr(name, data)


def test_rejects_traversal(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    _make_zip(archive, {"../../evil.txt": b"x"})
    with pytest.raises(UnsafeArchiveError):
        list_archive_entries(archive)  # pure zipfile path listing for unit test


def test_extract_ok_with_fake_runner(tmp_path: Path, monkeypatch):
    # Unit-test the path validation helper independently of real 7z
    from review_prep import archive_extractor as ae

    ae.validate_member_path(Path("ok/file.ma"), Path(tmp_path / "out"))
    with pytest.raises(UnsafeArchiveError):
        ae.validate_member_path(Path("../x.ma"), Path(tmp_path / "out"))
```

Also add one integration test marked `@pytest.mark.integration` that calls real `7z` if present (skip otherwise).

- [ ] **Step 2–4: Implement validation + `7z x -o... -y` wrapper + commit**

```bash
git commit -m "feat: safe 7-Zip archive extraction with traversal limits"
```

---

### Task 8: P4 adapter (safety-first)

**Files:**
- Create: `src/review_prep/p4_adapter.py`
- Create: `tests/fakes/fake_p4.py`
- Create: `tests/test_p4_adapter.py`

**Interfaces:**
- Produces: `P4Adapter` protocol with `describe_cl(cl: int)`, `preview_sync(cl: int) -> list[P4FilePlan]`, `sync_cl(cl: int) -> list[P4SyncResult]`  
- `P4FilePlan(depot, local, action, safe: bool, skip_reason: str | None)`  
- Unsafe if local is open/writable conflict; those get `safe=False` and are skipped on sync

- [ ] **Step 1: Tests against fake runner**

```python
def test_skips_open_files_and_syncs_siblings():
    fake = FakeP4(
        describe={11290000: ["//depot/a.ma", "//depot/b.ma"]},
        opened={"//depot/a.ma"},
        map={"//depot/a.ma": "D:/ws/a.ma", "//depot/b.ma": "D:/ws/b.ma"},
    )
    adapter = P4Adapter(runner=fake, client="my_client")
    results = adapter.sync_cl(11290000)
    by_depot = {r.depot: r for r in results}
    assert by_depot["//depot/a.ma"].skipped is True
    assert by_depot["//depot/b.ma"].skipped is False
```

Implement by shelling to `p4 -c CLIENT ...` in real adapter; fake injects command results.

- [ ] **Step 2–4: Implement + pass + commit**

```bash
git commit -m "feat: P4 exact-CL sync with unsafe-file skips"
```

---

### Task 9: ShotGrid adapter + fakes

**Files:**
- Create: `src/review_prep/shotgun_adapter.py`
- Create: `tests/fakes/fake_shotgun.py`
- Create: `tests/test_shotgun_adapter.py`
- Modify: `configs/default_shotgrid_query.json` (fill real filters when authenticated)

**Interfaces:**
- Produces: `ShotGridAdapter.find_worklist() -> list[Card]`; `list_attachments(card_id)`; `list_comments(card_id)`; `download_attachment(id, dest)`; `latest_delivery_comment(comments) -> Comment | None` using `is_delivery_comment`

`Card(id, code, thumbnail_url, raw_fields)`

- [ ] **Step 1: Unit tests with FakeShotgun**

```python
def test_latest_delivery_comment_skips_later_internal():
    comments = [
        Comment(id=3, text="thanks", created="2026-07-23T12:00:00"),
        Comment(id=2, text="Source Art CL is 99", created="2026-07-23T11:00:00"),
        Comment(id=1, text="hello", created="2026-07-23T10:00:00"),
    ]
    latest = latest_delivery_comment(comments)
    assert latest is not None
    assert latest.id == 2
```

- [ ] **Step 2: Implement adapter using `shotgun_api3.Shotgun(site, script_name, api_key)`**

- [ ] **Step 3: Manual checkpoint (human):** log into ShotGrid, inspect `layout_3`, replace `filters`/`fields`/`entity_type` in `configs/default_shotgrid_query.json`, add a live smoke script `scripts/smoke_shotgun_worklist.py` that prints card ids.

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: ShotGrid worklist adapter and delivery comment selection"
```

---

### Task 10: Prep orchestrator

**Files:**
- Create: `src/review_prep/orchestrator.py`
- Create: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: settings, StateRepo, ShotGridAdapter, P4Adapter, extract_archive, file_classifier, paths
- Produces: `PrepOrchestrator.run_worklist() -> PrepRunResult`; `prepare_cards(card_ids: list[int]) -> PrepRunResult`

For each card:
1. List attachments → archive routes download + extract into staging dir  
2. Latest delivery comment → parse CLs → apply policy (ignore / sync only / sync and open)  
3. Classify extracted/synced files into launchable list in state  
4. Never stop sibling routes on one failure  

- [ ] **Step 1: Failing test with fakes — one card with zip attachment + WIP CL**

```python
def test_card_runs_attachment_and_cl_routes(tmp_path):
    # Fake SG returns one asset with one zip attachment + WIP comment
    # Fake P4 syncs one .ma
    # Assert two routes recorded; launchable files include extracted + synced where policy says open
    ...
```

- [ ] **Step 2–4: Implement + pass + commit**

```bash
git commit -m "feat: prep orchestrator for attachment and P4 routes"
```

---

### Task 11: Launch coordinator (Cadet + leases)

**Files:**
- Create: `src/review_prep/launch_coordinator.py`
- Create: `tests/test_launch_coordinator.py`

**Interfaces:**
- Produces: `LaunchCoordinator.launch_eligible(local_date) -> LaunchReport`; `open_again(card_ids)`; `cadet_available() -> bool`

MVP Cadet check: process names include `Cadet.SystemTray` or `Cadet.Service`. If missing, append log prompt `"Cadet is not running; enter apex_r5dev then use Open Again"` and do not take successful leases.

Launch command: format settings template, e.g. default placeholder  
`{cadet_cmd} --toolset apex_r5dev --app Maya --file "{file}"`  
(exact template filled in settings during setup; subprocess `Popen` detached).

- [ ] **Step 1: Tests**

```python
def test_lease_prevents_second_launch(tmp_path, monkeypatch):
    ...


def test_cadet_missing_does_not_lease(tmp_path, monkeypatch):
    monkeypatch.setattr(LaunchCoordinator, "cadet_available", lambda self: False)
    report = coordinator.launch_eligible("2026-07-23")
    assert report.blocked_cadet is True
    assert repo.record_launch_lease_was_not_consumed_for_those_files
```

- [ ] **Step 2–4: Implement + pass + commit**

```bash
git commit -m "feat: Cadet launch coordinator with exactly-once leases"
```

---

### Task 12: Retention cleanup

**Files:**
- Create: `src/review_prep/retention.py`
- Create: `tests/test_retention.py`

**Interfaces:**
- Produces: `cleanup_staging(root: Path, today: date, retention_days: int | None) -> list[Path]`  
  If `retention_days is None`, no-op. Never delete today's `DAY_*` folder.

- [ ] **Step 1–4: TDD + commit**

```bash
git commit -m "feat: optional N-day staging retention cleanup"
```

---

### Task 13: Worker CLI + Windows Task Scheduler

**Files:**
- Create: `src/review_prep/worker_main.py`
- Create: `src/review_prep/scheduler_windows.py`
- Create: `tests/test_scheduler_windows.py`

**Interfaces:**
- `worker_main.main()` loads settings, opens DB under `%LOCALAPPDATA%/ReviewPrep/prep.db`, runs orchestrator, optional retention, writes run result  
- `register_daily_task(exe_path, hour=5, minute=0)` via `schtasks`  
- `register_logon_trigger(dashboard_exe)` for summary auto-open helper

- [ ] **Step 1: Worker dry-run test** monkeypatches orchestrator

- [ ] **Step 2: Implement worker**

```python
# worker_main.py outline
def main(argv=None) -> int:
    settings = load_settings(settings_path())
    repo = StateRepo(db_path())
    repo.ensure_schema()
    # wire adapters from settings + credentials
    result = PrepOrchestrator(...).run_worklist()
    cleanup_staging(...)
    return 0 if not result.hard_failure else 1
```

- [ ] **Step 3: `scheduler_windows.register_daily_task` builds:**

```text
schtasks /Create /F /TN "ReviewPrep\DailyPrep" /SC DAILY /ST 05:00 /RL LIMITED /TR "\"C:\\path\\review-prep-worker.exe\""
```

Use `/RU` current user; document catch-up via Task Scheduler default missed-run behavior (`Start when available` set in XML task if needed).

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: scheduled worker entrypoint and Task Scheduler registration"
```

---

### Task 14: Dashboard UI (PySide6)

**Files:**
- Create: `src/review_prep/app_main.py`
- Create: `src/review_prep/ui/main_window.py`
- Create: `src/review_prep/ui/summary_dialog.py`
- Create: `src/review_prep/ui/settings_wizard.py`
- Create: `tests/test_ui_summary_ack.py` (logic-level; full Qt optional)

**Interfaces:**
- On startup: if `latest_unacked_run()`, show `SummaryDialog`; on accept/close → `ack_summary`  
- Main window: list cards from last worklist snapshot / live refresh; multi-select; **Prepare**; **Open Again**; Settings  
- Settings wizard first-run: script key → keyring, staging root, P4 client, Cadet templates, 7z path; run test query

- [ ] **Step 1: Summary ack unit test** (dialog logic without requiring display if possible)

- [ ] **Step 2: Implement minimal PySide windows**

Keep UI plain and functional — table of cards, status column, buttons Prepare / Open Again / Settings. No design-system sprawl.

- [ ] **Step 3: Manual test on Windows**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: dashboard summary, Prepare, Open Again, and setup wizard"
```

---

### Task 15: Packaging (PyInstaller)

**Files:**
- Create: `packaging/review_prep.spec`
- Create: `packaging/build.ps1`
- Modify: `README.md` with build + install notes

**Interfaces:**
- Produce `review-prep-worker.exe` and `review-prep.exe` (console vs windowed)
- Per-user copy under `%LOCALAPPDATA%/ReviewPrep/app/` + Start Menu shortcut script
- Post-install: register scheduled task + logon helper

- [ ] **Step 1: Write `packaging/build.ps1`** that runs PyInstaller for both entrypoints

- [ ] **Step 2: Build on this workstation and smoke-launch `--help` / empty settings wizard**

- [ ] **Step 3: Commit**

```bash
git commit -m "build: PyInstaller packaging scripts for worker and dashboard"
```

---

### Task 16: End-to-end checklist (manual)

**Files:**
- Create: `docs/superpowers/plans/2026-07-23-daily-review-prep-e2e-checklist.md`

- [ ] **Step 1: Write checklist covering**
  - Setup wizard with script key + staging + P4 client + Cadet template + 7z  
  - Test query returns `layout_3` cards  
  - Worker prep: RAR/zip attachment card  
  - Worker prep: CL-only card (Source Art sync-only, WIP sync-and-open)  
  - Unsafe open file skipped  
  - Login summary auto-open + ack  
  - Cadet missing → prompt in log, Open Again works after Cadet up  
  - Manual Prepare + Open Again  
  - Retention N days dry-run  

- [ ] **Step 2: Commit checklist**

```bash
git commit -m "docs: MVP end-to-end verification checklist"
```

---

## Spec coverage (self-review)

| Spec area | Task(s) |
|-----------|---------|
| `layout_3` worklist / SG query | 5, 9 |
| Attachments + CL comments / both routes | 2, 9, 10 |
| Staging paths + retention | 3, 12 |
| 7-Zip rar/zip safety | 7 |
| P4 everyday client, skip unsafe, CL defaults | 1, 8, 10 |
| Cadet launch, leases, no auto-start | 11 |
| Schedule 5am + catch-up worker | 13 |
| Dashboard summary auto-open/ack, Prepare, Open Again | 14 |
| Credential Manager + setup | 5, 14 |
| Packaging self-contained | 15 |
| Slack / toast / Re-run / SG write-back | Explicit non-goals — no tasks |

**Placeholder scan:** Task 9 requires a human ShotGrid session to fill real filters — called out as a manual checkpoint, not left as vague TBD in code paths. Cadet CLI template remains a settings string until the studio command is confirmed at setup.

**Type consistency:** `ParsedCl`, `RouteState`, `ClPolicy`, `DeliveryRouteKind`, `StateRepo.record_launch_lease`, `PrepOrchestrator.run_worklist` used consistently across tasks.
