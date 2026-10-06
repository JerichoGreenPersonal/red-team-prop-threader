# mint_group Jobs Implementation Plan (Prop Threader)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drain Flightdeck `kind: mint_group` inbox jobs: join or create the Slack group, post one thread root per asset (or a shared-thread reply), record spokes and the canvas index, and write a result file Flightdeck can read. Support `live`, `test`, and `dry_run` modes.

**Architecture:** The worker's existing inbox drain routes `mint_group` jobs to a new `mint_group_jobs.process_mint_group_job`. A `PeopleResolver` maps sheet people (name + email) to Slack ids with one `users.list` per job (email lookup when the scope exists). The processor reuses the existing group/history/render/spoke/canvas pieces from `mint_from_job.py` and `jobs.py`. Dry run swaps in a `PreviewSlack` that records posts instead of sending.

**Tech Stack:** Python 3.11+, slack_sdk, SQLAlchemy, pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-10-02-slack-threads-from-request-form-design.md` (copied from ReviewPrep)

**Sibling plan (Flightdeck):** `red-team-review-prep/docs/superpowers/plans/2026-10-02-slack-threads-from-request-form.md`

## Global Constraints

- Branch `feature/mint-group-jobs` from `main` @ 1.1.0. Own PR; do not push `main`.
- Threader never reads Google. Flightdeck never holds a Slack token.
- Never print token values. Do not run the laptop Threader (`.\bin\run-local.ps1`) while EAV1089717 is live. Tests use fakes/MagicMock only, never real Slack.
- Job JSON is fixed by the spec (`kind: mint_group`; keys `job_id, created_at, sent_by, flightdeck_version, mode, test_channel_id, tab_title, season_id, group{title, channel_id, creative_stakeholder, additional_stakeholders}, assets[{asset_id, name, sg_url, ic_poc[], additional_ics[], shared_thread_with}]`).
- Result file `slack_jobs/done/{job_id}.result.json`: `status` in `done | done_with_issues | failed`; per-asset `outcome` in `created | joined | shared | skipped | failed` with `not_tagged`.
- Mode rules:
  - `live`: post to `group.channel_id`; write DB, `slack_threads/`, canvas index, `sent.json`.
  - `test`: post to `test_channel_id`; people rendered as plain text (`Name (email) - would tag U... (via name)`), no @-mentions; write DB rows (scoped to the test channel, needed for join) and `slack_threads_test/` only; no canvas index; no `sent.json`.
  - `dry_run`: no Slack writes (reads allowed: `conversations.info`, `users.list`); no DB writes, no spokes, no index; write `done/{job_id}.preview.json` plus the result file.
- `/create-prop-threads` output must not change: the IC POC label is opt-in.
- Version for this feature: **1.2.0** (minor), via `.agents/skills/bumpversion/SKILL.md`.
- Run focused tests: `uv run --with pytest-timeout pytest <files> -q --tb=short --timeout=60`. Lint: `uv run ruff check <files>` and `uv run ruff format <files>`.

## File map

| File | Status | Responsibility |
| --- | --- | --- |
| `src/red_team_prop_threader/cl_jobs.py` | modify | `MintGroupPerson`, `MintGroupAsset`, `MintGroupJob`, `parse_mint_group_job(path)` |
| `src/red_team_prop_threader/thread_message_jobs.py` | modify | drain routes `mint_group` to an optional handler |
| `src/red_team_prop_threader/slack_gateway.py` | modify | `list_users(team_id)`, `lookup_user_by_email(email)` |
| `src/red_team_prop_threader/people.py` | create | `PeopleResolver`, `ResolvedPerson`, `normalize_person_name` |
| `src/red_team_prop_threader/messages.py` | modify | `AssetRootContext.requestor_label` (default `Requestor`) |
| `src/red_team_prop_threader/edits.py` | modify | keep `requestor_label` from the snapshot on edits |
| `src/red_team_prop_threader/spokes.py` | modify | `folder` arg on `upsert_season_spoke` / `occupied_asset_ids`; `find_spoke` |
| `src/red_team_prop_threader/config.py` | modify | `slack_people_team_id` (`SLACK_PEOPLE_TEAM_ID`, default `T0297NTAU`) |
| `src/red_team_prop_threader/mint_group_jobs.py` | create | `PreviewSlack`, `process_mint_group_job`, `make_mint_group_handler` |
| `src/red_team_prop_threader/worker.py` | modify | pass the mint handler to the drain |
| Tests | create/modify | `tests/test_mint_group_parse.py`, `tests/test_thread_message_jobs.py`, `tests/test_people.py`, `tests/test_messages.py`, `tests/test_spokes.py`, `tests/test_mint_group_jobs.py` |

---

### Task 1: Parse mint_group jobs and route them in the drain

**Files:**
- Modify: `src/red_team_prop_threader/cl_jobs.py` (after `parse_job`; add names to `__all__`)
- Modify: `src/red_team_prop_threader/thread_message_jobs.py:82` (`drain_thread_message_inbox`)
- Test: `tests/test_mint_group_parse.py` (create), `tests/test_thread_message_jobs.py` (append)

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class MintGroupPerson:
    name: str
    email: str

@dataclass(frozen=True, slots=True)
class MintGroupAsset:
    asset_id: int
    name: str
    sg_url: str
    ic_poc: tuple[MintGroupPerson, ...]
    additional_ics: tuple[MintGroupPerson, ...]
    shared_thread_with: int | None

@dataclass(frozen=True, slots=True)
class MintGroupJob:
    job_id: str
    mode: str                  # "live" | "test" | "dry_run"
    test_channel_id: str
    tab_title: str
    season_id: str
    sent_by: str
    group_title: str
    channel_id: str
    creative_stakeholder: MintGroupPerson | None
    additional_stakeholders: tuple[MintGroupPerson, ...]
    assets: tuple[MintGroupAsset, ...]

def parse_mint_group_job(path: Path) -> MintGroupJob | None   # None unless kind == "mint_group" and job_id/group valid
def drain_thread_message_inbox(jobs_root: Path, slack: SlackGateway, *, mint_handler: Callable[[Path, MintGroupJob], None] | None = None) -> None
```

Drain rule: `thread_message` -> existing path. `mint_group` with a handler -> handler. `mint_group` without a handler -> leave in the inbox (log once). Anything else -> existing `Unsupported job` failure. A `mint_group` file that fails to parse (bad JSON shape) -> `write_failed(..., "Invalid mint_group job")` and move to done.

- [ ] **Step 1: Write the failing tests**

`tests/test_mint_group_parse.py`:

```python
import json
from pathlib import Path

from red_team_prop_threader.cl_jobs import MintGroupPerson, parse_mint_group_job


def _job(**overrides: object) -> dict:
    data = {
        "kind": "mint_group",
        "job_id": "j1",
        "created_at": "2026-10-02T22:15:00Z",
        "sent_by": "jgreen2",
        "flightdeck_version": "2.7.0",
        "mode": "test",
        "test_channel_id": "C0B4GJSA1G8",
        "tab_title": "S32 KC_MU5",
        "season_id": "S32",
        "group": {
            "title": "S32 KCMU5 OS Assets",
            "channel_id": "C02PR101SGH",
            "creative_stakeholder": {"name": "Eduardo Agostini", "email": "eagostini@respawn.com"},
            "additional_stakeholders": [{"name": "Jason McKenzie", "email": "jamckenzie@respawn.com"}],
        },
        "assets": [
            {
                "asset_id": 38885,
                "name": "unearthed_king_foundation_02",
                "sg_url": "https://respawn.shotgunstudio.com/detail/Asset/38885",
                "ic_poc": [{"name": "Jared Bosse", "email": "jbosse@ea.com"}],
                "additional_ics": [],
                "shared_thread_with": None,
            },
            {
                "asset_id": 39302,
                "name": "unearthed_king_foundation_03",
                "sg_url": "https://respawn.shotgunstudio.com/detail/Asset/39302",
                "ic_poc": [],
                "additional_ics": [],
                "shared_thread_with": 38885,
            },
        ],
    }
    data.update(overrides)
    return data


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "j1.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_parse_mint_group_job(tmp_path: Path) -> None:
    job = parse_mint_group_job(_write(tmp_path, _job()))
    assert job is not None
    assert (job.job_id, job.mode, job.test_channel_id, job.season_id) == ("j1", "test", "C0B4GJSA1G8", "S32")
    assert job.group_title == "S32 KCMU5 OS Assets"
    assert job.channel_id == "C02PR101SGH"
    assert job.creative_stakeholder == MintGroupPerson("Eduardo Agostini", "eagostini@respawn.com")
    assert [a.asset_id for a in job.assets] == [38885, 39302]
    assert job.assets[0].ic_poc == (MintGroupPerson("Jared Bosse", "jbosse@ea.com"),)
    assert job.assets[1].shared_thread_with == 38885


def test_parse_rejects_other_kinds_and_bad_mode(tmp_path: Path) -> None:
    assert parse_mint_group_job(_write(tmp_path, _job(kind="thread_message"))) is None
    assert parse_mint_group_job(_write(tmp_path, _job(mode="yolo"))) is None
    assert parse_mint_group_job(_write(tmp_path, _job(group={"title": "", "channel_id": "C1"}))) is None
```

Append to `tests/test_thread_message_jobs.py`:

```python
def test_drain_routes_mint_group_to_handler(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from red_team_prop_threader.thread_message_jobs import drain_thread_message_inbox

    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)
    job_path = inbox / "m1.json"
    job_path.write_text(
        json.dumps({"kind": "mint_group", "job_id": "m1", "mode": "dry_run", "group": {"title": "G", "channel_id": "C1"}, "assets": []}),
        encoding="utf-8",
    )
    seen = []
    drain_thread_message_inbox(tmp_path, MagicMock(), mint_handler=lambda path, job: seen.append((path.name, job.job_id)))
    assert seen == [("m1.json", "m1")]
    assert not (tmp_path / "slack_jobs" / "failed.json").exists()


def test_drain_leaves_mint_group_without_handler(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from red_team_prop_threader.thread_message_jobs import drain_thread_message_inbox

    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)
    job_path = inbox / "m2.json"
    job_path.write_text(json.dumps({"kind": "mint_group", "job_id": "m2", "mode": "live", "group": {"title": "G", "channel_id": "C1"}, "assets": []}), encoding="utf-8")
    drain_thread_message_inbox(tmp_path, MagicMock())
    assert job_path.is_file()
    assert not (tmp_path / "slack_jobs" / "failed.json").exists()
```

(Ensure `import json` and `from pathlib import Path` exist at the top of `tests/test_thread_message_jobs.py`.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run --with pytest-timeout pytest tests/test_mint_group_parse.py tests/test_thread_message_jobs.py -q --tb=short --timeout=60`
Expected: FAIL (`ImportError: parse_mint_group_job`; drain has no `mint_handler`).

- [ ] **Step 3: Implement the parser** (append to `cl_jobs.py`; add the four names to `__all__`)

```python
_MINT_GROUP_KIND = "mint_group"
_MINT_GROUP_MODES = frozenset({"live", "test", "dry_run"})


@dataclass(frozen=True, slots=True)
class MintGroupPerson:
    """Sheet person chip: display name and email."""

    name: str
    email: str


@dataclass(frozen=True, slots=True)
class MintGroupAsset:
    """One asset row from a mint_group job."""

    asset_id: int
    name: str
    sg_url: str
    ic_poc: tuple[MintGroupPerson, ...]
    additional_ics: tuple[MintGroupPerson, ...]
    shared_thread_with: int | None


@dataclass(frozen=True, slots=True)
class MintGroupJob:
    """Flightdeck mint_group inbox job (one Request Form tab)."""

    job_id: str
    mode: str
    test_channel_id: str
    tab_title: str
    season_id: str
    sent_by: str
    group_title: str
    channel_id: str
    creative_stakeholder: MintGroupPerson | None
    additional_stakeholders: tuple[MintGroupPerson, ...]
    assets: tuple[MintGroupAsset, ...]


def _person(raw: object) -> MintGroupPerson | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    email = str(raw.get("email") or "").strip()
    return MintGroupPerson(name=name, email=email) if (name or email) else None


def _people(raw: object) -> tuple[MintGroupPerson, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(p for p in (_person(item) for item in raw) if p is not None)


def is_mint_group_file(path: Path) -> bool:
    """Return True when the JSON file declares ``kind: mint_group``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(data, dict) and data.get("kind") == _MINT_GROUP_KIND


def parse_mint_group_job(path: Path) -> MintGroupJob | None:
    """Parse a mint_group inbox JSON file, or None when invalid or another kind."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or data.get("kind") != _MINT_GROUP_KIND:
        return None
    job_id = str(data.get("job_id") or "").strip()
    mode = str(data.get("mode") or "").strip()
    group = data.get("group")
    if not job_id or mode not in _MINT_GROUP_MODES or not isinstance(group, dict):
        return None
    title = str(group.get("title") or "").strip()
    channel_id = str(group.get("channel_id") or "").strip()
    if not title or not channel_id:
        return None
    assets: list[MintGroupAsset] = []
    for raw in data.get("assets") or []:
        if not isinstance(raw, dict):
            return None
        try:
            asset_id = int(raw.get("asset_id"))
        except (TypeError, ValueError):
            return None
        shared_raw = raw.get("shared_thread_with")
        try:
            shared = int(shared_raw) if shared_raw is not None else None
        except (TypeError, ValueError):
            shared = None
        assets.append(
            MintGroupAsset(
                asset_id=asset_id,
                name=str(raw.get("name") or f"Asset {asset_id}").strip(),
                sg_url=str(raw.get("sg_url") or f"https://respawn.shotgunstudio.com/detail/Asset/{asset_id}").strip(),
                ic_poc=_people(raw.get("ic_poc")),
                additional_ics=_people(raw.get("additional_ics")),
                shared_thread_with=shared,
            )
        )
    return MintGroupJob(
        job_id=job_id,
        mode=mode,
        test_channel_id=str(data.get("test_channel_id") or "").strip(),
        tab_title=str(data.get("tab_title") or "").strip(),
        season_id=str(data.get("season_id") or "").strip(),
        sent_by=str(data.get("sent_by") or "").strip(),
        group_title=title,
        channel_id=channel_id,
        creative_stakeholder=_person(group.get("creative_stakeholder")),
        additional_stakeholders=_people(group.get("additional_stakeholders")),
        assets=tuple(assets),
    )
```

Also add `"is_mint_group_file"` to `__all__`.

- [ ] **Step 4: Route in the drain** (`thread_message_jobs.py`)

Update imports:

```python
from red_team_prop_threader.cl_jobs import parse_job, list_inbox, stamp_sent, move_to_done, write_failed, is_mint_group_file, parse_mint_group_job
```

Under `TYPE_CHECKING` add `from collections.abc import Callable` and `from red_team_prop_threader.cl_jobs import MintGroupJob`.

Replace `drain_thread_message_inbox`:

```python
def drain_thread_message_inbox(
    jobs_root: Path, slack: SlackGateway, *, mint_handler: Callable[[Path, MintGroupJob], None] | None = None
) -> None:
    """Process each inbox JSON: thread_message replies, mint_group via handler, else fail.

    Args:
        jobs_root: ReviewPrep external links root (parent of slack_jobs/).
        slack: slack gateway used for replies and uploads.
        mint_handler: called for mint_group jobs; when None they stay in the inbox.

    Returns:
        None: each inbox JSON is posted, failed, or moved as a side effect.
    """
    inbox = jobs_root / "slack_jobs" / "inbox"
    for job_path in list_inbox(jobs_root):
        if is_mint_group_file(job_path):
            if mint_handler is None:
                _LOG.info("leaving mint_group job %s for a worker with mint support", job_path.name)
                continue
            mint_job = parse_mint_group_job(job_path)
            if mint_job is None:
                job_id, _asset = _ids_from_job_file(job_path)
                write_failed(jobs_root, job_id, "", _INVALID_MINT_GROUP)
                move_to_done(jobs_root, job_path)
                continue
            mint_handler(job_path, mint_job)
            continue
        job = parse_job(job_path)
        if job is None:
            job_id, asset_id = _ids_from_job_file(job_path)
            write_failed(jobs_root, job_id, asset_id, _UNSUPPORTED_JOB)
            move_to_done(jobs_root, job_path)
            continue
        process_thread_message_job(job, inbox=inbox, slack=slack, jobs_root=jobs_root, job_json_path=job_path)
```

Add constant next to `_UNSUPPORTED_JOB`: `_INVALID_MINT_GROUP = "Invalid mint_group job"`. Update the module docstring to `"""drain ReviewPrep inbox jobs: thread_message replies and mint_group routing."""`.

- [ ] **Step 5: Run tests**

Run: `uv run --with pytest-timeout pytest tests/test_mint_group_parse.py tests/test_thread_message_jobs.py tests/test_cl_jobs.py -q --tb=short --timeout=60`
Expected: PASS. (Skip `tests/test_cl_jobs.py` if absent.)

- [ ] **Step 6: Commit**

```bash
git add src/red_team_prop_threader/cl_jobs.py src/red_team_prop_threader/thread_message_jobs.py tests/test_mint_group_parse.py tests/test_thread_message_jobs.py
git commit -m "feat: parse mint_group jobs and route them from the inbox drain"
```

---

### Task 2: Resolve sheet people to Slack users

**Files:**
- Modify: `src/red_team_prop_threader/slack_gateway.py` (after `get_user_info`)
- Modify: `src/red_team_prop_threader/config.py` (`Settings` + `from_env`)
- Create: `src/red_team_prop_threader/people.py`
- Test: `tests/test_people.py`

**Interfaces:**
- Produces:

```python
# SlackGateway
def list_users(self, *, team_id: str) -> tuple[dict[str, Any], ...]        # users.list paginated, limit 200
def lookup_user_by_email(self, email: str) -> str | None                   # users.lookupByEmail; None on users_not_found; raises PermissionDeniedError on missing_scope

# Settings
slack_people_team_id: str = "T0297NTAU"                                    # env SLACK_PEOPLE_TEAM_ID

# people.py
@dataclass(frozen=True, slots=True)
class ResolvedPerson:
    name: str
    email: str
    user_id: str          # "" when not tagged
    method: str           # "email" | "name" | ""

def normalize_person_name(text: str) -> str
class PeopleResolver:
    def __init__(self, slack: PeopleGateway, *, team_id: str) -> None
    def resolve(self, person: MintGroupPerson) -> ResolvedPerson
```

Matching: email lookup first while it works (first `PermissionDeniedError` disables it for this resolver). Then exact match of `normalize_person_name(person.name)` against `real_name`, `profile.real_name`, `profile.display_name` of non-deleted, non-bot users; must map to exactly one user id, else not tagged. `normalize_person_name`: NFKD, drop combining marks, lowercase, collapse whitespace, strip.

- [ ] **Step 1: Write the failing tests** (`tests/test_people.py`)

```python
from unittest.mock import MagicMock

import pytest

from red_team_prop_threader._errors import PermissionDeniedError
from red_team_prop_threader.cl_jobs import MintGroupPerson
from red_team_prop_threader.people import PeopleResolver, normalize_person_name

USERS = (
    {"id": "U1", "real_name": "Jared Bosse", "profile": {"display_name": "jbosse"}},
    {"id": "U2", "real_name": "Ryan Lastimosa", "profile": {}},
    {"id": "U3", "real_name": "Ryan Lastimosa", "profile": {}},
    {"id": "U4", "real_name": "José Núñez", "profile": {}},
    {"id": "U5", "real_name": "Gone Person", "deleted": True, "profile": {}},
    {"id": "B1", "real_name": "Jared Bosse", "is_bot": True, "profile": {}},
)


def _slack(email_result: object = PermissionDeniedError("missing_scope")) -> MagicMock:
    slack = MagicMock()
    slack.list_users.return_value = USERS
    if isinstance(email_result, Exception):
        slack.lookup_user_by_email.side_effect = email_result
    else:
        slack.lookup_user_by_email.return_value = email_result
    return slack


def test_normalize_person_name() -> None:
    assert normalize_person_name("  José   NÚÑEZ ") == "jose nunez"


def test_name_match_unique_and_ambiguous() -> None:
    slack = _slack()
    resolver = PeopleResolver(slack, team_id="T0297NTAU")
    jared = resolver.resolve(MintGroupPerson("Jared Bosse", "jbosse@ea.com"))
    assert (jared.user_id, jared.method) == ("U1", "name")
    assert resolver.resolve(MintGroupPerson("Ryan Lastimosa", "rlastimosa@respawn.com")).user_id == ""
    assert resolver.resolve(MintGroupPerson("Jose Nunez", "jn@respawn.com")).user_id == "U4"
    assert resolver.resolve(MintGroupPerson("Gone Person", "g@respawn.com")).user_id == ""
    slack.list_users.assert_called_once_with(team_id="T0297NTAU")
    assert slack.lookup_user_by_email.call_count == 1


def test_email_lookup_wins_when_scope_present() -> None:
    slack = _slack(email_result="U9")
    resolver = PeopleResolver(slack, team_id="T0297NTAU")
    person = resolver.resolve(MintGroupPerson("Ryan Lastimosa", "rlastimosa@respawn.com"))
    assert (person.user_id, person.method) == ("U9", "email")


def test_email_miss_falls_back_to_name() -> None:
    slack = _slack(email_result=None)
    person = PeopleResolver(slack, team_id="T0297NTAU").resolve(MintGroupPerson("Jared Bosse", "x@ea.com"))
    assert (person.user_id, person.method) == ("U1", "name")


def test_gateway_list_users_paginates() -> None:
    from red_team_prop_threader.slack_gateway import SlackGateway

    client = MagicMock()
    client.users_list.side_effect = [
        {"ok": True, "members": [{"id": "U1"}], "response_metadata": {"next_cursor": "c2"}},
        {"ok": True, "members": [{"id": "U2"}], "response_metadata": {"next_cursor": ""}},
    ]
    users = SlackGateway(client).list_users(team_id="T0297NTAU")
    assert [u["id"] for u in users] == ["U1", "U2"]
    assert client.users_list.call_args_list[1].kwargs == {"team_id": "T0297NTAU", "limit": 200, "cursor": "c2"}


@pytest.mark.parametrize("value,expected", [("", "T0297NTAU"), ("T039ZEK3W", "T039ZEK3W")])
def test_settings_team_id(monkeypatch: pytest.MonkeyPatch, value: str, expected: str) -> None:
    from red_team_prop_threader.config import Settings

    for key in ("SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_APP_TOKEN", "SHOTGRID_SCRIPT_NAME", "SHOTGRID_SCRIPT_KEY"):
        monkeypatch.setenv(key, "x")
    monkeypatch.setenv("SLACK_PEOPLE_TEAM_ID", value)
    assert Settings.from_env().slack_people_team_id == expected
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --with pytest-timeout pytest tests/test_people.py -q --tb=short --timeout=60`
Expected: FAIL (`ModuleNotFoundError: red_team_prop_threader.people`).

- [ ] **Step 3: Gateway methods** (`slack_gateway.py`, after `get_user_info`)

```python
    def list_users(self, *, team_id: str) -> tuple[dict[str, Any], ...]:
        """List workspace users via users.list (Enterprise Grid needs ``team_id``).

        Args:
            team_id: workspace id, e.g. ``T0297NTAU`` (Respawn).

        Returns:
            tuple[dict[str, Any], ...]: raw user objects in API order.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        users: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"team_id": team_id, "limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            response = self._call("users_list", **kwargs)
            page = response.get("members") or []
            if not isinstance(page, list):
                raise ExternalServiceError("users.list returned invalid members")
            users.extend(item for item in page if isinstance(item, dict))
            metadata = response.get("response_metadata") or {}
            next_cursor = metadata.get("next_cursor") if isinstance(metadata, dict) else None
            if not next_cursor:
                return tuple(users)
            cursor = str(next_cursor)

    def lookup_user_by_email(self, email: str) -> str | None:
        """Return the user id for an email, or None when no user has it.

        Raises:
            PermissionDeniedError: when the token lacks ``users:read.email``.
            ExternalServiceError: on other Slack failures.
        """
        try:
            response = self._call("users_lookupByEmail", email=email)
        except NotFoundError:
            return None
        except ExternalServiceError as exc:
            if "users_not_found" in str(exc):
                return None
            raise
        user = response.get("user")
        return str(user.get("id") or "") or None if isinstance(user, dict) else None
```

Confirm `NotFoundError` and `PermissionDeniedError` are imported at the top of `slack_gateway.py` (they are used by `_translate_slack_error`); add `users_not_found` to `_NOT_FOUND_ERRORS`. Check that `_translate_slack_error` maps `missing_scope` to `PermissionDeniedError`; if it does not, add `"missing_scope"` to whichever permission set it uses.

- [ ] **Step 4: Settings field** (`config.py`)

Add constant `_DEFAULT_SLACK_PEOPLE_TEAM_ID = "T0297NTAU"`. Add field after `reviewprep_external_links_root`:

```python
    slack_people_team_id: str = _DEFAULT_SLACK_PEOPLE_TEAM_ID
```

In `from_env` before `return cls(`:

```python
        slack_people_team_id = os.environ.get("SLACK_PEOPLE_TEAM_ID", "").strip() or _DEFAULT_SLACK_PEOPLE_TEAM_ID
```

and pass `slack_people_team_id=slack_people_team_id,` in the constructor call.

- [ ] **Step 5: Create `src/red_team_prop_threader/people.py`**

```python
"""map Request Form people (name + email) to Slack user ids."""

from __future__ import annotations

import logging
import unicodedata
from typing import TYPE_CHECKING, Any, Protocol
from dataclasses import dataclass

from red_team_prop_threader._errors import PermissionDeniedError


if TYPE_CHECKING:
    from red_team_prop_threader.cl_jobs import MintGroupPerson


__all__ = ("PeopleResolver", "ResolvedPerson", "normalize_person_name")

_LOG = logging.getLogger(__name__)


class PeopleGateway(Protocol):
    """slack methods the resolver needs."""

    def list_users(self, *, team_id: str) -> tuple[dict[str, Any], ...]:
        """users.list for one workspace."""

    def lookup_user_by_email(self, email: str) -> str | None:
        """users.lookupByEmail."""


@dataclass(frozen=True, slots=True)
class ResolvedPerson:
    """one sheet person and the Slack id it maps to ("" when not tagged)."""

    name: str
    email: str
    user_id: str
    method: str


def normalize_person_name(text: str) -> str:
    """Lowercase, strip accents, and collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(plain.lower().split())


class PeopleResolver:
    """email lookup when the scope exists, else unique exact name match."""

    def __init__(self, slack: PeopleGateway, *, team_id: str) -> None:
        """Initialize with a gateway and the workspace id used for users.list."""
        self._slack = slack
        self._team_id = team_id
        self._email_enabled = True
        self._by_name: dict[str, set[str]] | None = None

    def _name_index(self) -> dict[str, set[str]]:
        if self._by_name is None:
            index: dict[str, set[str]] = {}
            for user in self._slack.list_users(team_id=self._team_id):
                if user.get("deleted") or user.get("is_bot"):
                    continue
                user_id = str(user.get("id") or "")
                profile = user.get("profile") if isinstance(user.get("profile"), dict) else {}
                names = {str(user.get("real_name") or ""), str(profile.get("real_name") or ""), str(profile.get("display_name") or "")}
                for name in names:
                    key = normalize_person_name(name)
                    if key and user_id:
                        index.setdefault(key, set()).add(user_id)
            self._by_name = index
        return self._by_name

    def resolve(self, person: MintGroupPerson) -> ResolvedPerson:
        """Return the Slack id for one person, or an untagged result."""
        if self._email_enabled and person.email:
            try:
                user_id = self._slack.lookup_user_by_email(person.email)
            except PermissionDeniedError:
                _LOG.info("users:read.email not granted; matching people by name")
                self._email_enabled = False
            else:
                if user_id:
                    return ResolvedPerson(person.name, person.email, user_id, "email")
        matches = self._name_index().get(normalize_person_name(person.name), set())
        if len(matches) == 1:
            return ResolvedPerson(person.name, person.email, next(iter(matches)), "name")
        return ResolvedPerson(person.name, person.email, "", "")
```

- [ ] **Step 6: Run tests**

Run: `uv run --with pytest-timeout pytest tests/test_people.py tests/test_config.py tests/test_slack_gateway.py -q --tb=short --timeout=60`
Expected: PASS (skip files that do not exist).

- [ ] **Step 7: Commit**

```bash
git add src/red_team_prop_threader/slack_gateway.py src/red_team_prop_threader/config.py src/red_team_prop_threader/people.py tests/test_people.py
git commit -m "feat: resolve Request Form people to Slack users"
```

---

### Task 3: Opt-in IC POC label and spoke folder support

**Files:**
- Modify: `src/red_team_prop_threader/messages.py` (`AssetRootContext`, `render_asset_root`)
- Modify: `src/red_team_prop_threader/edits.py:444` (`_asset_context_from_snapshot`)
- Modify: `src/red_team_prop_threader/spokes.py` (`upsert_season_spoke`, `occupied_asset_ids`, new `find_spoke`)
- Test: `tests/test_messages.py`, `tests/test_spokes.py` (append; create if missing)

**Interfaces:**
- Produces: `AssetRootContext.requestor_label: str = "Requestor"`; snapshot key `requestor_label`; `upsert_season_spoke(..., folder: str = "slack_threads")`; `occupied_asset_ids(share_root, *, folder: str = "slack_threads")`; `find_spoke(share_root, asset_id, *, folder="slack_threads") -> dict[str, str] | None` (first match across `*.json`, sorted by name).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_messages.py`:

```python
def test_asset_root_ic_poc_label_is_opt_in() -> None:
    from red_team_prop_threader.messages import AssetRootContext, render_asset_root

    base = dict(
        asset_entity_id=1, asset_name="a", asset_url="https://respawn.shotgunstudio.com/detail/Asset/1", group_title="G",
        created_ts=0, asset_animator_id="U1", asset_additional_ids=(), group_animator_display="", group_additional_displays=(),
        group_links=(), asset_links=(), message_identity="g:1",
    )
    default_text = str(render_asset_root(AssetRootContext(**base))["blocks"][0]["text"]["text"])
    ic_text = str(render_asset_root(AssetRootContext(**base, requestor_label="IC POC"))["blocks"][0]["text"]["text"])
    assert "*Requestor:* <@U1>" in default_text
    assert "*IC POC:* <@U1>" in ic_text
    empty = str(render_asset_root(AssetRootContext(**{**base, "asset_animator_id": ""}, requestor_label="IC POC"))["blocks"][0]["text"]["text"])
    assert "*IC POC:* unassigned" in empty
```

Append to `tests/test_spokes.py`:

```python
def test_spokes_folder_argument(tmp_path) -> None:
    from red_team_prop_threader.spokes import find_spoke, occupied_asset_ids, upsert_season_spoke

    assert upsert_season_spoke(
        tmp_path, season_id="S32", asset_id=7, permalink="p", channel_id="C1", thread_ts="1.2", source="mint", updated_at="t", folder="slack_threads_test"
    )
    assert (tmp_path / "slack_threads_test" / "S32.json").is_file()
    assert not (tmp_path / "slack_threads").exists()
    assert occupied_asset_ids(tmp_path, folder="slack_threads_test") == frozenset({7})
    assert occupied_asset_ids(tmp_path) == frozenset()
    assert find_spoke(tmp_path, 7, folder="slack_threads_test")["thread_ts"] == "1.2"
    assert find_spoke(tmp_path, 7) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --with pytest-timeout pytest tests/test_messages.py tests/test_spokes.py -q --tb=short --timeout=60 -k "opt_in or folder_argument"`
Expected: FAIL (`unexpected keyword argument 'requestor_label'` / `'folder'`).

- [ ] **Step 3: Implement the label**

In `AssetRootContext` add the field last, and document it in the docstring Args (`requestor_label: label for the asset people line; mint_group jobs use "IC POC".`):

```python
    requestor_label: str = "Requestor"
```

In `render_asset_root`, replace the two `"*Requestor:*"` literals:

```python
    label = _escape(context.requestor_label or "Requestor")
    ...
        requestor_parts.append(f"*{label}:* {_mention(asset_animator_id)}")
    ...
    requestor_line = f"*{label}:* unassigned" if not requestor_parts else "  ".join(requestor_parts)
```

In `edits._asset_context_from_snapshot`, add to the constructor call:

```python
        requestor_label=str(snapshot.get("requestor_label") or "Requestor"),
```

- [ ] **Step 4: Implement spoke folders** (`spokes.py`)

`upsert_season_spoke`: add keyword `folder: str = "slack_threads",` after `updated_at: str,` and change the path line to `path = Path(share_root) / folder / f"{season}.json"`; change the docstring to ``"""Upsert one asset key in ``{folder}/{season}.json``. skip corrupt files."""``.

`occupied_asset_ids`: signature `def occupied_asset_ids(share_root: Path, *, folder: str = "slack_threads") -> frozenset[int]:` and `folder_path = Path(share_root) / folder` (rename the local to avoid shadowing; update the two uses).

Add:

```python
def find_spoke(share_root: Path, asset_id: int, *, folder: str = "slack_threads") -> dict[str, str] | None:
    """Return the first spoke entry for ``asset_id`` across ``{folder}/*.json``."""
    folder_path = Path(share_root) / folder
    if not folder_path.is_dir():
        return None
    for path in sorted(folder_path.glob("*.json"), key=lambda p: p.name):
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        assets = data.get("assets") if isinstance(data, dict) else None
        entry = assets.get(str(int(asset_id))) if isinstance(assets, dict) else None
        if isinstance(entry, dict):
            return {str(k): str(v) for k, v in entry.items()}
    return None
```

- [ ] **Step 5: Run tests (including existing edit and mint tests)**

Run: `uv run --with pytest-timeout pytest tests/test_messages.py tests/test_spokes.py tests/test_edits.py tests/test_mint_from_job.py -q --tb=short --timeout=60`
Expected: PASS (skip files that do not exist).

- [ ] **Step 6: Commit**

```bash
git add src/red_team_prop_threader/messages.py src/red_team_prop_threader/edits.py src/red_team_prop_threader/spokes.py tests/test_messages.py tests/test_spokes.py
git commit -m "feat: opt-in IC POC label and spoke folder argument"
```

---

### Task 4: Process a mint_group job

**Files:**
- Create: `src/red_team_prop_threader/mint_group_jobs.py`
- Test: `tests/test_mint_group_jobs.py`

**Interfaces:**
- Consumes: `MintGroupJob`, `MintGroupAsset`, `MintGroupPerson`, `stamp_sent`, `write_failed`, `move_to_done` (cl_jobs); `PeopleResolver`, `ResolvedPerson` (Task 2); `AssetRootContext(requestor_label=...)`, `GroupSummaryContext`, `render_asset_root`, `render_group_summary` (messages); `occupied_asset_ids`, `upsert_season_spoke`, `find_spoke` (Task 3); `normalize_group_title` (validation); `Repositories`, `MessageKind`, `NewMessageInput` (repositories); `session_scope` (db); `Group` (tables); `CanvasService`, `GroupIndexRequest`, `IndexedAsset` (canvas).
- Produces:

```python
class PreviewSlack:
    """records writes; forwards reads (conversations.info, users.list, lookupByEmail) to the real gateway."""
    posts: list[dict[str, Any]]
    updates: list[dict[str, Any]]

def process_mint_group_job(
    job_path: Path,
    job: MintGroupJob,
    *,
    slack: SlackGateway,
    engine: Engine | None,
    jobs_root: Path,
    team_id: str,
    workspace_id: str,
    resolver: PeopleResolver | None = None,
    now: datetime | None = None,
) -> dict[str, Any]                       # the result dict that was written

def make_mint_group_handler(*, slack: SlackGateway, engine: Engine, jobs_root: Path, team_id: str) -> Callable[[Path, MintGroupJob], None]
```

Processing order (all modes):
1. Destination = `job.test_channel_id` in test mode (fail `Test channel missing` when blank), else `job.channel_id`.
2. `conversations.info(destination).is_member` must be true, else job fails `Bot not in channel`.
3. Spoke folder = `slack_threads_test` in test mode, else `slack_threads`. Assets already in that folder -> outcome `skipped` (`note: Already threaded`).
4. Resolve every person once. Live mode: mention ids. Test mode: replace `<@U...>` in rendered text with `Name (email) - would tag U... (via name)`. People with no id -> `not_tagged`. Tagged people not in the destination channel -> note `mentioned, not in channel: Name`.
5. Group: find `(destination, normalize_group_title(title))`. Missing and no new roots to post -> group outcome `not_needed`, no top post. Missing -> post top post (`included_asset_count` = number of new roots), record `GROUP_SUMMARY`. Present -> outcome `joined`; after roots are posted, `update_message` the summary with the count increased by the new roots and save via `touch_editor(editor_id="mint_group")`.
6. Roots in job order (non-shared assets): render with `requestor_label="IC POC"`, post, permalink, record `ASSET_ROOT` (snapshot includes `requestor_label`), upsert spoke (`source="mint"`), outcome `created`. A post failure -> outcome `failed` with the error; continue.
7. Shared assets: target thread = root created in this job, else `find_spoke(target, folder)`. Missing -> `failed: Shared thread target not found`. Else post reply `Also tracked here: <name> (ShotGrid ID: <id>)` in the target thread; spoke entry for the shared asset points at the target's channel/ts/permalink; outcome `shared`; append to summary snapshot `shared_assets`.
8. Live only: rebuild the group's canvas section via `CanvasService(slack).ensure_canvas(destination, create=True)` + `index_batch` with every latest root in the group plus `shared_assets` (each with its target permalink). Index failure -> job issue `Index not updated: <error>` (status `done_with_issues`, not `failed`).
9. Live only: `stamp_sent(jobs_root, asset_id, job_id)` for each `created` / `shared` asset.
10. Dry run: write `done/{job_id}.preview.json` with `{"job_id", "destination", "group_outcome", "posts": PreviewSlack.posts, "updates": PreviewSlack.updates}`. No DB writes, no spokes, no index (group lookup is read-only).
11. Write `done/{job_id}.result.json`; status `failed` when the job failed before any root, `done_with_issues` when any asset failed/has `not_tagged`/notes or the index failed, else `done`. On `failed`, also `write_failed(jobs_root, job_id, "", error)`. Always `move_to_done(jobs_root, job_path)` last.

- [ ] **Step 1: Write the failing tests** (`tests/test_mint_group_jobs.py`)

```python
import json
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock
from collections.abc import Generator

import pytest
from sqlalchemy import event, create_engine
from sqlalchemy.engine import Engine

from red_team_prop_threader.tables import Base
from red_team_prop_threader.cl_jobs import MintGroupJob, MintGroupAsset, MintGroupPerson
from red_team_prop_threader.mint_group_jobs import process_mint_group_job

NOW = datetime(2026, 10, 2, 22, 15, tzinfo=timezone.utc)
ED = MintGroupPerson("Eduardo Agostini", "eagostini@respawn.com")
JB = MintGroupPerson("Jared Bosse", "jbosse@ea.com")
NOBODY = MintGroupPerson("Mine Yilmaz-Ulas", "mulas@ea.com")


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    e = create_engine("sqlite:///:memory:")

    @event.listens_for(e, "connect")
    def _pragmas(dbapi_conn: object, _record: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(e)
    yield e
    e.dispose()


class FakeSlack:
    """records posts; channel members U1 (Eduardo) only; bot is a member."""

    def __init__(self, *, member: bool = True) -> None:
        self.member = member
        self.posts: list[dict] = []
        self.updates: list[dict] = []
        self._n = 0
        self.canvas = MagicMock()

    def get_conversation_info(self, channel_id: str) -> dict:
        return {"id": channel_id, "is_member": self.member}

    def get_conversation_members(self, channel_id: str) -> tuple[str, ...]:
        return ("U1",)

    def list_users(self, *, team_id: str) -> tuple[dict, ...]:
        return (
            {"id": "U1", "real_name": "Eduardo Agostini", "profile": {}},
            {"id": "U2", "real_name": "Jared Bosse", "profile": {}},
        )

    def lookup_user_by_email(self, email: str) -> str | None:
        from red_team_prop_threader._errors import PermissionDeniedError

        raise PermissionDeniedError("missing_scope")

    def get_user_info(self, user_id: str) -> dict:
        names = {"U1": "Eduardo Agostini", "U2": "Jared Bosse"}
        return {"id": user_id, "profile": {"real_name": names.get(user_id, user_id)}}

    def post_message(self, channel_id: str, *, text: str, blocks=None, thread_ts=None) -> dict:
        self._n += 1
        ts = f"1000.{self._n:04d}"
        self.posts.append({"channel": channel_id, "text": text, "blocks": blocks, "thread_ts": thread_ts, "ts": ts})
        return {"ts": ts}

    def update_message(self, channel_id: str, ts: str, *, text: str, blocks=None) -> dict:
        self.updates.append({"channel": channel_id, "ts": ts, "text": text, "blocks": blocks})
        return {"ts": ts}

    def get_permalink(self, channel_id: str, message_ts: str) -> str:
        return f"https://respawn.slack.com/archives/{channel_id}/p{message_ts.replace('.', '')}"


def _job(mode: str = "live", assets: tuple[MintGroupAsset, ...] | None = None, job_id: str = "j1") -> MintGroupJob:
    url = "https://respawn.shotgunstudio.com/detail/Asset/"
    return MintGroupJob(
        job_id=job_id,
        mode=mode,
        test_channel_id="C0B4GJSA1G8",
        tab_title="S32 KC_MU5",
        season_id="S32",
        sent_by="jgreen2",
        group_title="S32 KCMU5 OS Assets",
        channel_id="C02PR101SGH",
        creative_stakeholder=ED,
        additional_stakeholders=(),
        assets=assets
        or (
            MintGroupAsset(38885, "unearthed_king_foundation_02", f"{url}38885", (JB,), (NOBODY,), None),
            MintGroupAsset(39302, "unearthed_king_foundation_03", f"{url}39302", (), (), 38885),
        ),
    )


def _run(tmp_path: Path, engine: Engine | None, slack: FakeSlack, job: MintGroupJob, monkeypatch: pytest.MonkeyPatch) -> dict:
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    job_path = inbox / f"{job.job_id}.json"
    job_path.write_text(json.dumps({"kind": "mint_group", "job_id": job.job_id}), encoding="utf-8")
    monkeypatch.setattr("red_team_prop_threader.mint_group_jobs.CanvasService", lambda _slack: slack.canvas)
    slack.canvas.ensure_canvas.return_value = "F1"
    return process_mint_group_job(
        job_path, job, slack=slack, engine=engine, jobs_root=tmp_path, team_id="T0297NTAU", workspace_id="T0297NTAU", now=NOW  # type: ignore[arg-type]
    )


def test_live_creates_group_root_and_shared_reply(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    slack = FakeSlack()
    result = _run(tmp_path, engine, slack, _job(), monkeypatch)
    assert result["status"] == "done_with_issues"
    assert result["group"]["outcome"] == "created"
    top, root, reply = slack.posts
    assert top["channel"] == "C02PR101SGH" and top["thread_ts"] is None
    assert "*1* asset(s) included." in json.dumps(top["blocks"])
    root_text = json.dumps(root["blocks"])
    assert "*IC POC:* <@U2>" in root_text
    assert reply["thread_ts"] == root["ts"]
    assert reply["text"] == "Also tracked here: unearthed_king_foundation_03 (ShotGrid ID: 39302)"
    outcomes = {a["asset_id"]: a for a in result["assets"]}
    assert outcomes[38885]["outcome"] == "created"
    assert outcomes[38885]["not_tagged"] == ["Mine Yilmaz-Ulas"]
    assert "mentioned, not in channel: Jared Bosse" in outcomes[38885]["notes"]
    assert outcomes[39302]["outcome"] == "shared"
    season = json.loads((tmp_path / "slack_threads" / "S32.json").read_text(encoding="utf-8"))
    assert season["assets"]["39302"]["thread_ts"] == root["ts"]
    assert season["assets"]["38885"]["source"] == "mint"
    slack.canvas.index_batch.assert_called_once()
    indexed = slack.canvas.index_batch.call_args.args[0]
    assert sorted(a.entity_id for a in indexed.assets) == [38885, 39302]
    sent = json.loads((tmp_path / "slack_jobs" / "sent.json").read_text(encoding="utf-8"))
    assert "j1" in sent["38885"] and "j1" in sent["39302"]
    assert (tmp_path / "slack_jobs" / "done" / "j1.result.json").is_file()
    assert (tmp_path / "slack_jobs" / "done" / "j1.json").is_file()


def test_live_join_updates_count_and_skips_threaded(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    slack = FakeSlack()
    url = "https://respawn.shotgunstudio.com/detail/Asset/"
    _run(tmp_path, engine, slack, _job(assets=(MintGroupAsset(1, "a", f"{url}1", (JB,), (), None),)), monkeypatch)
    first_top_ts = slack.posts[0]["ts"]
    slack.posts.clear()
    result = _run(
        tmp_path, engine, slack,
        _job(assets=(MintGroupAsset(1, "a", f"{url}1", (JB,), (), None), MintGroupAsset(2, "b", f"{url}2", (JB,), (), None)), job_id="j2"),
        monkeypatch,
    )
    assert result["group"]["outcome"] == "joined"
    assert len(slack.posts) == 1 and slack.posts[0]["thread_ts"] is None
    assert {a["asset_id"]: a["outcome"] for a in result["assets"]} == {1: "skipped", 2: "created"}
    assert slack.updates[-1]["ts"] == first_top_ts
    assert "*2* asset(s) included." in json.dumps(slack.updates[-1]["blocks"])


def test_test_mode_plain_names_and_test_folder(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    slack = FakeSlack()
    result = _run(tmp_path, engine, slack, _job(mode="test"), monkeypatch)
    assert {p["channel"] for p in slack.posts} == {"C0B4GJSA1G8"}
    everything = json.dumps([p["blocks"] for p in slack.posts if p["blocks"]])
    assert "<@" not in everything
    assert "Jared Bosse (jbosse@ea.com) - would tag U2 (via name)" in everything
    assert (tmp_path / "slack_threads_test" / "S32.json").is_file()
    assert not (tmp_path / "slack_threads").exists()
    assert not (tmp_path / "slack_jobs" / "sent.json").exists()
    slack.canvas.index_batch.assert_not_called()
    assert result["destination"] == "C0B4GJSA1G8"


def test_dry_run_writes_preview_only(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    slack = FakeSlack()
    result = _run(tmp_path, engine, slack, _job(mode="dry_run"), monkeypatch)
    assert slack.posts == []
    preview = json.loads((tmp_path / "slack_jobs" / "done" / "j1.preview.json").read_text(encoding="utf-8"))
    assert len(preview["posts"]) == 3
    assert preview["group_outcome"] == "created"
    assert not (tmp_path / "slack_threads").exists()
    assert result["status"] in {"done", "done_with_issues"}
    second = _run(tmp_path, engine, FakeSlack(), _job(mode="dry_run", job_id="j2"), monkeypatch)
    assert second["group"]["outcome"] == "created"


def test_shared_only_job_posts_no_top_post(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://respawn.shotgunstudio.com/detail/Asset/"
    slack = FakeSlack()
    result = _run(tmp_path, engine, slack, _job(assets=(MintGroupAsset(5, "x", f"{url}5", (), (), 999),)), monkeypatch)
    assert result["group"]["outcome"] == "not_needed"
    assert slack.posts == []


def test_bot_not_in_channel_fails_job(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    slack = FakeSlack(member=False)
    result = _run(tmp_path, engine, slack, _job(), monkeypatch)
    assert (result["status"], result["error"]) == ("failed", "Bot not in channel")
    assert slack.posts == []
    failed = json.loads((tmp_path / "slack_jobs" / "failed.json").read_text(encoding="utf-8"))
    assert failed[0]["job_id"] == "j1" and failed[0]["error"] == "Bot not in channel"
    assert (tmp_path / "slack_jobs" / "done" / "j1.json").is_file()


def test_shared_target_missing(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://respawn.shotgunstudio.com/detail/Asset/"
    result = _run(tmp_path, engine, FakeSlack(), _job(assets=(MintGroupAsset(5, "x", f"{url}5", (), (), 999),)), monkeypatch)
    assert result["assets"][0]["outcome"] == "failed"
    assert result["assets"][0]["error"] == "Shared thread target not found"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --with pytest-timeout pytest tests/test_mint_group_jobs.py -q --tb=short --timeout=60`
Expected: FAIL (`ModuleNotFoundError: red_team_prop_threader.mint_group_jobs`).

- [ ] **Step 3: Implement `src/red_team_prop_threader/mint_group_jobs.py`**

```python
"""process Flightdeck mint_group jobs: one group, many thread roots."""

from __future__ import annotations

import re
import json
import logging
from typing import TYPE_CHECKING, Any
from datetime import datetime, timezone
from dataclasses import field, dataclass

from sqlalchemy import select

from red_team_prop_threader.db import session_scope
from red_team_prop_threader.canvas import CanvasService, IndexedAsset, GroupIndexRequest
from red_team_prop_threader.people import PeopleResolver, ResolvedPerson
from red_team_prop_threader.spokes import find_spoke, occupied_asset_ids, upsert_season_spoke
from red_team_prop_threader.tables import Group
from red_team_prop_threader.cl_jobs import stamp_sent, move_to_done, write_failed
from red_team_prop_threader.messages import AssetRootContext, GroupSummaryContext, render_asset_root, render_group_summary
from red_team_prop_threader.validation import normalize_group_title
from red_team_prop_threader.repositories import MessageKind, Repositories, NewMessageInput


if TYPE_CHECKING:
    from pathlib import Path
    from collections.abc import Callable

    from sqlalchemy.engine import Engine

    from red_team_prop_threader.cl_jobs import MintGroupJob, MintGroupAsset, MintGroupPerson
    from red_team_prop_threader.slack_gateway import SlackGateway


__all__ = ("PreviewSlack", "make_mint_group_handler", "process_mint_group_job")

_LOG = logging.getLogger(__name__)
_MENTION_RE = re.compile(r"<@([UW][A-Z0-9]+)>")
_LIVE_FOLDER = "slack_threads"
_TEST_FOLDER = "slack_threads_test"


class _JobFailed(Exception):
    """job-level failure; message is shown to Flightdeck verbatim."""


class PreviewSlack:
    """dry-run gateway: records writes, forwards read-only calls."""

    def __init__(self, real: Any) -> None:
        """Wrap the real gateway for read-only calls."""
        self._real = real
        self.posts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []

    def get_conversation_info(self, channel_id: str) -> dict[str, Any]:
        return self._real.get_conversation_info(channel_id)

    def get_conversation_members(self, channel_id: str) -> tuple[str, ...]:
        return self._real.get_conversation_members(channel_id)

    def list_users(self, *, team_id: str) -> tuple[dict[str, Any], ...]:
        return self._real.list_users(team_id=team_id)

    def lookup_user_by_email(self, email: str) -> str | None:
        return self._real.lookup_user_by_email(email)

    def get_user_info(self, user_id: str) -> dict[str, Any]:
        return self._real.get_user_info(user_id)

    def post_message(self, channel_id: str, *, text: str, blocks: list[dict[str, Any]] | None = None, thread_ts: str | None = None) -> dict[str, Any]:
        ts = f"preview.{len(self.posts) + 1}"
        self.posts.append({"channel": channel_id, "text": text, "blocks": blocks, "thread_ts": thread_ts, "ts": ts})
        return {"ts": ts}

    def update_message(self, channel_id: str, ts: str, *, text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        self.updates.append({"channel": channel_id, "ts": ts, "text": text, "blocks": blocks})
        return {"ts": ts}

    def get_permalink(self, channel_id: str, message_ts: str) -> str:
        return f"preview://{channel_id}/{message_ts}"


@dataclass
class _AssetOutcome:
    asset_id: int
    name: str
    outcome: str = ""
    permalink: str = ""
    error: str = ""
    not_tagged: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "outcome": self.outcome,
            "permalink": self.permalink,
            "error": self.error,
            "not_tagged": self.not_tagged,
            "notes": self.notes,
        }


def _blocks(rendered: dict[str, object]) -> list[dict[str, Any]]:
    raw = rendered.get("blocks")
    if not isinstance(raw, list):
        return []
    return [{str(k): v for k, v in block.items()} for block in raw if isinstance(block, dict)]


def _defang(value: Any, labels: dict[str, str]) -> Any:
    """Replace ``<@U…>`` mentions with plain labels everywhere in a payload."""
    if isinstance(value, str):
        return _MENTION_RE.sub(lambda m: labels.get(m.group(1), m.group(1)), value)
    if isinstance(value, list):
        return [_defang(item, labels) for item in value]
    if isinstance(value, dict):
        return {k: _defang(v, labels) for k, v in value.items()}
    return value


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


class _Run:
    """state for one job run."""

    def __init__(self, job: MintGroupJob, *, slack: Any, engine: Engine | None, jobs_root: Path, team_id: str, workspace_id: str, resolver: PeopleResolver | None, now: datetime) -> None:
        self.job = job
        self.mode = job.mode
        self.persist = job.mode != "dry_run"
        self.slack = PreviewSlack(slack) if job.mode == "dry_run" else slack
        self.engine = engine
        self.jobs_root = jobs_root
        self.workspace_id = workspace_id
        self.resolver = resolver or PeopleResolver(self.slack, team_id=team_id)
        self.now = now
        self.folder = _TEST_FOLDER if job.mode == "test" else _LIVE_FOLDER
        self.destination = job.test_channel_id if job.mode == "test" else job.channel_id
        self.labels: dict[str, str] = {}
        self.members: set[str] = set()
        self.issues: list[str] = []
        self.group_outcome = ""
        self.group_permalink = ""
        self.outcomes = [_AssetOutcome(a.asset_id, a.name) for a in job.assets]

    # people --------------------------------------------------------------
    def person_ids(self, people: tuple[MintGroupPerson, ...], outcome: _AssetOutcome | None) -> tuple[str, ...]:
        ids: list[str] = []
        for person in people:
            resolved: ResolvedPerson = self.resolver.resolve(person)
            if not resolved.user_id:
                if outcome is not None:
                    outcome.not_tagged.append(person.name or person.email)
                else:
                    self.issues.append(f"not tagged: {person.name or person.email}")
                continue
            self.labels[resolved.user_id] = f"{person.name} ({person.email}) - would tag {resolved.user_id} (via {resolved.method})"
            if resolved.user_id not in self.members:
                note = f"mentioned, not in channel: {person.name}"
                if outcome is not None:
                    outcome.notes.append(note)
                else:
                    self.issues.append(note)
            if resolved.user_id not in ids:
                ids.append(resolved.user_id)
        return tuple(ids)

    def display(self, person: MintGroupPerson | None) -> str:
        return person.name if person is not None else ""

    def render(self, rendered: dict[str, object]) -> tuple[str, list[dict[str, Any]]]:
        text, blocks = str(rendered["text"]), _blocks(rendered)
        if self.mode == "test":
            return _defang(text, self.labels), _defang(blocks, self.labels)
        return text, blocks

    # main ----------------------------------------------------------------
    def run(self) -> None:
        job = self.job
        if self.mode == "test" and not self.destination:
            raise _JobFailed("Test channel missing")
        info = self.slack.get_conversation_info(self.destination)
        if not info.get("is_member"):
            raise _JobFailed("Bot not in channel")
        try:
            self.members = set(self.slack.get_conversation_members(self.destination))
        except Exception:  # noqa: BLE001 - membership only drives notes
            self.members = set()

        occupied = occupied_asset_ids(self.jobs_root, folder=self.folder)
        to_root: list[tuple[MintGroupAsset, _AssetOutcome]] = []
        to_share: list[tuple[MintGroupAsset, _AssetOutcome]] = []
        for asset, outcome in zip(job.assets, self.outcomes, strict=True):
            if asset.asset_id in occupied:
                outcome.outcome = "skipped"
                outcome.notes.append("Already threaded")
            elif asset.shared_thread_with is not None:
                to_share.append((asset, outcome))
            else:
                to_root.append((asset, outcome))

        creative_ids = self.person_ids((job.creative_stakeholder,) if job.creative_stakeholder else (), None)
        additional_ids = self.person_ids(job.additional_stakeholders, None)
        creative_id = creative_ids[0] if creative_ids else ""
        creative_display = self.display(job.creative_stakeholder)
        additional_displays = tuple(p.name for p in job.additional_stakeholders)

        if self.engine is None:
            raise _JobFailed("no database for mint")
        with session_scope(self.engine) as session:
            repos = Repositories.from_session(session)
            norm = normalize_group_title(job.group_title)
            group_row = session.execute(select(Group).where(Group.channel_id == self.destination, Group.normalized_title == norm)).scalar_one_or_none()
            group_id = group_row.id if group_row is not None else "preview-group"
            summary = repos.history.latest_group_summary(group_row.id) if group_row is not None else None
            summary_snapshot: dict[str, Any] = dict(((summary.canvas_metadata or {}).get("edit") or {}) if summary else {})

            if group_row is None and not to_root:
                self.group_outcome = "not_needed"
            elif group_row is None:
                self.group_outcome = "created"
                if self.persist:
                    group_id = repos.groups.create(workspace_id=self.workspace_id, channel_id=self.destination, display_title=job.group_title, normalized_title=norm, now=self.now).id
                summary_snapshot = {
                    "kind": "group_summary",
                    "group_title": job.group_title,
                    "group_animator_id": creative_id,
                    "group_additional_ids": list(additional_ids),
                    "group_links": [],
                    "group_animator_display": creative_display,
                    "group_additional_displays": list(additional_displays),
                    "included_asset_count": len(to_root),
                    "processing_status": "Complete",
                    "message_identity": group_id,
                    "shared_assets": [],
                }
                text, blocks = self.render(render_group_summary(self._summary_context(summary_snapshot)))
                ts = str(self.slack.post_message(self.destination, text=text, blocks=blocks)["ts"])
                self.group_permalink = self.slack.get_permalink(self.destination, ts)
                if self.persist:
                    summary = repos.history.record(
                        NewMessageInput(
                            workspace_id=self.workspace_id, channel_id=self.destination, group_id=group_id, batch_id=None,
                            kind=MessageKind.GROUP_SUMMARY, asset_entity_id=None, slack_ts=ts, permalink=self.group_permalink,
                            canvas_metadata={"edit": summary_snapshot}, now=self.now,
                        )
                    )
            else:
                self.group_outcome = "joined"
                self.group_permalink = summary.permalink if summary is not None else ""
                creative_display = str(summary_snapshot.get("group_animator_display") or creative_display)
                additional_displays = tuple(summary_snapshot.get("group_additional_displays") or additional_displays)

            roots: dict[int, tuple[str, str]] = {}
            for asset, outcome in to_root:
                try:
                    ic_ids = self.person_ids(asset.ic_poc, outcome)
                    extra_ids = self.person_ids(asset.additional_ics, outcome)
                    snapshot = {
                        "kind": "asset_root",
                        "entity_id": asset.asset_id,
                        "asset_name": asset.name,
                        "asset_url": asset.sg_url,
                        "group_title": job.group_title,
                        "created_ts": int(self.now.timestamp()),
                        "asset_animator_id": ic_ids[0] if ic_ids else "",
                        "asset_additional_ids": list(ic_ids[1:] + extra_ids),
                        "asset_links": [],
                        "group_animator_id": creative_id,
                        "group_additional_ids": list(additional_ids),
                        "group_links": [],
                        "group_animator_display": creative_display,
                        "group_additional_displays": list(additional_displays),
                        "message_identity": f"{group_id}:{asset.asset_id}",
                        "has_prior_thread": False,
                        "requestor_label": "IC POC",
                    }
                    text, blocks = self.render(render_asset_root(self._root_context(snapshot)))
                    ts = str(self.slack.post_message(self.destination, text=text, blocks=blocks)["ts"])
                    permalink = self.slack.get_permalink(self.destination, ts)
                except Exception as exc:  # noqa: BLE001 - per-asset failure, keep going
                    outcome.outcome, outcome.error = "failed", str(exc)
                    continue
                roots[asset.asset_id] = (ts, permalink)
                outcome.outcome, outcome.permalink = "created", permalink
                if self.persist:
                    repos.history.record(
                        NewMessageInput(
                            workspace_id=self.workspace_id, channel_id=self.destination, group_id=group_id, batch_id=None,
                            kind=MessageKind.ASSET_ROOT, asset_entity_id=asset.asset_id, slack_ts=ts, permalink=permalink,
                            canvas_metadata={"edit": snapshot}, now=self.now,
                        )
                    )
                    self._spoke(asset.asset_id, permalink, ts)

            shared_entries: list[dict[str, Any]] = []
            for asset, outcome in to_share:
                target_id = int(asset.shared_thread_with or 0)
                if target_id in roots:
                    target_ts, target_link = roots[target_id]
                    target_channel = self.destination
                else:
                    spoke = find_spoke(self.jobs_root, target_id, folder=self.folder)
                    if not spoke or not spoke.get("thread_ts"):
                        outcome.outcome, outcome.error = "failed", "Shared thread target not found"
                        continue
                    target_ts, target_link, target_channel = spoke["thread_ts"], spoke.get("permalink", ""), spoke.get("channel_id", self.destination)
                try:
                    self.slack.post_message(
                        target_channel, text=f"Also tracked here: {asset.name} (ShotGrid ID: {asset.asset_id})", thread_ts=target_ts
                    )
                except Exception as exc:  # noqa: BLE001
                    outcome.outcome, outcome.error = "failed", str(exc)
                    continue
                outcome.outcome, outcome.permalink = "shared", target_link
                shared_entries.append(
                    {"entity_id": asset.asset_id, "name": asset.name, "asset_url": asset.sg_url, "permalink": target_link, "created_at": self.now.isoformat()}
                )
                if self.persist:
                    self._spoke(asset.asset_id, target_link, target_ts, channel_id=target_channel)

            new_roots = len(roots)
            if self.group_outcome == "joined" and summary is not None and (new_roots or shared_entries):
                summary_snapshot["included_asset_count"] = int(summary_snapshot.get("included_asset_count") or 0) + new_roots
                summary_snapshot["shared_assets"] = list(summary_snapshot.get("shared_assets") or []) + shared_entries
                text, blocks = self.render(render_group_summary(self._summary_context(summary_snapshot)))
                self.slack.update_message(summary.channel_id, summary.slack_ts, text=text, blocks=blocks)
                if self.persist:
                    metadata = dict(summary.canvas_metadata or {})
                    metadata["edit"] = summary_snapshot
                    repos.history.touch_editor(summary.id, editor_id="mint_group", now=self.now, canvas_metadata=metadata)
            elif self.group_outcome == "created" and summary is not None and shared_entries and self.persist:
                summary_snapshot["shared_assets"] = shared_entries
                metadata = dict(summary.canvas_metadata or {})
                metadata["edit"] = summary_snapshot
                repos.history.touch_editor(summary.id, editor_id="mint_group", now=self.now, canvas_metadata=metadata)

            if self.mode == "live" and (new_roots or shared_entries):
                try:
                    self._index(repos, group_id, summary_snapshot, creative_display, additional_displays)
                except Exception as exc:  # noqa: BLE001 - index is best-effort per spec
                    self.issues.append(f"Index not updated: {exc}")

        if self.mode == "live":
            for outcome in self.outcomes:
                if outcome.outcome in {"created", "shared"}:
                    stamp_sent(self.jobs_root, outcome.asset_id, job.job_id)

    def _spoke(self, asset_id: int, permalink: str, ts: str, *, channel_id: str | None = None) -> None:
        if not self.job.season_id:
            return
        upsert_season_spoke(
            self.jobs_root, season_id=self.job.season_id, asset_id=asset_id, permalink=permalink,
            channel_id=channel_id or self.destination, thread_ts=ts, source="mint", updated_at=self.now.isoformat(), folder=self.folder,
        )

    def _summary_context(self, snapshot: dict[str, Any]) -> GroupSummaryContext:
        return GroupSummaryContext(
            group_title=str(snapshot["group_title"]),
            animator_id=str(snapshot.get("group_animator_id") or "") or None,
            additional_ids=tuple(str(i) for i in snapshot.get("group_additional_ids") or ()),
            links=(),
            included_asset_count=int(snapshot.get("included_asset_count") or 0),
            processing_status=str(snapshot.get("processing_status") or "Complete"),
            summary_identity=str(snapshot.get("message_identity") or ""),
            canvas_url=None,
        )

    def _root_context(self, snapshot: dict[str, Any]) -> AssetRootContext:
        return AssetRootContext(
            asset_entity_id=int(snapshot["entity_id"]),
            asset_name=str(snapshot["asset_name"]),
            asset_url=str(snapshot["asset_url"]),
            group_title=str(snapshot["group_title"]),
            created_ts=int(snapshot["created_ts"]),
            asset_animator_id=str(snapshot["asset_animator_id"]),
            asset_additional_ids=tuple(snapshot["asset_additional_ids"]),
            group_animator_display=str(snapshot["group_animator_display"]),
            group_additional_displays=tuple(snapshot["group_additional_displays"]),
            group_links=(),
            asset_links=(),
            message_identity=str(snapshot["message_identity"]),
            is_latest=True,
            requestor_label=str(snapshot["requestor_label"]),
        )

    def _index(self, repos: Repositories, group_id: str, snapshot: dict[str, Any], creative_display: str, additional_displays: tuple[str, ...]) -> None:
        assets: list[IndexedAsset] = []
        for root in repos.history.list_latest_asset_roots_for_group(group_id):
            edit = (root.canvas_metadata or {}).get("edit") or {}
            assets.append(
                IndexedAsset(
                    entity_id=int(root.asset_entity_id or 0),
                    name=str(edit.get("asset_name") or f"Asset {root.asset_entity_id}"),
                    asset_url=str(edit.get("asset_url") or ""),
                    permalink=root.permalink,
                    created_at=root.created_at,
                )
            )
        for entry in snapshot.get("shared_assets") or []:
            assets.append(
                IndexedAsset(
                    entity_id=int(entry["entity_id"]),
                    name=str(entry["name"]),
                    asset_url=str(entry["asset_url"]),
                    permalink=str(entry["permalink"]),
                    created_at=datetime.fromisoformat(str(entry["created_at"])),
                )
            )
        canvas = CanvasService(self.slack)
        canvas_id = canvas.ensure_canvas(self.destination, create=True)
        canvas.index_batch(
            GroupIndexRequest(
                channel_id=self.destination,
                canvas_id=canvas_id,
                group_title=self.job.group_title,
                animator_display=creative_display,
                additional_displays=additional_displays,
                links=(),
                assets=tuple(assets),
            )
        )


def process_mint_group_job(
    job_path: Path,
    job: MintGroupJob,
    *,
    slack: SlackGateway,
    engine: Engine | None,
    jobs_root: Path,
    team_id: str,
    workspace_id: str,
    resolver: PeopleResolver | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one mint_group job, write result (and preview), and move it to done/."""
    run = _Run(job, slack=slack, engine=engine, jobs_root=jobs_root, team_id=team_id, workspace_id=workspace_id, resolver=resolver, now=now or datetime.now(timezone.utc))
    error = ""
    try:
        run.run()
    except _JobFailed as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 - surface any crash as a failed job
        _LOG.exception("mint_group job %s failed", job.job_id)
        error = f"mint failed: {exc}"

    any_root = any(o.outcome in {"created", "shared"} for o in run.outcomes)
    if error and not any_root:
        status = "failed"
    elif error or run.issues or any(o.outcome == "failed" or o.not_tagged or [n for n in o.notes if n != "Already threaded"] for o in run.outcomes):
        status = "done_with_issues"
    else:
        status = "done"
    result = {
        "job_id": job.job_id,
        "status": status,
        "error": error,
        "mode": job.mode,
        "destination": run.destination,
        "group": {"title": job.group_title, "outcome": run.group_outcome, "permalink": run.group_permalink},
        "issues": run.issues,
        "assets": [o.as_dict() for o in run.outcomes],
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    done = jobs_root / "slack_jobs" / "done"
    if isinstance(run.slack, PreviewSlack):
        _write_json(done / f"{job.job_id}.preview.json", {"job_id": job.job_id, "destination": run.destination, "group_outcome": run.group_outcome, "posts": run.slack.posts, "updates": run.slack.updates})
    _write_json(done / f"{job.job_id}.result.json", result)
    if status == "failed":
        write_failed(jobs_root, job.job_id, "", error)
    move_to_done(jobs_root, job_path)
    return result


def make_mint_group_handler(*, slack: SlackGateway, engine: Engine, jobs_root: Path, team_id: str) -> Callable[[Path, MintGroupJob], None]:
    """Return the drain callback that processes one mint_group job."""
    workspace_id = "W1"
    try:
        workspace_id = str(slack.auth_test().get("team_id") or workspace_id)
    except Exception:  # noqa: BLE001
        _LOG.warning("auth.test failed; using workspace id %s", workspace_id)

    def _handle(job_path: Path, job: MintGroupJob) -> None:
        process_mint_group_job(job_path, job, slack=slack, engine=engine, jobs_root=jobs_root, team_id=team_id, workspace_id=workspace_id)

    return _handle
```

Notes for the implementer:
- In dry run the group lookup still reads the DB, so `group_outcome` is accurate, but `group_id` stays `preview-group` for new groups and no rows are written. `session_scope` commits on exit; dry run adds nothing to the session, so the commit is a no-op.
- If `session_scope` is not a context manager that commits (check `db.py`), mirror exactly how `mint_from_job.process_job` uses it.
- If `history.record` for `ASSET_ROOT` requires a batch or raises on `batch_id=None`, mirror `mint_from_job.py:385-417`, which already records with `batch_id=None`.

- [ ] **Step 4: Run tests**

Run: `uv run --with pytest-timeout pytest tests/test_mint_group_jobs.py -q --tb=short --timeout=60`
Expected: PASS. Fix code, not tests, unless a test contradicts the spec.

- [ ] **Step 5: Commit**

```bash
git add src/red_team_prop_threader/mint_group_jobs.py tests/test_mint_group_jobs.py
git commit -m "feat: process mint_group jobs (join/create, roots, shared replies, index, modes)"
```

---

### Task 5: Wire the worker

**Files:**
- Modify: `src/red_team_prop_threader/worker.py`
- Test: `tests/test_worker.py` (append; create if missing)

**Interfaces:**
- Consumes: `make_mint_group_handler` (Task 4), `Settings.slack_people_team_id` (Task 2), `drain_thread_message_inbox(..., mint_handler=)` (Task 1).

- [ ] **Step 1: Write the failing test**

```python
def test_run_forever_passes_mint_handler(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from red_team_prop_threader import worker

    cfg = MagicMock()
    cfg.reviewprep_external_links_root = "R:/links"
    cfg.slack_people_team_id = "T0297NTAU"
    monkeypatch.setattr(worker, "build_engine", lambda url: MagicMock())
    monkeypatch.setattr(worker.SlackGateway, "from_settings", classmethod(lambda cls, s: MagicMock()))
    monkeypatch.setattr(worker, "session_scope", MagicMock())
    monkeypatch.setattr(worker, "BatchExecutor", MagicMock(return_value=MagicMock(run_once=MagicMock(return_value=None))))
    handler = object()
    monkeypatch.setattr(worker, "make_mint_group_handler", lambda **kw: handler)
    seen = {}
    monkeypatch.setattr(worker, "drain_thread_message_inbox", lambda root, slack, *, mint_handler=None: seen.update(handler=mint_handler))
    worker.run_forever(settings=cfg, once=True)
    assert seen["handler"] is handler
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --with pytest-timeout pytest tests/test_worker.py -q --tb=short --timeout=60 -k mint_handler`
Expected: FAIL (`AttributeError: make_mint_group_handler`).

- [ ] **Step 3: Implement**

Add import: `from red_team_prop_threader.mint_group_jobs import make_mint_group_handler`.

In `run_forever`, after `clock = UtcClock()`:

```python
    jobs_root = Path(cfg.reviewprep_external_links_root)
    mint_handler = make_mint_group_handler(slack=slack, engine=engine, jobs_root=jobs_root, team_id=cfg.slack_people_team_id)
```

Replace the drain call:

```python
            drain_thread_message_inbox(jobs_root, slack, mint_handler=mint_handler)
```

Update the `run_forever` docstring first line to `"""Poll for PENDING batches and drain inbox jobs (thread_message and mint_group)."""` and replace "Inbox drain replies in existing spokes and never mints." with "mint_group jobs create Slack groups and threads; thread_message jobs only reply."

- [ ] **Step 4: Run the whole affected suite**

Run: `uv run --with pytest-timeout pytest tests/test_worker.py tests/test_thread_message_jobs.py tests/test_mint_group_jobs.py tests/test_mint_group_parse.py tests/test_people.py tests/test_messages.py tests/test_spokes.py tests/test_edits.py -q --tb=short --timeout=60`
Expected: PASS.

- [ ] **Step 5: Full suite, lint, types**

Run:

```powershell
uv run --with pytest-timeout pytest -q --tb=short --timeout=120
uv run ruff check .
uv run ruff format --check .
uv run ty check .
```

Expected: all pass (Threader tests have no Qt; a full run is safe here).

- [ ] **Step 6: Commit**

```bash
git add src/red_team_prop_threader/worker.py tests/test_worker.py
git commit -m "feat: worker drains mint_group jobs"
```

---

### Task 6: Version bump, PR, deploy, manual gate

- [ ] **Step 1: Bump to 1.2.0** with `.agents/skills/bumpversion/SKILL.md`, type **minor**. Changelog: mint_group jobs from Flightdeck (group join/create, IC POC roots, shared-thread replies, canvas index, live/test/dry-run modes), people matching by name with email when `users:read.email` is granted, `SLACK_PEOPLE_TEAM_ID`.

- [ ] **Step 2: Open the PR** from `feature/mint-group-jobs` (use `gh pr create`). Do not merge without the user.

- [ ] **Step 3: Deploy to EAV1089717 after merge** (user-run): pull `main`, `uv sync`, restart the worker, confirm the log line `prop-threader worker starting`. Laptop Threader stays off.

- [ ] **Step 4: Manual gate (all through EAV, in this order)**
  1. Flightdeck mode **Dry run** on `S32 KC_MU5` -> `done/<job>.preview.json` shows 1 top post (or join), roots with IC POC, shared replies for `_03.._05`. No Slack posts.
  2. Flightdeck mode **Test channel** (`C0B4GJSA1G8`) on the same tab -> posts in `#red-slackbot-dev` only, names as plain text with `would tag`, `slack_threads_test/S32.json` written, `slack_threads/` untouched. Send again -> group `joined`, already-threaded rows `skipped`.
  3. Flightdeck mode **Live** on one tab chosen by the user -> real channel; check top post, roots, index section, `slack_threads/<season>.json`, and Flightdeck picker shows `Already threaded`.
