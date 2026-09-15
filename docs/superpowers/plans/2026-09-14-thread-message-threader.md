# Thread Message Implementation Plan (Threader drain)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On EAV1089717, drain ReviewPrep `kind: thread_message` inbox jobs, reply in the existing Slack thread with body plus 0..n files, and fail leftover Post CL JSON without posting.

**Architecture:** Same `{REVIEWPREP_EXTERNAL_LINKS_ROOT}/slack_jobs/inbox` poll as today. No mint, no Request Form, no group create. If `spoke_channel_id` or `spoke_thread_ts` is missing, `write_failed` and skip. Old jobs without `kind: thread_message` fail with `Unsupported job; send Thread Message`.

**Tech Stack:** Python 3.11+, existing `red_team_prop_threader` worker, slack_sdk `files_upload_v2` (already on `feature/slack-cl-jobs`).

**Spec:** `docs/superpowers/specs/2026-09-11-thread-message-design.md` (Threader section)

**Sibling plan:** `docs/superpowers/plans/2026-09-14-thread-message.md` (ReviewPrep). Ship together.

## Global Constraints

- Sibling repo `red-team-prop-threader`, branch `feature/slack-cl-jobs` (or a new branch from it). Not ReviewPrep. Not Threader `main` without a PR.
- One live instance: EAV1089717. Laptop Threader off. Bounce worker after deploy.
- Do not mint. Do not read Google / column Z.
- ASCII hyphen-minus in failed-job error text.
- `sent.json` values are job id strings, not CL numbers.
- TDD in the Threader repo.

## File map (Threader repo)

- Modify: `src/red_team_prop_threader/cl_jobs.py` (`parse_job`, `stamp_sent`)
- Modify: `src/red_team_prop_threader/mint_from_job.py` or worker tick (stop calling mint for these jobs)
- Create or modify: process function for thread messages (keep mint module unused for this kind)
- Test: `tests/test_cl_jobs.py`, new `tests/test_thread_message_jobs.py`

ReviewPrep JSON (do not rename keys): `kind`, `job_id`, `asset_id`, `body`, `images`, `spoke_channel_id`, `spoke_thread_ts`.

---

### Task 1: Parse thread_message; fail old jobs

**Files:**
- Modify: `src/red_team_prop_threader/cl_jobs.py`
- Test: `tests/test_cl_jobs.py`

**Interfaces:**
- Produces: `parse_job(path: Path) -> ThreadMessageJob | None` where

```python
@dataclass(frozen=True)
class ThreadMessageJob:
    job_id: str
    asset_id: int
    body: str
    image_filenames: tuple[str, ...]
    spoke_channel_id: str
    spoke_thread_ts: str
```

If JSON `kind != "thread_message"`, return None and let Task 2 fail it (or `parse_job` raises `UnsupportedJob`). Pick one: `parse_job` returns `None` for unsupported; worker calls `write_failed(..., "Unsupported job; send Thread Message")` then moves JSON+images to `done/` or deletes after failed stamp so it does not retry forever.

`stamp_sent(root, asset_id: int, job_id: str)` appends `job_id` to `sent.json[str(asset_id)]`.

- [ ] **Step 1: Tests**

```python
def test_parse_thread_message_job(tmp_path: Path) -> None:
    p = tmp_path / "j.json"
    p.write_text(
        json.dumps({
            "kind": "thread_message",
            "job_id": "j",
            "asset_id": 38863,
            "body": "hi",
            "images": ["j_0.png"],
            "spoke_channel_id": "C1",
            "spoke_thread_ts": "1.2",
        }),
        encoding="utf-8",
    )
    job = parse_job(p)
    assert job is not None
    assert job.body == "hi"
    assert job.image_filenames == ("j_0.png",)


def test_parse_old_post_cl_is_unsupported(tmp_path: Path) -> None:
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"job_id": "old", "asset_id": 1, "cls": [{"label": "WIP", "number": 99}]}), encoding="utf-8")
    assert parse_job(p) is None
```

- [ ] **Step 2: Run** `uv run pytest tests/test_cl_jobs.py -q --tb=short` FAIL
- [ ] **Step 3: Implement parse + stamp_sent job ids**
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** `feat: parse thread_message jobs and ignore post-cl json`

---

### Task 2: Reply in spoke; upload files; no mint

**Files:**
- Create: `src/red_team_prop_threader/thread_message_jobs.py`
- Modify: `src/red_team_prop_threader/worker.py` (call this before or instead of mint-from-job for inbox files)
- Test: `tests/test_thread_message_jobs.py`

**Interfaces:**
- Consumes: `SlackGateway.post_message`, `SlackGateway.upload_file` (existing `files_upload_v2`)
- Produces: `process_thread_message_job(job: ThreadMessageJob, *, inbox: Path, slack: SlackGateway, jobs_root: Path) -> None`

Flow:
1. If not `job.spoke_channel_id.strip()` or not `job.spoke_thread_ts.strip()`: `write_failed(..., "Missing Slack thread")`; do not post.
2. If `parse_job` was None: `write_failed(..., "Unsupported job; send Thread Message")`.
3. `post_message(channel=spoke_channel_id, text=body or " ", thread_ts=spoke_thread_ts)` when body is non-empty. If body empty and images exist, skip text or post a single space — Slack requires a parent message; use `upload_file(..., thread_ts=..., initial_comment=None)` on the first file as the reply if body is empty.
4. For each filename in `image_filenames`, `inbox / filename` must be a file; `upload_file(channel_id=..., file_path=..., thread_ts=...)`.
5. `stamp_sent(jobs_root, job.asset_id, job.job_id)`.
6. Move JSON and image files to `jobs_root/done/`.
7. Never call `mint_from_job`.

- [ ] **Step 1: Tests** with MagicMock slack: body+two files posts once and uploads twice; missing spoke writes failed and zero posts; old JSON path writes `Unsupported job; send Thread Message`.

- [ ] **Step 2: FAIL** `uv run pytest tests/test_thread_message_jobs.py -q --tb=short`
- [ ] **Step 3: Implement**
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** `feat: post thread_message replies without minting`

---

### Task 3: Worker tick + EAV bounce notes

**Files:**
- Modify: `src/red_team_prop_threader/worker.py`
- Test: extend `tests/test_thread_message_jobs.py` or existing worker test to assert inbox `*.json` are passed to `process_thread_message_job` / unsupported fail

**Produces:** Each worker tick lists inbox JSON, processes thread_message jobs, fails others, does not mint.

- [ ] **Step 1: Test** worker helper with tmp inbox
- [ ] **Step 2: FAIL**
- [ ] **Step 3: Wire tick**
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit** `feat: drain thread_message inbox on worker tick`

Deploy (not a code task): checkout on EAV1089717, bounce web+worker, confirm laptop Threader is off.

---
