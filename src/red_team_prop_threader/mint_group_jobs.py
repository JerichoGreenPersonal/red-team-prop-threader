"""process Flightdeck mint_group jobs: one group, many thread roots."""

from __future__ import annotations

import re
import json
from typing import TYPE_CHECKING, Any
import logging
from datetime import datetime, timezone
from dataclasses import field, dataclass

from sqlalchemy import select

from red_team_prop_threader.db import session_scope
from red_team_prop_threader.canvas import IndexedAsset, CanvasService, GroupIndexRequest
from red_team_prop_threader.people import PeopleResolver
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
_ALREADY_THREADED = "Already threaded"


class _JobFailedError(Exception):
    """job-level failure; message is shown to Flightdeck verbatim."""


class PreviewSlack:
    """dry-run gateway: records writes, forwards read-only calls."""

    def __init__(self, real: Any) -> None:
        """Wrap the real gateway for read-only calls.

        Args:
            real: slack gateway used for conversations.info, members, and users.
        """
        self._real = real
        self.posts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.deleted: list[dict[str, str]] = []

    def get_conversation_info(self, channel_id: str) -> dict[str, Any]:
        """Forward conversations.info."""
        return self._real.get_conversation_info(channel_id)

    def get_conversation_members(self, channel_id: str) -> tuple[str, ...]:
        """Forward conversations.members."""
        return self._real.get_conversation_members(channel_id)

    def list_users(self, *, team_id: str) -> tuple[dict[str, Any], ...]:
        """Forward users.list."""
        return self._real.list_users(team_id=team_id)

    def lookup_user_by_email(self, email: str) -> str | None:
        """Forward users.lookupByEmail."""
        return self._real.lookup_user_by_email(email)

    def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Forward users.info."""
        return self._real.get_user_info(user_id)

    def post_message(self, channel_id: str, *, text: str, blocks: list[dict[str, Any]] | None = None, thread_ts: str | None = None) -> dict[str, Any]:
        """Record a post instead of sending it."""
        ts = f"preview.{len(self.posts) + 1}"
        self.posts.append({"channel": channel_id, "text": text, "blocks": blocks, "thread_ts": thread_ts, "ts": ts})
        return {"ts": ts}

    def update_message(self, channel_id: str, ts: str, *, text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Record an update instead of sending it."""
        self.updates.append({"channel": channel_id, "ts": ts, "text": text, "blocks": blocks})
        return {"ts": ts}

    def delete_message(self, channel_id: str, ts: str) -> None:
        """Drop a recorded preview post."""
        self.deleted.append({"channel": channel_id, "ts": ts})
        self.posts = [post for post in self.posts if not (post["channel"] == channel_id and post["ts"] == ts)]

    def get_permalink(self, channel_id: str, message_ts: str) -> str:
        """Return a placeholder permalink."""
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

    def __init__(
        self,
        job: MintGroupJob,
        *,
        slack: Any,
        engine: Engine | None,
        jobs_root: Path,
        team_id: str,
        workspace_id: str,
        resolver: PeopleResolver | None,
        now: datetime,
    ) -> None:
        self.job = job
        self.mode = job.mode
        self.persist = job.mode != "dry_run"
        self.real_slack = slack
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
        self._posted: list[dict[str, Any]] = []

    # people --------------------------------------------------------------
    def person_ids(self, people: tuple[MintGroupPerson, ...], outcome: _AssetOutcome | None) -> tuple[str, ...]:
        ids: list[str] = []
        for person in people:
            resolved = self.resolver.resolve(person)
            label = person.name or person.email
            if not resolved.user_id:
                if outcome is not None:
                    outcome.not_tagged.append(label)
                else:
                    self.issues.append(f"not tagged: {label}")
                continue
            self.labels[resolved.user_id] = f"{person.name} ({person.email}) - would tag {resolved.user_id} (via {resolved.method})"
            if resolved.user_id not in self.members:
                note = f"mentioned, not in channel: {label}"
                if outcome is not None:
                    outcome.notes.append(note)
                else:
                    self.issues.append(note)
            if resolved.user_id not in ids:
                ids.append(resolved.user_id)
        return tuple(ids)

    def render(self, rendered: dict[str, object]) -> tuple[str, list[dict[str, Any]]]:
        text, blocks = str(rendered["text"]), _blocks(rendered)
        if self.mode == "test":
            return _defang(text, self.labels), _defang(blocks, self.labels)
        return text, blocks

    # main ----------------------------------------------------------------
    def run(self) -> None:
        job = self.job
        if self.mode == "test" and not self.destination:
            raise _JobFailedError("Test channel missing")
        info = self.slack.get_conversation_info(self.destination)
        if not info.get("is_member"):
            raise _JobFailedError("Bot not in channel")
        try:
            self.members = set(self.slack.get_conversation_members(self.destination))
        except Exception:
            self.members = set()

        occupied = occupied_asset_ids(self.jobs_root, folder=self.folder)
        to_root: list[tuple[MintGroupAsset, _AssetOutcome]] = []
        to_share: list[tuple[MintGroupAsset, _AssetOutcome]] = []
        for asset, outcome in zip(job.assets, self.outcomes, strict=True):
            if asset.asset_id in occupied:
                outcome.outcome = "skipped"
                outcome.notes.append(_ALREADY_THREADED)
            elif asset.shared_thread_with is not None:
                to_share.append((asset, outcome))
            else:
                to_root.append((asset, outcome))

        creative_ids = self.person_ids((job.creative_stakeholder,) if job.creative_stakeholder else (), None)
        additional_ids = self.person_ids(job.additional_stakeholders, None)
        creative_id = creative_ids[0] if creative_ids else ""
        creative_display = job.creative_stakeholder.name if job.creative_stakeholder else ""
        additional_displays = tuple(p.name for p in job.additional_stakeholders)

        if self.engine is None:
            raise _JobFailedError("no database for mint")
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
                    group_id = repos.groups.create(
                        workspace_id=self.workspace_id, channel_id=self.destination, display_title=job.group_title, normalized_title=norm, now=self.now
                    ).id
                    session.flush()
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
                ts = str(self._post(self.destination, text=text, blocks=blocks, group=True)["ts"])
                self.group_permalink = self.slack.get_permalink(self.destination, ts)
                if self.persist:
                    summary = repos.history.record(
                        NewMessageInput(
                            workspace_id=self.workspace_id,
                            channel_id=self.destination,
                            group_id=group_id,
                            batch_id=None,
                            kind=MessageKind.GROUP_SUMMARY,
                            asset_entity_id=None,
                            slack_ts=ts,
                            permalink=self.group_permalink,
                            canvas_metadata={"edit": summary_snapshot},
                            now=self.now,
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
                    ts = str(self._post(self.destination, text=text, blocks=blocks, asset_id=asset.asset_id)["ts"])
                    permalink = self.slack.get_permalink(self.destination, ts)
                except Exception as exc:
                    outcome.outcome, outcome.error = "failed", str(exc)
                    continue
                roots[asset.asset_id] = (ts, permalink)
                outcome.outcome, outcome.permalink = "created", permalink
                if self.persist:
                    repos.history.record(
                        NewMessageInput(
                            workspace_id=self.workspace_id,
                            channel_id=self.destination,
                            group_id=group_id,
                            batch_id=None,
                            kind=MessageKind.ASSET_ROOT,
                            asset_entity_id=asset.asset_id,
                            slack_ts=ts,
                            permalink=permalink,
                            canvas_metadata={"edit": snapshot},
                            now=self.now,
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
                    target_ts = spoke["thread_ts"]
                    target_link = spoke.get("permalink", "")
                    target_channel = spoke.get("channel_id") or self.destination
                try:
                    self._post(
                        target_channel,
                        text=f"Also tracked here: {asset.name} (ShotGrid ID: {asset.asset_id})",
                        thread_ts=target_ts,
                        asset_id=asset.asset_id,
                    )
                except Exception as exc:
                    outcome.outcome, outcome.error = "failed", str(exc)
                    continue
                outcome.outcome, outcome.permalink = "shared", target_link
                shared_entries.append({
                    "entity_id": asset.asset_id,
                    "name": asset.name,
                    "asset_url": asset.sg_url,
                    "permalink": target_link,
                    "created_at": self.now.isoformat(),
                })
                if self.persist:
                    self._spoke(asset.asset_id, target_link, target_ts, channel_id=target_channel)

            self._abort_if_partial()
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

            if self.mode == "live" and group_id != "preview-group" and (new_roots or shared_entries):
                try:
                    self._index(repos, group_id, summary_snapshot, creative_display, additional_displays)
                except Exception as exc:
                    self.issues.append(f"Index not updated: {exc}")

        if self.mode == "live":
            for outcome in self.outcomes:
                if outcome.outcome in {"created", "shared"}:
                    stamp_sent(self.jobs_root, outcome.asset_id, job.job_id)

    def _post(
        self,
        channel_id: str,
        *,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
        asset_id: int | None = None,
        group: bool = False,
    ) -> dict[str, Any]:
        """Post one message and remember it so a failed job can delete it."""
        response = self.slack.post_message(channel_id, text=text, blocks=blocks, thread_ts=thread_ts)
        self._posted.append({"channel": channel_id, "ts": str(response["ts"]), "asset_id": asset_id, "group": group})
        return response

    def discard_posts(self) -> None:
        """Delete every Slack message this attempt posted."""
        posted_assets = {item["asset_id"] for item in self._posted if item["asset_id"] is not None}
        removed_group = any(item["group"] for item in self._posted)
        for item in reversed(self._posted):
            try:
                self.slack.delete_message(item["channel"], item["ts"])
            except Exception:
                _LOG.exception("could not delete partial mint post %s %s", item["channel"], item["ts"])
        for outcome in self.outcomes:
            if outcome.asset_id in posted_assets:
                outcome.outcome = ""
                outcome.permalink = ""
                outcome.error = ""
        if removed_group:
            self.group_outcome = ""
            self.group_permalink = ""
        self._posted.clear()

    def _abort_if_partial(self) -> None:
        """A job that posted anything and then failed a thread leaves nothing in Slack."""
        if self._posted and any(outcome.outcome == "failed" for outcome in self.outcomes):
            self.discard_posts()
            raise _JobFailedError("job did not finish; removed the messages it had posted")

    def _spoke(self, asset_id: int, permalink: str, ts: str, *, channel_id: str | None = None) -> None:
        if not self.job.season_id:
            return
        upsert_season_spoke(
            self.jobs_root,
            season_id=self.job.season_id,
            asset_id=asset_id,
            permalink=permalink,
            channel_id=channel_id or self.destination,
            thread_ts=ts,
            source="mint",
            updated_at=self.now.isoformat(),
            folder=self.folder,
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
        assets.extend(
            IndexedAsset(
                entity_id=int(entry["entity_id"]),
                name=str(entry["name"]),
                asset_url=str(entry["asset_url"]),
                permalink=str(entry["permalink"]),
                created_at=datetime.fromisoformat(str(entry["created_at"])),
            )
            for entry in snapshot.get("shared_assets") or []
        )
        canvas = CanvasService(self.real_slack)
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


def _status(run: _Run, error: str) -> str:
    any_root = any(o.outcome in {"created", "shared"} for o in run.outcomes)
    if error and not any_root:
        return "failed"
    asset_issue = any(o.outcome == "failed" or o.not_tagged or any(n != _ALREADY_THREADED for n in o.notes) for o in run.outcomes)
    if error or run.issues or asset_issue:
        return "done_with_issues"
    return "done"


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
    """Run one mint_group job, write result (and preview), and move it to done/.

    Args:
        job_path: inbox JSON path for the job.
        job: parsed mint_group job.
        slack: slack gateway (wrapped in PreviewSlack for dry runs).
        engine: database engine for groups and message history.
        jobs_root: ReviewPrep external links root (parent of slack_jobs/).
        team_id: workspace id for users.list.
        workspace_id: workspace id recorded on groups and messages.
        resolver: optional people resolver (tests); built from ``slack`` when omitted.
        now: optional clock override.

    Returns:
        dict[str, Any]: the result written to ``done/{job_id}.result.json``.
    """
    run = _Run(
        job,
        slack=slack,
        engine=engine,
        jobs_root=jobs_root,
        team_id=team_id,
        workspace_id=workspace_id,
        resolver=resolver,
        now=now or datetime.now(timezone.utc),
    )
    error = ""
    try:
        run.run()
    except _JobFailedError as exc:
        error = str(exc)
        run.discard_posts()
    except Exception as exc:
        _LOG.exception("mint_group job %s failed", job.job_id)
        error = f"mint failed: {exc}"
        run.discard_posts()

    status = _status(run, error)
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
        preview = {
            "job_id": job.job_id,
            "destination": run.destination,
            "group_outcome": run.group_outcome,
            "posts": run.slack.posts,
            "updates": run.slack.updates,
        }
        _write_json(done / f"{job.job_id}.preview.json", preview)
    _write_json(done / f"{job.job_id}.result.json", result)
    if status == "failed":
        write_failed(jobs_root, job.job_id, "", error)
    move_to_done(jobs_root, job_path)
    return result


def make_mint_group_handler(*, slack: SlackGateway, engine: Engine, jobs_root: Path, team_id: str) -> Callable[[Path, MintGroupJob], None]:
    """Return the drain callback that processes one mint_group job.

    Args:
        slack: slack gateway.
        engine: database engine.
        jobs_root: ReviewPrep external links root.
        team_id: workspace id for users.list.

    Returns:
        Callable[[Path, MintGroupJob], None]: handler for ``drain_thread_message_inbox``.
    """
    workspace_id = "W1"
    try:
        workspace_id = str(slack.auth_test().get("team_id") or workspace_id)
    except Exception:
        _LOG.warning("auth.test failed; using workspace id %s", workspace_id)

    def _handle(job_path: Path, job: MintGroupJob) -> None:
        process_mint_group_job(job_path, job, slack=slack, engine=engine, jobs_root=jobs_root, team_id=team_id, workspace_id=workspace_id)

    return _handle
