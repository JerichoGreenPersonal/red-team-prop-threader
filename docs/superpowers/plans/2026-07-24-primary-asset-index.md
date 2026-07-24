# Primary Asset Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dual-write satellite `INDEX OF PROP REQUESTS` canvases and a `PRIMARY ASSET INDEX` canvas in `C04H4QZEYUE`, with collapsible H2/H3 markdown and `:Slack:` / `:shotgrid:` link markers (keeping `:threadparrot:` on asset roots).

**Architecture:** After each required satellite `INDEX_ASSET` (and on group edits), run a best-effort `INDEX_PRIMARY_ASSET` durable op that indexes the same group onto the primary channel canvas. Shared `render_group_markdown` produces the new heading/emoji layout for both canvases; primary headings include channel display for uniqueness. Primary failures never raise out of the executor — they succeed the op with an error payload so the batch is not marked failed.

**Tech Stack:** Python 3.11, Slack Bolt/SDK canvas APIs, SQLAlchemy operations table, pytest, uv.

## Global Constraints

- Naming: `PRIMARY_ASSET_INDEX` / `INDEX_PRIMARY_ASSET` / `PRIMARY_ASSET_INDEX_CHANNEL_ID` — never `MASTER_*`.
- Default primary channel id: `C04H4QZEYUE`.
- Primary canvas title: `PRIMARY ASSET INDEX`.
- Satellite canvas title unchanged: `INDEX OF PROP REQUESTS`.
- New primary groups: `insert_at_start`; updates: in-place `replace` (no bump).
- Primary write is best-effort; satellite success must not be blocked.
- Skip primary op when `batch.channel_id == primary_channel_id`.
- Keep `:threadparrot:` on asset root messages.
- No AI attribution in commits.

## File map

| File | Responsibility |
| --- | --- |
| `src/red_team_prop_threader/config.py` | Load `PRIMARY_ASSET_INDEX_CHANNEL_ID` |
| `.env.example` | Document the new env var |
| `src/red_team_prop_threader/domain.py` | Add `OperationKind.INDEX_PRIMARY_ASSET` |
| `src/red_team_prop_threader/canvas.py` | New markdown shape; primary title constant; ensure primary canvas; primary H2 + source line |
| `src/red_team_prop_threader/messages.py` | `:shotgrid:` on asset SG link; keep `:threadparrot:` |
| `src/red_team_prop_threader/jobs.py` | Plan + execute `INDEX_PRIMARY_ASSET` best-effort |
| `src/red_team_prop_threader/edits.py` | After satellite `index_batch`, best-effort primary index |
| `src/red_team_prop_threader/worker.py` (if needed) | Pass settings/primary channel id into executor wiring |
| `tests/test_config.py` | Config default/override |
| `tests/test_canvas.py` | Markdown + primary ensure |
| `tests/test_messages.py` | ShotGrid emoji + parrot |
| `tests/test_jobs.py` | Planner/executor primary behavior |
| `tests/test_edits.py` | Edit path dual index |
| `docs/user-guide.md` | Short note on primary index |
| `docs/admin/remote-host.md` | Env var for EAV |

---

### Task 1: Config — `PRIMARY_ASSET_INDEX_CHANNEL_ID`

**Files:**
- Modify: `src/red_team_prop_threader/config.py`
- Modify: `.env.example`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.primary_asset_index_channel_id: str` defaulting to `"C04H4QZEYUE"`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` (alongside existing Settings tests; reuse the usual env monkeypatch fixture pattern already in that file):

```python
def test_primary_asset_index_channel_id_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """PRIMARY_ASSET_INDEX_CHANNEL_ID defaults to C04H4QZEYUE."""
    # ... set all required env vars as other tests do ...
    monkeypatch.delenv("PRIMARY_ASSET_INDEX_CHANNEL_ID", raising=False)
    settings = Settings.from_env()
    assert settings.primary_asset_index_channel_id == "C04H4QZEYUE"


def test_primary_asset_index_channel_id_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """PRIMARY_ASSET_INDEX_CHANNEL_ID can be overridden."""
    # ... set required env vars ...
    monkeypatch.setenv("PRIMARY_ASSET_INDEX_CHANNEL_ID", "C999OVERRIDE")
    settings = Settings.from_env()
    assert settings.primary_asset_index_channel_id == "C999OVERRIDE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_primary_asset_index_channel_id_default -v`  
Expected: FAIL (attribute missing or AttributeError)

- [ ] **Step 3: Implement**

In `Settings` dataclass add:

```python
primary_asset_index_channel_id: str
```

In `from_env()`:

```python
primary_asset_index_channel_id = (
    os.environ.get("PRIMARY_ASSET_INDEX_CHANNEL_ID", "C04H4QZEYUE").strip() or "C04H4QZEYUE"
)
```

Pass it into the `Settings(...)` constructor. Add to `.env.example`:

```text
PRIMARY_ASSET_INDEX_CHANNEL_ID=C04H4QZEYUE
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_config.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/red_team_prop_threader/config.py .env.example tests/test_config.py
git commit -m "feat: add PRIMARY_ASSET_INDEX_CHANNEL_ID setting"
```

---

### Task 2: Canvas markdown — H2/H3 + emojis (both canvases)

**Files:**
- Modify: `src/red_team_prop_threader/canvas.py`
- Modify: `tests/test_canvas.py`

**Interfaces:**
- Consumes: existing `GroupIndexRequest`
- Produces: extended `GroupIndexRequest` with optional primary fields; updated `render_group_markdown`

Extend `GroupIndexRequest`:

```python
@dataclass(frozen=True, slots=True)
class GroupIndexRequest:
    channel_id: str
    canvas_id: str
    group_title: str
    animator_display: str
    additional_displays: tuple[str, ...]
    links: tuple[SupportingLink, ...]
    assets: tuple[IndexedAsset, ...]
    for_primary: bool = False
    source_channel_display: str = ""
```

Add constant:

```python
PRIMARY_CANVAS_TITLE = "PRIMARY ASSET INDEX"
```

Export it in `__all__`.

- [ ] **Step 1: Write failing tests**

```python
def test_render_group_markdown_uses_h3_asset_name_and_emoji_links() -> None:
    from red_team_prop_threader.canvas import render_group_markdown

    md = render_group_markdown(sample_new_group())
    assert "### Prop A" in md or "### " in md  # plain H3 name, not link heading
    assert ":shotgrid:" in md
    assert ":Slack:" in md
    assert "### [Prop A]" not in md  # old linked H3 gone


def test_render_group_markdown_primary_includes_channel_in_h2() -> None:
    from red_team_prop_threader.canvas import render_group_markdown

    req = sample_new_group(for_primary=True, source_channel_display="red-props")
    # extend sample_new_group helper to accept these kwargs
    md = render_group_markdown(req)
    assert md.startswith("## ")
    assert "(red-props)" in md.splitlines()[0]
    assert "**Source channel:**" in md
```

Update any existing `test_canvas.py` assertions that expect `### [name](url)` or bare `[stamp](permalink)` lines.

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/test_canvas.py -q`  
Expected: FAIL on new/updated assertions

- [ ] **Step 3: Implement `render_group_markdown`**

Replace asset rendering with:

```python
def render_group_markdown(request: GroupIndexRequest) -> str:
    title = normalize_group_title(request.group_title)
    if request.for_primary:
        display = (request.source_channel_display or request.channel_id).strip()
        heading = f"## {title} ({display})"
    else:
        heading = f"## {title}"
    people_parts = [part for part in (request.animator_display, *request.additional_displays) if part and part.strip()]
    people = ", ".join(people_parts) if people_parts else "unassigned"
    link_lines = "\n".join(f"- [{_escape_md(link.label)}]({link.url})" for link in request.links)
    asset_parts: list[str] = []
    for asset in request.assets:
        lines = [
            f"### {_escape_md(asset.name)}",
            f"- :shotgrid: [ShotGrid]({asset.asset_url})",
            f"- {_asset_thread_line(asset.permalink, asset.created_at, is_latest=asset.is_latest)}",
        ]
        if asset.prior_permalink and asset.prior_created_at is not None:
            lines.append(f"- {_asset_thread_line(asset.prior_permalink, asset.prior_created_at, is_latest=False)}")
        asset_parts.append("\n".join(lines))
    sections = [heading]
    if request.for_primary:
        src = (request.source_channel_display or request.channel_id).strip()
        sections.append(f"**Source channel:** #{src}")
    sections.append(f"**Creative Stakeholder:** {people}")
    if link_lines:
        sections.append("**Group Links:**\n" + link_lines)
    if asset_parts:
        sections.append("\n\n".join(asset_parts))
    return "\n\n".join(sections) + "\n\n\n"


def _asset_thread_line(permalink: str, created_at: datetime, *, is_latest: bool) -> str:
    stamp = format_canvas_timestamp(created_at)
    latest = " — Latest" if is_latest else ""
    return f":Slack: [{stamp}]({permalink}){latest}"
```

Keep `index_batch` lookup using `normalize_group_title` for satellites. For primary, lookup must use the full H2 text including `({display})` — update `index_batch` to compute `lookup_title` the same way as `heading` (strip `## `).

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/test_canvas.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/red_team_prop_threader/canvas.py tests/test_canvas.py
git commit -m "feat: canvas index H2/H3 collapse layout with Slack and ShotGrid emojis"
```

---

### Task 3: Ensure primary canvas helper

**Files:**
- Modify: `src/red_team_prop_threader/canvas.py`
- Modify: `tests/test_canvas.py`

**Interfaces:**
- Produces: `CanvasService.ensure_primary_canvas(channel_id: str) -> str` → canvas file id

- [ ] **Step 1: Write failing test**

```python
def test_ensure_primary_canvas_creates_when_missing() -> None:
    fake = FakeSlackGateway(channel_canvas_id=None)
    svc = CanvasService(fake)
    canvas_id = svc.ensure_primary_canvas("C04H4QZEYUE")
    assert canvas_id == "Fnew"
    assert fake.canvas_title == "PRIMARY ASSET INDEX"


def test_ensure_primary_canvas_renames_wrong_title() -> None:
    fake = FakeSlackGateway(channel_canvas_id="Fcanvas", canvas_title="Old Title")
    svc = CanvasService(fake)
    canvas_id = svc.ensure_primary_canvas("C04H4QZEYUE")
    assert canvas_id == "Fcanvas"
    assert fake.canvas_title == "PRIMARY ASSET INDEX"
    assert any(e.operation == "rename" for e in fake.canvas_edits)
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/test_canvas.py::test_ensure_primary_canvas_creates_when_missing -v`

- [ ] **Step 3: Implement**

```python
def ensure_primary_canvas(self, channel_id: str) -> str:
    """Ensure the primary channel has a canvas titled PRIMARY ASSET INDEX.

    Creates or renames as needed. Raises ExternalServiceError / PermissionDeniedError
    on Slack failures (caller treats as best-effort).
    """
    return self.ensure_canvas(channel_id, create=True, rename=True, title=PRIMARY_CANVAS_TITLE)
```

If `ensure_canvas` currently hardcodes `CANVAS_TITLE`, add an optional `title: str = CANVAS_TITLE` parameter and thread it through create/rename/title checks. Do **not** change satellite preflight defaults.

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/test_canvas.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/red_team_prop_threader/canvas.py tests/test_canvas.py
git commit -m "feat: ensure PRIMARY ASSET INDEX canvas on primary channel"
```

---

### Task 4: Asset root `:shotgrid:` emoji (keep `:threadparrot:`)

**Files:**
- Modify: `src/red_team_prop_threader/messages.py`
- Modify: `tests/test_messages.py`

**Interfaces:**
- Produces: asset line containing both `:threadparrot:` bookends and `:shotgrid:` before the SG link

- [ ] **Step 1: Write failing test**

```python
def test_asset_root_includes_shotgrid_emoji_and_threadparrot() -> None:
    message = render_asset_root(sample_asset_context())
    rendered = "\n".join(
        block["text"]["text"]
        for block in message["blocks"]
        if block.get("type") == "section" and isinstance(block.get("text"), dict)
    )
    assert ":threadparrot:" in rendered
    assert ":shotgrid:" in rendered
    assert ":shotgrid: *Asset:*" in rendered or ":shotgrid:" in rendered
```

Prefer exact shape:

```text
:threadparrot: *Asset:* :shotgrid: <url|name> (ShotGrid ID: …) :threadparrot:
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement in `render_asset_root`**

Change asset link construction to:

```python
asset_link = f":shotgrid: <{context.asset_url}|{escaped_name}>"
asset_line = f":threadparrot: *Asset:* {asset_link} (ShotGrid ID: {context.asset_entity_id})"
```

Keep existing parrot bookends and `(latest thread)` behavior.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_messages.py -q`  
Expected: PASS (update any brittle string assertions)

- [ ] **Step 5: Commit**

```bash
git add src/red_team_prop_threader/messages.py tests/test_messages.py
git commit -m "feat: add :shotgrid: emoji to asset root ShotGrid links"
```

---

### Task 5: Domain + planner — `INDEX_PRIMARY_ASSET`

**Files:**
- Modify: `src/red_team_prop_threader/domain.py`
- Modify: `src/red_team_prop_threader/jobs.py` (`_KIND_ORDER`, `BatchPlanner.plan`)
- Modify: `tests/test_jobs.py` (or add planner-focused tests)

**Interfaces:**
- Produces: `OperationKind.INDEX_PRIMARY_ASSET = "index_primary_asset"`
- Planner emits primary op after each `INDEX_ASSET` when `payload["channel_id"]` or `batch.channel_id` ≠ settings primary id

Planner currently has no Settings — pass primary channel via batch payload at plan time **or** read from batch payload key `primary_asset_index_channel_id` written when the batch is created.

**Chosen approach:** When the draft is confirmed / batch payload is built (workflow), include:

```python
"primary_asset_index_channel_id": settings.primary_asset_index_channel_id,
"source_channel_display": "<channel name or id>",  # best available
```

If display name is not already available, store `channel_id` and let the executor resolve display later (fallback to channel id).

- [ ] **Step 1: Write failing planner test**

```python
def test_plan_includes_index_primary_asset_after_each_index(repositories, ...):
    # create batch with channel_id != C04H4QZEYUE and payload including
    # primary_asset_index_channel_id=C04H4QZEYUE and one asset
    ops = BatchPlanner(repositories).plan(batch_id, now=now)
    kinds = [op.kind for op in ops]
    assert OperationKind.INDEX_PRIMARY_ASSET in kinds
    # for each INDEX_ASSET there is a following INDEX_PRIMARY_ASSET with same entity_id
    idx = kinds.index(OperationKind.INDEX_ASSET)
    assert kinds[idx + 1] is OperationKind.INDEX_PRIMARY_ASSET


def test_plan_skips_index_primary_when_channel_is_primary(repositories, ...):
    # batch.channel_id == C04H4QZEYUE
    ops = BatchPlanner(repositories).plan(batch_id, now=now)
    assert all(op.kind is not OperationKind.INDEX_PRIMARY_ASSET for op in ops)
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

In `domain.py`:

```python
INDEX_PRIMARY_ASSET = "index_primary_asset"
```

In `jobs.py` `_KIND_ORDER`:

```python
OperationKind.INDEX_ASSET: 2,
OperationKind.INDEX_PRIMARY_ASSET: 3,
OperationKind.RETIRE_PRIOR_LATEST: 4,
OperationKind.FINALIZE_SUMMARY: 5,
```

In `BatchPlanner.plan`, after each `INDEX_ASSET` block:

```python
primary_channel = str(payload.get("primary_asset_index_channel_id") or "").strip()
if primary_channel and batch.channel_id != primary_channel:
    tick = tick + timedelta(microseconds=1)
    planned.append(
        self._repos.operations.add_planned(
            batch_id=batch_id,
            kind=OperationKind.INDEX_PRIMARY_ASSET,
            asset_entity_id=entity_id,
            idempotency_key=f"{batch_id}:index_primary_asset:{entity_id}",
            payload={"entity_id": entity_id},
            now=tick,
        )
    )
```

Wire `primary_asset_index_channel_id` into batch payload in `workflow.py` (wherever payload dict is assembled for `batches.create` / confirm). Search for `"canvas_id"` in workflow and add the key next to it. Also add `source_channel_display` if a channel name is already on hand; else omit (executor falls back to channel id).

Update `stop_assets` tuple in `_run_batch` to include `OperationKind.INDEX_PRIMARY_ASSET`.

- [ ] **Step 4: Run job/planner tests**

Run: `uv run pytest tests/test_jobs.py -q`  
Expected: PASS (fix any order-sensitive assertions)

- [ ] **Step 5: Commit**

```bash
git add src/red_team_prop_threader/domain.py src/red_team_prop_threader/jobs.py src/red_team_prop_threader/workflow.py tests/test_jobs.py
git commit -m "feat: plan INDEX_PRIMARY_ASSET after satellite index"
```

---

### Task 6: Executor — best-effort `_index_primary_asset`

**Files:**
- Modify: `src/red_team_prop_threader/jobs.py`
- Modify: `tests/test_jobs.py`

**Interfaces:**
- Consumes: `CanvasService.ensure_primary_canvas`, `GroupIndexRequest(for_primary=True, ...)`
- Produces: `_index_primary_asset(...) -> dict` that **never raises** for Slack/permission errors; returns `{"indexed": True}` or `{"indexed": False, "error": "..."}`

Critical: do **not** let exceptions escape `_dispatch` for this kind in a way that marks FAILED — either catch inside `_index_primary_asset` or special-case in `_execute_operation`. Prefer catch inside `_index_primary_asset` so the op is `SUCCEEDED` with `indexed: false`.

- [ ] **Step 1: Write failing tests**

```python
def test_index_primary_asset_writes_primary_canvas(...):
    # execute batch with fake canvas; assert edit_canvas called for primary canvas id
    ...


def test_index_primary_failure_does_not_fail_batch(...):
    # make ensure_primary_canvas / index_batch raise PermissionDeniedError
    # batch terminal status must be SUCCEEDED
    # INDEX_PRIMARY_ASSET op status SUCCEEDED with result indexed False
    ...
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

In `_dispatch`:

```python
if operation.kind is OperationKind.INDEX_PRIMARY_ASSET:
    return self._index_primary_asset(batch, operation, payload)
```

```python
def _index_primary_asset(self, batch: BatchRecord, operation: OperationRecord, payload: dict[str, Any]) -> dict[str, Any]:
    primary_channel = str(payload.get("primary_asset_index_channel_id") or "").strip()
    if not primary_channel or batch.channel_id == primary_channel:
        return {"indexed": False, "skipped": True}
    try:
        self._require_succeeded_asset_op(batch.id, OperationKind.POST_ASSET, operation.asset_entity_id)
        canvas_id = self._canvas.ensure_primary_canvas(primary_channel)
        indexed_assets = self._indexed_assets_for_group(batch, payload)
        group_animator_id = self._group_animator_id(payload)
        display = str(payload.get("source_channel_display") or batch.channel_id)
        request = GroupIndexRequest(
            channel_id=batch.channel_id,
            canvas_id=canvas_id,
            group_title=str(payload["group_title"]),
            animator_display=self._display_name(group_animator_id or ""),
            additional_displays=tuple(
                self._display_name(str(item)) for item in payload.get("group_additional_ids") or () if str(item).strip()
            ),
            links=_links_from_payload(payload.get("group_links")),
            assets=indexed_assets,
            for_primary=True,
            source_channel_display=display,
        )
        self._canvas.index_batch(request)
        return {"indexed": True, "entity_id": operation.asset_entity_id, "canvas_id": canvas_id}
    except Exception as exc:  # best-effort: never fail the batch
        # log with module logger; do not include tokens
        return {"indexed": False, "error": str(exc)[:500]}
```

Use the existing project logger pattern from `_logging.py` / jobs module if present; otherwise `logging.getLogger(__name__).warning(...)`.

Narrow the bare `except` if the codebase prefers catching `(PermissionDeniedError, ExternalServiceError, ValueError, LookupError)` **plus** a final log — still return dict, never raise.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_jobs.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/red_team_prop_threader/jobs.py tests/test_jobs.py
git commit -m "feat: best-effort INDEX_PRIMARY_ASSET executor path"
```

---

### Task 7: Edits path — dual index

**Files:**
- Modify: `src/red_team_prop_threader/edits.py`
- Modify: `tests/test_edits.py`
- Possibly: constructor injection of `primary_asset_index_channel_id: str`

**Interfaces:**
- After satellite `index_batch`, call ensure + primary `index_batch` in try/except (best-effort)

- [ ] **Step 1: Write failing test**

Extend edit tests so that after a successful group edit, the fake slack records a second canvas edit targeting the primary canvas (or `ensure_primary_canvas` + `index_batch` with `for_primary=True`). Failure on primary must not raise to the edit caller.

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement**

In `EditService` (or equivalent), after the satellite `index_batch` block (~line 241):

```python
primary_channel = self._primary_asset_index_channel_id
if primary_channel and summary.channel_id != primary_channel:
    try:
        primary_canvas_id = self._canvas.ensure_primary_canvas(primary_channel)
        self._canvas.index_batch(
            GroupIndexRequest(
                channel_id=summary.channel_id,
                canvas_id=primary_canvas_id,
                group_title=str(summary_snapshot["group_title"]),
                animator_display=str(summary_snapshot["group_animator_display"]),
                additional_displays=tuple(str(item) for item in summary_snapshot.get("group_additional_displays") or ()),
                links=tuple(
                    SupportingLink(str(item["label"]), str(item["url"]))
                    for item in summary_snapshot.get("group_links") or ()
                ),
                assets=self._indexed_assets(roots),
                for_primary=True,
                source_channel_display=str(summary_snapshot.get("source_channel_display") or summary.channel_id),
            )
        )
    except Exception:
        logging.getLogger(__name__).warning("primary asset index update failed", exc_info=True)
```

Thread `primary_asset_index_channel_id` from Settings where `EditService` is constructed (`slack_app.py` / workflow wiring).

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_edits.py -q`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/red_team_prop_threader/edits.py src/red_team_prop_threader/slack_app.py tests/test_edits.py
git commit -m "feat: update PRIMARY ASSET INDEX on group edits"
```

---

### Task 8: Docs + verification

**Files:**
- Modify: `docs/user-guide.md`
- Modify: `docs/admin/remote-host.md`
- Modify: `docs/superpowers/specs/2026-07-24-primary-asset-index-design.md` (status → approved)

- [ ] **Step 1: Document**

User guide: one short section — satellite channels keep local indexes; primary ledger lives in the configured primary channel; collapse H2/H3; bot must be in primary channel.

Remote host: list `PRIMARY_ASSET_INDEX_CHANNEL_ID` in the `.env` table.

- [ ] **Step 2: Full test suite**

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run ty check .
```

Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add docs/user-guide.md docs/admin/remote-host.md docs/superpowers/specs/2026-07-24-primary-asset-index-design.md
git commit -m "docs: document PRIMARY ASSET INDEX dual-write behavior"
```

- [ ] **Step 4: EAV smoke (manual)**

1. Confirm bot is in `C04H4QZEYUE`.
2. Pull/restart stack on EAV.
3. Run `/create-prop-threads` in a satellite channel.
4. Confirm local canvas + primary canvas both updated with new markdown shape.
5. Edit group details; confirm primary section updates in place.

---

## Spec coverage check

| Spec requirement | Task |
| --- | --- |
| Dual-write local + primary | 5, 6, 7 |
| Channel `C04H4QZEYUE` / env | 1 |
| `PRIMARY ASSET INDEX` title | 3 |
| H2/H3 + emojis both canvases | 2 |
| Source channel + disambiguated primary H2 | 2, 6 |
| insert_at_start / in-place replace | 2 (`index_batch` existing behavior + primary lookup title) |
| Best-effort primary | 6, 7 |
| Skip when same channel | 5 |
| Keep `:threadparrot:` + add `:shotgrid:` | 4 |
| Docs / rollout | 8 |
