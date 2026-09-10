"""process jobs from the inbox."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
import logging
from datetime import datetime, timezone

from red_team_prop_threader.spokes import occupied_asset_ids, upsert_season_spoke
from red_team_prop_threader._errors import NotFoundError, ExternalServiceError, RetryableExternalServiceError
from red_team_prop_threader.cl_jobs import sent_has, parse_job, list_inbox, stamp_sent, move_to_done, write_failed, resolve_channel
from red_team_prop_threader.validation import normalize_group_title


if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.engine import Engine

    from red_team_prop_threader.cl_jobs import SlackClJob
    from red_team_prop_threader.slack_gateway import SlackGateway


__all__ = ("process_cl_jobs", "process_job", "reply_already_posted")

_LOG = logging.getLogger(__name__)


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
    except (ExternalServiceError, RetryableExternalServiceError):
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


def process_job(job_path: Path, job: SlackClJob, *, slack: SlackGateway, season_root: Path, engine: Engine | None = None) -> None:
    """Process a single SlackClJob."""
    from typing import Any

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
                    select(Group).where(
                        Group.channel_id == channel_id,
                        Group.normalized_title == group_title_norm
                    )
                ).scalar_one_or_none()
                
                now = datetime.now(timezone.utc)
                if group_row is None:
                    # Create group
                    group = repos.groups.create(
                        workspace_id="W1", # Dummy default, typically comes from context but we don't have it here
                        channel_id=channel_id,
                        display_title=job.group_title or "",
                        normalized_title=group_title_norm,
                        now=now
                    )
                    group_id = group.id
                    
                    # Validate channel members for POCs
                    try:
                        members = set(slack.get_conversation_members(channel_id))
                    except ExternalServiceError:
                        members = set()
                        
                    selected_pocs = set()
                    if job.creative_stakeholder:
                        selected_pocs.add(job.creative_stakeholder)
                    if job.additional_stakeholders:
                        selected_pocs.update(job.additional_stakeholders)
                        
                    valid_pocs = list(selected_pocs & members)
                    
                    # Mint group summary
                    from red_team_prop_threader.messages import AssetRootContext, GroupSummaryContext, render_asset_root, render_group_summary
                    
                    # Need an animator to pass to context
                    animator_id = job.creative_stakeholder if job.creative_stakeholder in valid_pocs else ""
                    additional_ids = [p for p in valid_pocs if p != animator_id]
                    
                    context = GroupSummaryContext(
                        group_title=job.group_title or "",
                        animator_id=animator_id,
                        additional_ids=tuple(additional_ids),
                        links=(),
                        included_asset_count=1,
                        processing_status="Complete",
                        summary_identity=group_id,
                        canvas_url=None,
                    )
                    
                    def _display_name(uid: str) -> str:
                        if not uid:
                            return ""
                        try:
                            info = slack.get_user_info(uid)
                            profile = info.get("profile", {})
                            for k in ("display_name", "real_name"):
                                val = profile.get(k)
                                if isinstance(val, str) and val.strip():
                                    return val.strip()
                        except ExternalServiceError:
                            pass
                        return uid
                        
                    group_animator_display = _display_name(animator_id)
                    group_additional_displays = tuple(_display_name(uid) for uid in additional_ids)
                    
                    rendered = render_group_summary(context)
                    
                    def _blocks(rnd: dict[str, object]) -> list[dict[str, Any]]:
                        b = rnd.get("blocks")
                        if not isinstance(b, list):
                            return []
                        return [{str(k): v for k, v in block.items()} for block in b if isinstance(block, dict)]
                        
                    resp = slack.post_message(channel_id, text=str(rendered["text"]), blocks=_blocks(rendered))
                    summary_ts = str(resp["ts"])
                    summary_link = slack.get_permalink(channel_id, summary_ts)
                    
                    from red_team_prop_threader.repositories import MessageKind, NewMessageInput
                    repos.history.record(NewMessageInput(
                        workspace_id="W1",
                        channel_id=channel_id,
                        group_id=group_id,
                        batch_id=None,
                        kind=MessageKind.GROUP_SUMMARY,
                        asset_entity_id=None,
                        slack_ts=summary_ts,
                        permalink=summary_link,
                        canvas_metadata=None,
                        now=now
                    ))
                else:
                    group_id = group_row.id
                    valid_pocs = []
                    group_animator_display = ""
                    group_additional_displays = ()
                    animator_id = ""
                    additional_ids = []
                    
                def _blocks(rnd: dict[str, object]) -> list[dict[str, Any]]:
                    b = rnd.get("blocks")
                    if not isinstance(b, list):
                        return []
                    return [{str(k): v for k, v in block.items()} for block in b if isinstance(block, dict)]
                    
                # Post the asset root
                from red_team_prop_threader.messages import AssetRootContext, render_asset_root
                asset_ctx = AssetRootContext(
                    asset_entity_id=asset_int,
                    asset_name=job.job_id,
                    asset_url=f"https://respawn.shotgunstudio.com/detail/Asset/{asset_int}",
                    group_title=job.group_title or "",
                    created_ts=int(now.timestamp()),
                    asset_animator_id="",
                    asset_additional_ids=(),
                    group_animator_display=group_animator_display,
                    group_additional_displays=group_additional_displays,
                    group_links=(),
                    asset_links=(),
                    message_identity=f"{group_id}:{asset_int}",
                    is_latest=True,
                    has_prior_thread=False
                )
                rendered_asset = render_asset_root(asset_ctx)
                resp_asset = slack.post_message(channel_id, text=str(rendered_asset["text"]), blocks=_blocks(rendered_asset))
                thread_ts = str(resp_asset["ts"])
                permalink = slack.get_permalink(channel_id, thread_ts)
                
                from red_team_prop_threader.repositories import MessageKind, NewMessageInput
                repos.history.record(NewMessageInput(
                    workspace_id="W1",
                    channel_id=channel_id,
                    group_id=group_id,
                    batch_id=None,
                    kind=MessageKind.ASSET_ROOT,
                    asset_entity_id=asset_int,
                    slack_ts=thread_ts,
                    permalink=permalink,
                    canvas_metadata=None,
                    now=now
                ))
                
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
                        updated_at=now.isoformat()
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

        # 6. stamp_sent
        if job.cls:
            stamp_sent(season_root, job.asset_id, job.cls)
        move_to_done(season_root, job_path)

    except (ExternalServiceError, RetryableExternalServiceError) as e:
        # 4 & 7. Write failed, do not stamp sent, leave inbox file
        write_failed(season_root, job.job_id, job.asset_id, str(e))


def process_cl_jobs(share_root: Path | str, slack: SlackGateway, *, engine: Engine | None = None) -> None:
    """Process all valid jobs in the inbox."""
    from pathlib import Path
    root = Path(share_root)
    for job_path in list_inbox(root):
        job = parse_job(job_path)
        if job is None:
            continue
        process_job(job_path, job, slack=slack, season_root=root, engine=engine)
