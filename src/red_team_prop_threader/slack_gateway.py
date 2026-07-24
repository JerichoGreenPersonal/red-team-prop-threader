"""typed wrapper over the Slack Web API methods required by prop-threader."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import logging

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from red_team_prop_threader._errors import ConflictError, NotFoundError, ExternalServiceError, PermissionDeniedError, RetryableExternalServiceError


if TYPE_CHECKING:
    from red_team_prop_threader.config import Settings


__all__ = ("SlackGateway",)

_LOG = logging.getLogger(__name__)

_PERMISSION_ERRORS = frozenset({
    "not_in_channel",
    "missing_scope",
    "not_allowed_token_type",
    "access_denied",
    "restricted_action",
    "canvas_disabled",
    "feature_not_enabled",
    "paid_teams_only",
    "not_allowed",
})
_NOT_FOUND_ERRORS = frozenset({"channel_not_found", "canvas_not_found", "file_not_found", "message_not_found", "user_not_found", "not_found"})
_CONFLICT_ERRORS = frozenset({"channel_canvas_already_exists", "conflict", "cant_update_message"})
_RETRYABLE_ERRORS = frozenset({"ratelimited", "rate_limited", "service_unavailable", "internal_error", "fatal_error", "request_timeout"})


class SlackGateway:
    """thin typed facade over Slack Web API calls used by the app."""

    def __init__(self, client: WebClient) -> None:
        """Initialize with an authenticated Slack WebClient.

        Args:
            client: slack_sdk WebClient configured with the bot token.
        """
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings) -> SlackGateway:
        """Build a gateway from application settings.

        Args:
            settings: validated application settings.

        Returns:
            SlackGateway: gateway bound to the configured bot token.
        """
        return cls(WebClient(token=settings.slack_bot_token))

    def auth_test(self) -> dict[str, Any]:
        """Verify the bot token via auth.test.

        Returns:
            dict[str, Any]: auth.test response body.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        return self._call("auth_test")

    def get_conversation_info(self, channel_id: str) -> dict[str, Any]:
        """Fetch conversations.info for a channel.

        Args:
            channel_id: slack channel id.

        Returns:
            dict[str, Any]: the channel object from the API response.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        response = self._call("conversations_info", channel=channel_id)
        channel = response.get("channel")
        if not isinstance(channel, dict):
            raise ExternalServiceError("conversations.info returned invalid channel")
        return channel

    def get_conversation_members(self, channel_id: str) -> tuple[str, ...]:
        """List all member user ids for a channel with cursor pagination.

        Args:
            channel_id: slack channel id.

        Returns:
            tuple[str, ...]: member user ids in API order.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        members: list[str] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"channel": channel_id, "limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            response = self._call("conversations_members", **kwargs)
            page = response.get("members") or []
            if not isinstance(page, list):
                raise ExternalServiceError("conversations.members returned invalid members")
            members.extend(str(item) for item in page)
            metadata = response.get("response_metadata") or {}
            next_cursor = metadata.get("next_cursor") if isinstance(metadata, dict) else None
            if not next_cursor:
                break
            cursor = str(next_cursor)
        return tuple(members)

    def get_file_info(self, file_id: str) -> dict[str, Any]:
        """Fetch files.info for a canvas/file id.

        Args:
            file_id: slack file or canvas id.

        Returns:
            dict[str, Any]: the file object from the API response.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        response = self._call("files_info", file=file_id)
        file_obj = response.get("file")
        if not isinstance(file_obj, dict):
            raise ExternalServiceError("files.info returned invalid file")
        return file_obj

    def open_view(self, trigger_id: str, view: dict[str, Any]) -> dict[str, Any]:
        """Open a modal via views.open.

        Args:
            trigger_id: slack interactivity trigger id.
            view: block kit view payload.

        Returns:
            dict[str, Any]: views.open response body.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        _LOG.info("views.open starting")
        try:
            result = self._call("views_open", trigger_id=trigger_id, view=view)
        except ExternalServiceError:
            _LOG.exception("views.open failed")
            raise
        _LOG.info("views.open succeeded")
        return result

    def update_view(self, view_id: str, view: dict[str, Any], *, view_hash: str | None = None) -> dict[str, Any]:
        """Update an open modal via views.update.

        Args:
            view_id: slack view id.
            view: replacement block kit view payload.
            view_hash: optional view hash for conflict detection.

        Returns:
            dict[str, Any]: views.update response body.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        kwargs: dict[str, Any] = {"view_id": view_id, "view": view}
        if view_hash is not None:
            kwargs["hash"] = view_hash
        _LOG.info("views.update starting view_id=%s", view_id)
        try:
            result = self._call("views_update", **kwargs)
        except ExternalServiceError:
            _LOG.exception("views.update failed view_id=%s", view_id)
            raise
        _LOG.info("views.update succeeded view_id=%s", view_id)
        return result

    def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Fetch users.info for display-name rendering.

        Args:
            user_id: slack user id.

        Returns:
            dict[str, Any]: the user object from the API response.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        response = self._call("users_info", user=user_id)
        user = response.get("user")
        if not isinstance(user, dict):
            raise ExternalServiceError("users.info returned invalid user")
        return user

    def open_dm(self, user_id: str) -> str:
        """Open a DM channel with a user via conversations.open.

        Args:
            user_id: slack user id.

        Returns:
            str: dm channel id.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        response = self._call("conversations_open", users=user_id)
        channel = response.get("channel")
        if not isinstance(channel, dict) or "id" not in channel:
            raise ExternalServiceError("conversations.open returned invalid channel")
        return str(channel["id"])

    def post_message(self, channel_id: str, *, text: str, blocks: list[dict[str, Any]] | None = None, thread_ts: str | None = None) -> dict[str, Any]:
        """Post a message via chat.postMessage.

        Args:
            channel_id: destination channel id.
            text: fallback text.
            blocks: optional block kit blocks.
            thread_ts: optional parent thread timestamp.

        Returns:
            dict[str, Any]: chat.postMessage response body.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        kwargs: dict[str, Any] = {"channel": channel_id, "text": text}
        if blocks is not None:
            kwargs["blocks"] = blocks
        if thread_ts is not None:
            kwargs["thread_ts"] = thread_ts
        return self._call("chat_postMessage", **kwargs)

    def update_message(self, channel_id: str, ts: str, *, text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Update a bot message via chat.update.

        Args:
            channel_id: channel containing the message.
            ts: message timestamp.
            text: replacement fallback text.
            blocks: optional replacement blocks.

        Returns:
            dict[str, Any]: chat.update response body.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        kwargs: dict[str, Any] = {"channel": channel_id, "ts": ts, "text": text}
        if blocks is not None:
            kwargs["blocks"] = blocks
        return self._call("chat_update", **kwargs)

    def get_permalink(self, channel_id: str, message_ts: str) -> str:
        """Resolve a message permalink via chat.getPermalink.

        Args:
            channel_id: channel containing the message.
            message_ts: message timestamp.

        Returns:
            str: permalink url.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        response = self._call("chat_getPermalink", channel=channel_id, message_ts=message_ts)
        permalink = response.get("permalink")
        if not isinstance(permalink, str) or not permalink:
            raise ExternalServiceError("chat.getPermalink returned invalid permalink")
        return permalink

    def create_channel_canvas(self, channel_id: str, *, title: str) -> str:
        """Create the built-in channel canvas via conversations.canvases.create.

        Args:
            channel_id: slack channel id.
            title: canvas title.

        Returns:
            str: created canvas/file id.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        response = self._call("conversations_canvases_create", channel_id=channel_id, title=title, document_content={"type": "markdown", "markdown": ""})
        canvas_id = response.get("canvas_id")
        if not isinstance(canvas_id, str) or not canvas_id:
            raise ExternalServiceError("conversations.canvases.create returned invalid canvas_id")
        return canvas_id

    def lookup_sections(self, canvas_id: str, *, contains_text: str | None = None, section_types: tuple[str, ...] = ("any_header",)) -> list[dict[str, Any]]:
        """Lookup canvas sections via canvases.sections.lookup.

        Args:
            canvas_id: canvas/file id.
            contains_text: optional text filter.
            section_types: section type filters.

        Returns:
            list[dict[str, Any]]: matching section objects.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        # Omit empty section_types — Slack rejects [] with invalid_arguments.
        criteria: dict[str, Any] = {}
        if section_types:
            criteria["section_types"] = list(section_types)
        if contains_text is not None:
            criteria["contains_text"] = contains_text
        response = self._call("canvases_sections_lookup", canvas_id=canvas_id, criteria=criteria)
        sections = response.get("sections") or []
        if not isinstance(sections, list):
            raise ExternalServiceError("canvases.sections.lookup returned invalid sections")
        return [section for section in sections if isinstance(section, dict)]

    def edit_canvas(self, canvas_id: str, *, operation: str, markdown: str | None = None, section_id: str | None = None, title: str | None = None) -> None:
        """Apply exactly one canvases.edit operation.

        Args:
            canvas_id: canvas/file id.
            operation: canvas edit operation name.
            markdown: document markdown for content operations.
            section_id: target section for relative/replace/delete ops.
            title: title markdown for rename operations.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        change: dict[str, Any] = {"operation": operation}
        if operation == "rename":
            change["title_content"] = {"type": "markdown", "markdown": title or ""}
        else:
            if markdown is not None:
                change["document_content"] = {"type": "markdown", "markdown": markdown}
            if section_id is not None:
                change["section_id"] = section_id
        self._call("canvases_edit", canvas_id=canvas_id, changes=[change])

    def rename_canvas(self, canvas_id: str, *, title: str) -> None:
        """Rename a canvas title via canvases.edit rename.

        Args:
            canvas_id: canvas/file id.
            title: new canvas title.

        Raises:
            ExternalServiceError: on Slack API failure.
        """
        self.edit_canvas(canvas_id, operation="rename", title=title)

    def _call(self, method_name: str, **kwargs: Any) -> dict[str, Any]:
        """Invoke a WebClient method and translate SlackApiError.

        Args:
            method_name: attribute name on WebClient.
            **kwargs: method arguments.

        Returns:
            dict[str, Any]: slack API response data.

        Raises:
            RetryableExternalServiceError: for rate limits and transient failures.
            PermissionDeniedError: for auth/plan/permission failures.
            NotFoundError: for missing resources.
            ConflictError: for conflict responses.
            ExternalServiceError: for other Slack failures.
        """
        method = getattr(self._client, method_name)
        try:
            response = method(**kwargs)
        except SlackApiError as exc:
            raise _translate_slack_error(exc) from None
        data = response.data if hasattr(response, "data") else response
        if not isinstance(data, dict):
            raise ExternalServiceError(f"slack {method_name} returned invalid payload")
        if data.get("ok") is False:
            raise ExternalServiceError(f"slack {method_name} returned ok=false")
        return data


def _translate_slack_error(exc: SlackApiError) -> ConflictError | NotFoundError | ExternalServiceError:
    """Map a SlackApiError into a typed application error.

    Args:
        exc: slack SDK API error.

    Returns:
        ExternalServiceError: typed error subclass appropriate for the failure.
    """
    response = exc.response
    error_code = ""
    headers: dict[str, Any] = {}
    status: int | None = None
    if response is not None:
        status = getattr(response, "status_code", None)
        try:
            headers = dict(response.headers)
        except Exception:
            headers = {}
        try:
            payload = response.get("error") if hasattr(response, "get") else None
            if isinstance(payload, str):
                error_code = payload
            elif isinstance(response.data, dict):
                error_code = str(response.data.get("error") or "")
        except Exception:
            error_code = ""

    retry_after = _parse_retry_after(headers)
    if status == 429 or error_code in _RETRYABLE_ERRORS:
        return RetryableExternalServiceError("slack api temporarily unavailable", retry_after=retry_after)
    if error_code in _PERMISSION_ERRORS:
        return PermissionDeniedError(f"slack permission denied ({error_code})")
    if error_code in _NOT_FOUND_ERRORS:
        return NotFoundError(f"slack resource not found ({error_code})")
    if error_code in _CONFLICT_ERRORS:
        return ConflictError(f"slack resource conflict ({error_code})")
    detail = _slack_error_detail(response)
    suffix = f" ({error_code})" if error_code else ""
    if detail:
        suffix = f"{suffix}: {detail}" if suffix else f" ({detail})"
    return ExternalServiceError(f"slack api request failed{suffix}")


def _slack_error_detail(response: object) -> str:
    """Extract Slack response_metadata.messages for operator-facing errors."""
    if response is None:
        return ""
    data: object = None
    if hasattr(response, "data"):
        data = getattr(response, "data")
    elif isinstance(response, dict):
        data = response
    if not isinstance(data, dict):
        return ""
    metadata = data.get("response_metadata")
    if not isinstance(metadata, dict):
        return ""
    messages = metadata.get("messages")
    if not isinstance(messages, list):
        return ""
    parts = [str(item).strip() for item in messages if str(item).strip()]
    return "; ".join(parts[:3])


def _parse_retry_after(headers: dict[str, Any]) -> float | None:
    """Parse Retry-After from response headers when present.

    Args:
        headers: response headers mapping.

    Returns:
        float | None: seconds to wait, or None when absent/invalid.
    """
    raw = None
    for key, value in headers.items():
        if str(key).lower() == "retry-after":
            raw = value
            break
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
