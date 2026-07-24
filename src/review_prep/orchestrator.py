"""Prep orchestrator: attachment download/extract and P4 CL sync per card."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
import logging
from pathlib import Path
import zipfile
from datetime import date
from dataclasses import field, dataclass

from review_prep.paths import asset_staging_dir, assert_local_or_unc
from review_prep.models import DEFAULT_CL_POLICIES, ClPolicy, RouteState, DeliveryRouteKind
from review_prep.cl_parser import parse_cls_from_comment
from review_prep.file_classifier import archive_kind, filter_launchable, is_recognized_dcc
from review_prep.shotgun_adapter import latest_delivery_comment
from review_prep.archive_extractor import UnsafeArchiveError, extract_archive


if TYPE_CHECKING:
    from review_prep.state import StateRepo
    from review_prep.models import ParsedCl
    from review_prep.settings import AppSettings
    from review_prep.p4_adapter import P4Adapter, P4SyncResult
    from review_prep.shotgun_adapter import Card, Attachment, ShotGridAdapter


_logger = logging.getLogger(__name__)

_DEFAULT_MAX_FILES = 10_000
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024 * 1024


@dataclass
class PrepRunResult:
    """Outcome of one prep run across one or more cards.

    Attributes:
        prep_run_id (int): StateRepo prep_runs id.
        local_date (str): Local calendar date (YYYY-MM-DD).
        card_ids (list[int]): Cards processed in this run.
        launchable_files (list[Path]): Files eligible to open (attachment extracts + sync-and-open CLs).
        hard_failure (bool): True only when the run could not start (e.g. bad staging root).
        errors (list[str]): Per-route or per-card error messages (partial failures).
    """

    prep_run_id: int
    local_date: str
    card_ids: list[int] = field(default_factory=list)
    launchable_files: list[Path] = field(default_factory=list)
    hard_failure: bool = False
    errors: list[str] = field(default_factory=list)


class PrepOrchestrator:
    """Drive attachment and P4 delivery routes for worklist cards.

    Sibling routes on a card are independent: one failure does not abort the others.
    """

    def __init__(
        self,
        *,
        settings: AppSettings,
        state: StateRepo,
        shotgun: ShotGridAdapter,
        p4: P4Adapter,
        local_date: date | None = None,
        trigger: str = "manual",
        max_files: int = _DEFAULT_MAX_FILES,
        max_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        """Initialize the orchestrator with injected settings and adapters.

        Args:
            settings (AppSettings): User settings (staging, CL policies, patterns, 7z).
            state (StateRepo): SQLite manifest for prep runs and routes.
            shotgun (ShotGridAdapter): Worklist / attachments / comments adapter.
            p4 (P4Adapter): Everyday-client Perforce adapter.
            local_date (date | None): Calendar date for staging and leases; defaults to today.
            trigger (str): Prep run trigger label (scheduled, manual, test, ...).
            max_files (int): Archive extract file-count limit.
            max_bytes (int): Archive extract uncompressed byte limit.
        """
        self._settings = settings
        self._state = state
        self._shotgun = shotgun
        self._p4 = p4
        self._local_date = local_date if local_date is not None else date.today()
        self._trigger = trigger
        self._max_files = max_files
        self._max_bytes = max_bytes

    def run_worklist(self) -> PrepRunResult:
        """Prepare every card returned by the ShotGrid worklist query.

        Returns:
            (PrepRunResult) Aggregated route outcomes and launchable files.
        """
        cards = self._shotgun.find_worklist()
        return self._prepare_cards(cards)

    def prepare_cards(self, card_ids: list[int]) -> PrepRunResult:
        """Prepare the given card ids (matched against the current worklist).

        Args:
            card_ids (list[int]): ShotGrid entity ids to prepare.

        Returns:
            (PrepRunResult) Aggregated route outcomes and launchable files.
        """
        wanted = set(card_ids)
        cards = [card for card in self._shotgun.find_worklist() if card.id in wanted]
        # Preserve caller order for determinism.
        by_id = {card.id: card for card in cards}
        ordered = [by_id[cid] for cid in card_ids if cid in by_id]
        return self._prepare_cards(ordered)

    def _prepare_cards(self, cards: list[Card]) -> PrepRunResult:
        """Start a prep run and process each card's delivery routes."""
        date_str = self._local_date.isoformat()
        try:
            staging_root = assert_local_or_unc(Path(self._settings.staging_root))
        except ValueError as exc:
            _logger.error("Invalid staging root: %s", exc)
            run_id = self._state.start_prep_run(date_str, self._trigger)
            return PrepRunResult(prep_run_id=run_id, local_date=date_str, card_ids=[], hard_failure=True, errors=[str(exc)])

        run_id = self._state.start_prep_run(date_str, self._trigger)
        result = PrepRunResult(prep_run_id=run_id, local_date=date_str, card_ids=[c.id for c in cards])

        for card in cards:
            try:
                launchable = self._prepare_one_card(run_id, card, staging_root, result.errors)
                result.launchable_files.extend(launchable)
            except Exception as exc:
                msg = f"card {card.id}: {exc}"
                _logger.exception("Card prep failed: %s", msg)
                result.errors.append(msg)

        return result

    def _prepare_one_card(self, prep_run_id: int, card: Card, staging_root: Path, errors: list[str]) -> list[Path]:
        """Process attachment and CL routes for one card; return launchable paths."""
        staging = asset_staging_dir(staging_root, self._local_date, card.code, card.id)
        staging.mkdir(parents=True, exist_ok=True)
        launchable: list[Path] = []

        for attachment in self._shotgun.list_attachments(card.id):
            try:
                launchable.extend(self._process_attachment(prep_run_id, card, attachment, staging))
            except Exception as exc:
                msg = f"card {card.id} attachment {attachment.id}: {exc}"
                _logger.exception("%s", msg)
                errors.append(msg)
                self._upsert(
                    prep_run_id,
                    card.id,
                    DeliveryRouteKind.ATTACHMENT_ARCHIVE if archive_kind(Path(attachment.filename)) else DeliveryRouteKind.ATTACHMENT_LOOSE,
                    str(attachment.id),
                    RouteState.FAILED,
                    str(exc),
                )

        comments = self._shotgun.list_comments(card.id)
        delivery = latest_delivery_comment(comments)
        if delivery is not None:
            for parsed in parse_cls_from_comment(delivery.text):
                try:
                    launchable.extend(self._process_cl(prep_run_id, card, parsed))
                except Exception as exc:
                    msg = f"card {card.id} CL {parsed.number}: {exc}"
                    _logger.exception("%s", msg)
                    errors.append(msg)
                    self._upsert(prep_run_id, card.id, DeliveryRouteKind.P4_CL, str(parsed.number), RouteState.FAILED, str(exc))

        return launchable

    def _process_attachment(self, prep_run_id: int, card: Card, attachment: Attachment, staging: Path) -> list[Path]:
        """Download and extract (or stage) one attachment; return launchable paths."""
        filename = attachment.filename or f"attachment_{attachment.id}"
        kind = archive_kind(Path(filename))
        route_kind = DeliveryRouteKind.ATTACHMENT_ARCHIVE if kind else DeliveryRouteKind.ATTACHMENT_LOOSE
        route_key = str(attachment.id)

        if kind is None and not is_recognized_dcc(Path(filename)):
            self._upsert(prep_run_id, card.id, route_kind, route_key, RouteState.SKIPPED, f"ignored attachment: {filename}")
            return []

        self._upsert(prep_run_id, card.id, route_kind, route_key, RouteState.DOWNLOADING, f"downloading {filename}")
        dest = staging / filename
        try:
            self._shotgun.download_attachment(attachment.id, dest)
        except Exception as exc:
            self._upsert(prep_run_id, card.id, route_kind, route_key, RouteState.FAILED, f"download failed: {exc}")
            raise

        if kind is not None:
            return self._extract_archive_route(prep_run_id, card.id, route_key, dest, staging)

        # Loose recognized DCC file.
        launchable = self._select_launchable([dest])
        detail = _detail_json("ready", launchable=launchable)
        self._upsert(prep_run_id, card.id, route_kind, route_key, RouteState.READY_TO_LAUNCH, detail)
        return launchable

    def _extract_archive_route(self, prep_run_id: int, card_id: int, route_key: str, archive: Path, staging: Path) -> list[Path]:
        """Extract a downloaded archive into staging and classify launchables."""
        self._upsert(prep_run_id, card_id, DeliveryRouteKind.ATTACHMENT_ARCHIVE, route_key, RouteState.EXTRACTING, f"extracting {archive.name}")
        extract_dest = staging / f"extracted_{route_key}"
        try:
            extracted = extract_archive(archive, extract_dest, Path(self._settings.seven_zip_exe), max_files=self._max_files, max_bytes=self._max_bytes)
        except (UnsafeArchiveError, OSError, zipfile.BadZipFile) as exc:
            self._upsert(prep_run_id, card_id, DeliveryRouteKind.ATTACHMENT_ARCHIVE, route_key, RouteState.FAILED, f"extract failed: {exc}")
            raise

        launchable = self._select_launchable(extracted)
        detail = _detail_json("ready", launchable=launchable, extracted=[str(p) for p in extracted])
        self._upsert(prep_run_id, card_id, DeliveryRouteKind.ATTACHMENT_ARCHIVE, route_key, RouteState.READY_TO_LAUNCH, detail)
        return launchable

    def _process_cl(self, prep_run_id: int, card: Card, parsed: ParsedCl) -> list[Path]:
        """Apply CL policy, sync when required, and return launchable paths."""
        route_key = str(parsed.number)
        policy = self._resolve_policy(parsed)

        if policy is ClPolicy.IGNORE:
            self._upsert(prep_run_id, card.id, DeliveryRouteKind.P4_CL, route_key, RouteState.SKIPPED, f"ignored {parsed.label} CL {parsed.number}")
            return []

        self._upsert(prep_run_id, card.id, DeliveryRouteKind.P4_CL, route_key, RouteState.SYNCING, f"syncing {parsed.label} CL {parsed.number}")
        results = self._p4.sync_cl(parsed.number)
        synced_paths = [Path(r.local) for r in results if not r.skipped]
        skipped = [r for r in results if r.skipped]
        state, launchable = self._finalize_cl_route(policy, synced_paths, results)

        detail = _detail_json(
            state.value,
            launchable=launchable if policy is ClPolicy.SYNC_AND_OPEN else [],
            synced=[str(p) for p in synced_paths],
            skipped=[{"depot": r.depot, "reason": r.skip_reason} for r in skipped],
            label=parsed.label,
            policy=policy.value,
        )
        self._upsert(prep_run_id, card.id, DeliveryRouteKind.P4_CL, route_key, state, detail)
        return launchable if policy is ClPolicy.SYNC_AND_OPEN else []

    def _finalize_cl_route(self, policy: ClPolicy, synced_paths: list[Path], results: list[P4SyncResult]) -> tuple[RouteState, list[Path]]:
        """Choose route state and launchable files after a CL sync."""
        launchable = self._select_launchable(synced_paths) if policy is ClPolicy.SYNC_AND_OPEN else []
        if not results:
            return RouteState.SYNCED_ONLY if policy is ClPolicy.SYNC_ONLY else RouteState.READY_TO_LAUNCH, launchable
        all_skipped = all(r.skipped for r in results)
        any_skipped = any(r.skipped for r in results)
        if all_skipped:
            return RouteState.PARTIAL, []
        if any_skipped:
            if policy is ClPolicy.SYNC_AND_OPEN:
                return RouteState.SYNCED_ONLY, launchable
            return RouteState.SYNCED_ONLY, []
        if policy is ClPolicy.SYNC_AND_OPEN:
            return RouteState.READY_TO_LAUNCH, launchable
        return RouteState.SYNCED_ONLY, []

    def _resolve_policy(self, parsed: ParsedCl) -> ClPolicy:
        """Resolve CL label → policy from settings, falling back to defaults / Unknown."""
        configured = dict(self._settings.cl_policies or {})
        key = parsed.label if parsed.label in configured else parsed.policy_key
        raw = configured.get(key) or configured.get("Unknown")
        if raw is None:
            return DEFAULT_CL_POLICIES.get(parsed.label, ClPolicy.SYNC_ONLY)
        try:
            return ClPolicy(raw)
        except ValueError:
            return ClPolicy.SYNC_ONLY

    def _select_launchable(self, paths: list[Path]) -> list[Path]:
        """Keep recognized DCC files that pass include/exclude patterns."""
        dcc = [p for p in paths if is_recognized_dcc(p)]
        return filter_launchable(dcc, self._settings.include_patterns, self._settings.exclude_patterns)

    def _upsert(self, prep_run_id: int, card_sg_id: int, route_kind: DeliveryRouteKind, route_key: str, state: RouteState, detail: str) -> None:
        """Persist a route state transition."""
        self._state.upsert_route(
            prep_run_id=prep_run_id, card_sg_id=card_sg_id, route_kind=route_kind.value, route_key=route_key, state=state.value, detail=detail
        )


def _detail_json(status: str, **extra: object) -> str:
    """Serialize route detail as JSON, converting Path lists to strings."""
    payload: dict[str, object] = {"status": status}
    for key, value in extra.items():
        if isinstance(value, list) and value and isinstance(value[0], Path):
            payload[key] = [str(p) for p in value]  # type: ignore[misc]
        else:
            payload[key] = value
    return json.dumps(payload)
