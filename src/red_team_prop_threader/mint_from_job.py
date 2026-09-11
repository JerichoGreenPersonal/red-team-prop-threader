"""process jobs from the inbox."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
import logging
from datetime import datetime, timezone
from dataclasses import dataclass

from red_team_prop_threader.spokes import occupied_asset_ids, upsert_season_spoke
from red_team_prop_threader._errors import NotFoundError, ExternalServiceError, RetryableExternalServiceError
from red_team_prop_threader.cl_jobs import sent_has, parse_job, list_inbox, stamp_sent, move_to_done, write_failed, resolve_channel
from red_team_prop_threader.validation import normalize_group_title, validate_channel_members


if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.engine import Engine

    from red_team_prop_threader.cl_jobs import SlackClJob
    from red_team_prop_threader.shotgrid import ShotGridGateway
    from red_team_prop_threader.slack_gateway import SlackGateway


__all__ = ("process_cl_jobs", "process_job", "reply_already_posted")

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ResolvedJobPeople:
    """slack ids mapped from a Post CL job after handle resolve and membership check."""

    creative_stakeholder_id: str
    additional_stakeholder_ids: tuple[str, ...]
    ic_poc_id: str
    additional_ic_ids: tuple[str, ...]


def _is_slack_user_id(value: str) -> bool:
    """Return True when *value* looks like a Slack user or guest id.

    Args:
        value: job handle or id string.

    Returns:
        bool: True for ``U…`` / ``W…`` ids.
    """
    return len(value) > 1 and value[0] in {"U", "W"} and value[1:].isalnum()


def _cached_user_info(slack: SlackGateway, member_id: str, info_cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Return cached ``users.info`` for *member_id*, fetching once on miss.

    Args:
        slack: slack gateway.
        member_id: channel member slack id.
        info_cache: mutable cache of user objects keyed by slack id.

    Returns:
        dict[str, Any]: user object, or empty dict when lookup fails.
    """
    if member_id not in info_cache:
        try:
            info_cache[member_id] = slack.get_user_info(member_id)
        except ExternalServiceError:
            info_cache[member_id] = {}
    return info_cache[member_id]


def _resolve_job_person(raw: str | None, *, members: set[str], slack: SlackGateway, info_cache: dict[str, dict[str, Any]]) -> str:
    """Resolve a job handle or slack id to a candidate user id.

    Membership is not applied here. ``@username`` / bare username is matched
    against channel members' ``name``. ``U…`` / ``W…`` values pass through.

    Args:
        raw: job field value from ReviewPrep (handle or slack id).
        members: slack user ids in the target channel.
        slack: slack gateway for ``users.info``.
        info_cache: mutable cache of user objects keyed by slack id.

    Returns:
        str: candidate slack id, or empty string when missing or unmatched.
    """
    handle = str(raw or "").strip()
    if not handle:
        return ""
    if _is_slack_user_id(handle):
        return handle
    name = handle.lstrip("@").lower()
    if not name:
        return ""
    for member_id in members:
        info = _cached_user_info(slack, member_id, info_cache)
        if str(info.get("name") or "").lower() == name:
            return member_id
    return ""


def _unique_member_ids(ids: list[str], *, missing: set[str], exclude: set[str]) -> tuple[str, ...]:
    """Keep first-seen ids that survived the member check.

    Args:
        ids: resolved ids in job order.
        missing: ids rejected by ``validate_channel_members``.
        exclude: ids already assigned to another role.

    Returns:
        tuple[str, ...]: unique member ids.
    """
    seen = set(exclude)
    out: list[str] = []
    for uid in ids:
        if not uid or uid in missing or uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return tuple(out)


def _map_job_people(job: SlackClJob, *, members: set[str], slack: SlackGateway, info_cache: dict[str, dict[str, Any]]) -> _ResolvedJobPeople:
    """Map job handles to internal slack ids, then drop non-members.

    Job JSON keeps ``creative_stakeholder`` / ``additional_stakeholders`` (and
    optional ``ic_poc`` / ``additional_ics``) as handles. This does not read
    ``*_id`` keys from the job.

    Args:
        job: parsed inbox job.
        members: slack user ids in the target channel.
        slack: slack gateway.
        info_cache: mutable cache of user objects keyed by slack id.

    Returns:
        _ResolvedJobPeople: member ids for snapshots and message context.
    """
    creative = _resolve_job_person(job.creative_stakeholder, members=members, slack=slack, info_cache=info_cache)
    additional = [_resolve_job_person(item, members=members, slack=slack, info_cache=info_cache) for item in job.additional_stakeholders or ()]
    ic_poc = _resolve_job_person(job.ic_poc, members=members, slack=slack, info_cache=info_cache)
    additional_ics = [_resolve_job_person(item, members=members, slack=slack, info_cache=info_cache) for item in job.additional_ics or ()]
    selected = {uid for uid in (creative, *additional, ic_poc, *additional_ics) if uid}
    missing = validate_channel_members(selected, members)
    creative_stakeholder_id = "" if (not creative or creative in missing) else creative
    ic_poc_id = "" if (not ic_poc or ic_poc in missing) else ic_poc
    return _ResolvedJobPeople(
        creative_stakeholder_id=creative_stakeholder_id,
        additional_stakeholder_ids=_unique_member_ids(additional, missing=missing, exclude={creative_stakeholder_id}),
        ic_poc_id=ic_poc_id,
        additional_ic_ids=_unique_member_ids(additional_ics, missing=missing, exclude={ic_poc_id}),
    )


def _display_name_from_cache(uid: str, slack: SlackGateway, info_cache: dict[str, dict[str, Any]]) -> str:
    """Return a slack display name for *uid*, or the id when unknown.

    Args:
        uid: slack user id.
        slack: slack gateway.
        info_cache: mutable cache of user objects keyed by slack id.

    Returns:
        str: display name, or *uid* when lookup fails.
    """
    if not uid:
        return ""
    info = _cached_user_info(slack, uid, info_cache)
    profile = info.get("profile") if isinstance(info.get("profile"), dict) else {}
    for key in ("display_name", "real_name"):
        value = profile.get(key) if isinstance(profile, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return uid


def reply_already_posted(gateway: SlackGateway, channel_id: str, thread_ts: str, body: str) -> bool:
    """Check if a reply with exactly the given body already exists."""
    if not body:
        return False
    try:
        resp = gateway._call("conversations_replies", channel=channel_id, ts=thread_ts)
        messages = resp.get("messages")
        if isinstance(messages, list):
            for msg in messages:
                if isinstance(msg, dict) and msg.get("text") == body:
                    return True
    except RetryableExternalServiceError:
        raise
    except ExternalServiceError:
        pass
    return False


def _find_spoke_in_season(season_root: Path, season_id: str, asset_id: str) -> dict[str, str] | None:
    path = season_root / "slack_threads" / f"{season_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        assets = data.get("assets", {})
        if isinstance(assets, dict):
            spoke = assets.get(str(int(asset_id)))
            if isinstance(spoke, dict):
                return spoke
    except (json.JSONDecodeError, OSError, ValueError):
        pass
    return None


def process_job(
    job_path: Path,
    job: SlackClJob,
    *,
    slack: SlackGateway,
    season_root: Path,
    engine: Engine | None = None,
    shotgrid: ShotGridGateway | None = None,
    workspace_id: str = "W1",
) -> None:
    """Process a single SlackClJob."""
    # 1. If all cls already sent -> move to done, return
    if job.cls and all(sent_has(season_root, job.asset_id, cl) for cl in job.cls):
        move_to_done(season_root, job_path)
        return

    channel_id = job.spoke_channel_id
    thread_ts = job.spoke_thread_ts

    try:
        asset_int = int(job.asset_id)
    except ValueError:
        write_failed(season_root, job.job_id, job.asset_id, "invalid asset_id")
        return

    # 2. Skip mint when job spoke set, or in season JSON
    needs_mint = True
    occupied = occupied_asset_ids(season_root)

    if channel_id and thread_ts:
        needs_mint = False
    elif asset_int in occupied and job.season_id:
        spoke = _find_spoke_in_season(season_root, job.season_id, job.asset_id)
        if spoke and spoke.get("channel_id") and spoke.get("thread_ts"):
            channel_id = spoke["channel_id"]
            thread_ts = spoke["thread_ts"]
            needs_mint = False

    if needs_mint:
        if not job.channel:
            write_failed(season_root, job.job_id, job.asset_id, "mint required but no channel on job")
            return

        try:
            channel_id = resolve_channel(slack, job.channel)
        except NotFoundError as e:
            write_failed(season_root, job.job_id, job.asset_id, str(e))
            return

        if engine is None:
            write_failed(season_root, job.job_id, job.asset_id, "no database for mint")
            return

        try:
            group_title_norm = normalize_group_title(job.group_title or "")
            from red_team_prop_threader.db import session_scope
            from red_team_prop_threader.repositories import Repositories

            with session_scope(engine) as session:
                repos = Repositories.from_session(session)
                # Find group by channel and normalized title
                from sqlalchemy import select

                from red_team_prop_threader.tables import Group

                group_row = session.execute(
                    select(Group).where(Group.channel_id == channel_id, Group.normalized_title == group_title_norm)
                ).scalar_one_or_none()

                now = datetime.now(timezone.utc)
                try:
                    members = set(slack.get_conversation_members(channel_id))
                except ExternalServiceError:
                    members = set()
                info_cache: dict[str, dict[str, Any]] = {}
                people = _map_job_people(job, members=members, slack=slack, info_cache=info_cache)
                creative_stakeholder_id = people.creative_stakeholder_id
                additional_stakeholder_ids = people.additional_stakeholder_ids
                ic_poc_id = people.ic_poc_id
                additional_ic_ids = people.additional_ic_ids
                creative_stakeholder_display = _display_name_from_cache(creative_stakeholder_id, slack, info_cache)
                additional_stakeholder_displays = tuple(_display_name_from_cache(uid, slack, info_cache) for uid in additional_stakeholder_ids)

                from red_team_prop_threader.messages import AssetRootContext, GroupSummaryContext, render_asset_root, render_group_summary
                from red_team_prop_threader.repositories import MessageKind, NewMessageInput

                def _blocks(rnd: dict[str, object]) -> list[dict[str, Any]]:
                    b = rnd.get("blocks")
                    if not isinstance(b, list):
                        return []
                    return [{str(k): v for k, v in block.items()} for block in b if isinstance(block, dict)]

                if group_row is None:
                    group = repos.groups.create(
                        workspace_id=workspace_id, channel_id=channel_id, display_title=job.group_title or "", normalized_title=group_title_norm, now=now
                    )
                    group_id = group.id

                    context = GroupSummaryContext(
                        group_title=job.group_title or "",
                        animator_id=creative_stakeholder_id or None,
                        additional_ids=additional_stakeholder_ids,
                        links=(),
                        included_asset_count=1,
                        processing_status="Complete",
                        summary_identity=group_id,
                        canvas_url=None,
                    )
                    rendered = render_group_summary(context)
                    resp = slack.post_message(channel_id, text=str(rendered["text"]), blocks=_blocks(rendered))
                    summary_ts = str(resp["ts"])
                    summary_link = slack.get_permalink(channel_id, summary_ts)
                    repos.history.record(
                        NewMessageInput(
                            workspace_id=workspace_id,
                            channel_id=channel_id,
                            group_id=group_id,
                            batch_id=None,
                            kind=MessageKind.GROUP_SUMMARY,
                            asset_entity_id=None,
                            slack_ts=summary_ts,
                            permalink=summary_link,
                            canvas_metadata={
                                "edit": {
                                    "kind": "group_summary",
                                    "group_title": job.group_title or "",
                                    "group_animator_id": creative_stakeholder_id,
                                    "group_additional_ids": list(additional_stakeholder_ids),
                                    "group_links": [],
                                    "group_animator_display": creative_stakeholder_display,
                                    "group_additional_displays": list(additional_stakeholder_displays),
                                    "included_asset_count": 1,
                                    "processing_status": "Complete",
                                    "message_identity": group_id,
                                }
                            },
                            now=now,
                        )
                    )
                else:
                    group_id = group_row.id

                asset_name = f"Asset {asset_int}"
                if shotgrid is not None:
                    try:
                        labels = shotgrid.find_asset_labels((asset_int,))
                        if asset_int in labels and labels[asset_int][2]:
                            asset_name = labels[asset_int][2]
                    except ExternalServiceError:
                        pass

                created_ts = int(now.timestamp())
                asset_ctx = AssetRootContext(
                    asset_entity_id=asset_int,
                    asset_name=asset_name,
                    asset_url=f"https://respawn.shotgunstudio.com/detail/Asset/{asset_int}",
                    group_title=job.group_title or "",
                    created_ts=created_ts,
                    asset_animator_id=ic_poc_id,
                    asset_additional_ids=additional_ic_ids,
                    group_animator_display=creative_stakeholder_display,
                    group_additional_displays=additional_stakeholder_displays,
                    group_links=(),
                    asset_links=(),
                    message_identity=f"{group_id}:{asset_int}",
                    is_latest=True,
                    has_prior_thread=False,
                )
                rendered_asset = render_asset_root(asset_ctx)
                resp_asset = slack.post_message(channel_id, text=str(rendered_asset["text"]), blocks=_blocks(rendered_asset))
                thread_ts = str(resp_asset["ts"])
                permalink = slack.get_permalink(channel_id, thread_ts)

                repos.history.record(
                    NewMessageInput(
                        workspace_id=workspace_id,
                        channel_id=channel_id,
                        group_id=group_id,
                        batch_id=None,
                        kind=MessageKind.ASSET_ROOT,
                        asset_entity_id=asset_int,
                        slack_ts=thread_ts,
                        permalink=permalink,
                        canvas_metadata={
                            "edit": {
                                "kind": "asset_root",
                                "entity_id": asset_int,
                                "asset_name": asset_name,
                                "asset_url": f"https://respawn.shotgunstudio.com/detail/Asset/{asset_int}",
                                "group_title": job.group_title or "",
                                "created_ts": created_ts,
                                "asset_animator_id": ic_poc_id,
                                "asset_additional_ids": list(additional_ic_ids),
                                "asset_links": [],
                                "group_animator_id": creative_stakeholder_id,
                                "group_additional_ids": list(additional_stakeholder_ids),
                                "group_links": [],
                                "group_animator_display": creative_stakeholder_display,
                                "group_additional_displays": list(additional_stakeholder_displays),
                                "message_identity": f"{group_id}:{asset_int}",
                                "has_prior_thread": False,
                            }
                        },
                        now=now,
                    )
                )

                # Upsert season file
                if job.season_id:
                    upsert_season_spoke(
                        season_root,
                        season_id=job.season_id,
                        asset_id=asset_int,
                        permalink=permalink,
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        source="mint",
                        updated_at=now.isoformat(),
                    )

        except Exception as e:
            write_failed(season_root, job.job_id, job.asset_id, f"mint failed: {e}")
            return

    if not channel_id or not thread_ts:
        write_failed(season_root, job.job_id, job.asset_id, "missing channel or thread")
        return

    try:
        body = job.body or ""

        # 3. reply_already_posted
        if body and not reply_already_posted(slack, channel_id, thread_ts, body):
            slack.post_message(channel_id, text=body, thread_ts=thread_ts)

        # 5. upload_file
        if job.image_filename:
            image_path = job_path.parent / job.image_filename
            if image_path.is_file():
                slack.upload_file(channel_id, file_path=image_path, thread_ts=thread_ts)
            else:
                write_failed(season_root, job.job_id, job.asset_id, f"image file missing: {job.image_filename}")
                return

        # 6. stamp_sent
        if job.cls:
            stamp_sent(season_root, job.asset_id, job.cls)
        move_to_done(season_root, job_path)

    except Exception as e:
        # 4 & 7. Write failed, do not stamp sent, leave inbox file
        write_failed(season_root, job.job_id, job.asset_id, str(e))


def process_cl_jobs(share_root: Path | str, slack: SlackGateway, *, engine: Engine | None = None, shotgrid: ShotGridGateway | None = None) -> None:
    """Process all valid jobs in the inbox."""
    from pathlib import Path

    root = Path(share_root)

    workspace_id = "W1"
    try:
        auth = slack.auth_test()
        if "team_id" in auth:
            workspace_id = auth["team_id"]
    except ExternalServiceError:
        pass

    for job_path in list_inbox(root):
        job = parse_job(job_path)
        if job is None:
            continue
        process_job(job_path, job, slack=slack, season_root=root, engine=engine, shotgrid=shotgrid, workspace_id=workspace_id)
