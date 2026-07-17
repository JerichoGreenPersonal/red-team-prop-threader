"""shotgrid adapter for page export and asset import."""

from __future__ import annotations

import io
import csv
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from red_team_prop_threader.domain import ImportResult, ImportedAsset
from red_team_prop_threader._errors import ExternalServiceError, ImportValidationError


if TYPE_CHECKING:
    from urllib.parse import ParseResult
    from collections.abc import Callable

    from red_team_prop_threader.config import Settings


__all__ = ("ShotGridGateway", "build_asset_url", "parse_export_csv", "parse_page_id")

_MAX_EXPORT_ROWS = 30


def _parse_https_authority(url: str, *, label: str) -> tuple[ParseResult, str]:
    """Parse an HTTPS URL authority without leaking malformed input.

    Args:
        url: the URL to parse.
        label: the safe URL label used in validation messages.

    Returns:
        tuple[ParseResult, str]: the parsed URL and normalized hostname.

    Raises:
        ImportValidationError: if parsing or authority inspection fails, the
            scheme is not HTTPS, credentials are present, or the port is not
            implicit or 443.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        username = parsed.username
        password = parsed.password
        port = parsed.port
    except ValueError:
        raise ImportValidationError(f"{label} has invalid authority") from None

    if parsed.scheme != "https":
        raise ImportValidationError(f"{label} must use HTTPS")
    if not hostname:
        raise ImportValidationError(f"{label} must include a hostname")
    if username is not None or password is not None:
        raise ImportValidationError(f"{label} must not include credentials")

    authority = parsed.netloc.rsplit("@", 1)[-1]
    if authority.endswith(":"):
        raise ImportValidationError(f"{label} has invalid authority")
    if port is not None and port != 443:
        raise ImportValidationError(f"{label} must not include a non-standard port")

    return parsed, hostname.lower()


def parse_page_id(url: str, expected_host: str) -> int:
    """Parse and validate a ShotGrid page URL, returning the page ID.

    Args:
        url: the absolute HTTPS page URL to parse.
        expected_host: the required hostname to match exactly (case-insensitive).

    Returns:
        int: the positive integer page ID extracted from the URL path.

    Raises:
        ImportValidationError: if the URL is not a valid absolute HTTPS ShotGrid
            page URL with a matching host and a /page/<positive-integer> path.
    """
    parsed, hostname = _parse_https_authority(url, label="page URL")

    if hostname != expected_host.lower():
        raise ImportValidationError(f"page URL must use host {expected_host!r} exactly")

    if parsed.fragment:
        raise ImportValidationError("page URL must not include a fragment")

    if parsed.query:
        raise ImportValidationError("page URL must not include a query string")

    # remove exactly one optional trailing slash
    path = parsed.path[:-1] if parsed.path.endswith("/") else parsed.path
    parts = path.split("/")

    # valid path: '' / 'page' / '<id>'
    if len(parts) != 3 or parts[0] != "" or parts[1] != "page":
        raise ImportValidationError("page URL path must be /page/<positive integer>")

    id_str = parts[2]
    if not id_str or not id_str.isascii() or not id_str.isdecimal():
        raise ImportValidationError("page URL path must contain a positive integer page ID")

    page_id = int(id_str)
    if page_id <= 0:
        raise ImportValidationError("page ID must be a positive integer")

    return page_id


def _validate_base_url(base_url: str) -> str:
    """Validate a base URL and return it with any trailing slash stripped.

    Args:
        base_url: the URL to validate.

    Returns:
        str: the validated base URL with trailing slash removed.

    Raises:
        ImportValidationError: if the URL is not an absolute HTTPS URL with a
            hostname and no credentials, query string, or fragment.
    """
    parsed, _hostname = _parse_https_authority(base_url, label="base URL")

    if parsed.query:
        raise ImportValidationError("base URL must not include a query string")

    if parsed.fragment:
        raise ImportValidationError("base URL must not include a fragment")

    return base_url.rstrip("/")


def build_asset_url(base_url: str, entity_id: int) -> str:
    """Build an asset detail URL for the given entity ID.

    Args:
        base_url: absolute HTTPS ShotGrid base URL with no credentials, query, or fragment.
        entity_id: positive integer entity ID for the asset.

    Returns:
        str: the full asset detail URL in the form <base_url>/detail/Asset/<entity_id>.

    Raises:
        ImportValidationError: if base_url fails validation or entity_id is not
            a positive integer.
    """
    normalized = _validate_base_url(base_url)
    if isinstance(entity_id, bool) or not isinstance(entity_id, int) or entity_id <= 0:
        raise ImportValidationError("entity ID must be a positive integer")
    return f"{normalized}/detail/Asset/{entity_id}"


def parse_export_csv(csv_text: str, base_url: str) -> ImportResult:
    """Parse and validate a CSV export from ShotGrid into an ImportResult.

    Args:
        csv_text: raw CSV text returned by a ShotGrid page export.
        base_url: absolute HTTPS ShotGrid base URL used to construct asset URLs.

    Returns:
        ImportResult: validated, deduplicated, ordered asset records.

    Raises:
        ImportValidationError: if the CSV is missing required headers, contains
            duplicate required headers, has more than 30 data rows, has zero data
            rows, or contains rows with invalid or missing fields.
    """
    normalized_base = _validate_base_url(base_url)

    csv_text = csv_text.removeprefix("\ufeff")
    reader = csv.DictReader(io.StringIO(csv_text, newline=""), strict=True)

    try:
        # DictReader populates fieldnames on first row read; trigger it
        fieldnames: list[str] = list(reader.fieldnames or [])
        # collect all rows before validating to enforce the raw row limit
        raw_rows: list[dict[Any, Any]] = list(reader)
    except csv.Error:
        raise ImportValidationError("CSV export contains malformed CSV") from None

    if not fieldnames:
        raise ImportValidationError("CSV has no headers")

    normalized_fields = [f.strip().lower() for f in fieldnames]

    if "asset name" not in normalized_fields:
        raise ImportValidationError("CSV is missing required header 'Asset Name'")
    if "entity id" not in normalized_fields:
        raise ImportValidationError("CSV is missing required header 'Entity ID'")

    if normalized_fields.count("asset name") > 1:
        raise ImportValidationError("CSV contains duplicate header 'Asset Name'")
    if normalized_fields.count("entity id") > 1:
        raise ImportValidationError("CSV contains duplicate header 'Entity ID'")

    name_key = fieldnames[normalized_fields.index("asset name")]
    id_key = fieldnames[normalized_fields.index("entity id")]

    if len(raw_rows) > _MAX_EXPORT_ROWS:
        raise ImportValidationError(f"CSV export contains {len(raw_rows)} rows, which exceeds the limit of {_MAX_EXPORT_ROWS}")

    if not raw_rows:
        raise ImportValidationError("CSV export contains no data rows")

    seen_ids: dict[int, bool] = {}
    assets: list[ImportedAsset] = []
    duplicate_count = 0

    for source_index, row in enumerate(raw_rows):
        if None in row:
            raise ImportValidationError(f"row {source_index + 1} is malformed (contains undeclared fields)")

        name_raw: str | None = row.get(name_key)
        id_raw: str | None = row.get(id_key)

        if name_raw is None or id_raw is None:
            raise ImportValidationError(f"row {source_index + 1} is malformed (missing required fields)")

        name = name_raw.strip()
        if not name:
            raise ImportValidationError(f"row {source_index + 1} has a blank asset name")

        id_str = id_raw.strip()
        if not id_str or not id_str.isascii() or not id_str.isdecimal():
            raise ImportValidationError(f"row {source_index + 1} has an invalid entity ID")

        entity_id = int(id_str)
        if entity_id <= 0:
            raise ImportValidationError(f"row {source_index + 1} has a non-positive entity ID")

        if entity_id in seen_ids:
            duplicate_count += 1
            continue

        seen_ids[entity_id] = True
        asset_url = f"{normalized_base}/detail/Asset/{entity_id}"
        assets.append(ImportedAsset(entity_id=entity_id, name=name, url=asset_url, source_index=source_index))

    return ImportResult(assets=tuple(assets), duplicate_count=duplicate_count)


class ShotGridGateway:
    """shotgrid gateway for exporting pages via the script API."""

    def __init__(self, base_url: str, script_name: str, script_key: str, *, client_factory: Callable[[], Any] | None = None) -> None:
        """Initialize the gateway with credentials and an optional client factory.

        Args:
            base_url: normalized HTTPS ShotGrid base URL.
            script_name: ShotGrid script entity name.
            script_key: ShotGrid script API key (not included in repr).
            client_factory: optional callable that returns a Shotgun client; when
                omitted the real shotgun_api3.Shotgun client is constructed.
        """
        normalized_base_url = _validate_base_url(base_url)
        normalized_script_name = script_name.strip()
        normalized_script_key = script_key.strip()
        if not normalized_script_name:
            raise ImportValidationError("ShotGrid script name must not be blank")
        if not normalized_script_key:
            raise ImportValidationError("ShotGrid script key must not be blank")

        self._base_url = normalized_base_url
        self._script_name = normalized_script_name
        self._script_key = normalized_script_key
        try:
            if client_factory is not None:
                self._client: Any = client_factory()
            else:
                import shotgun_api3

                self._client = shotgun_api3.Shotgun(normalized_base_url, script_name=normalized_script_name, api_key=normalized_script_key, connect=False)
        except Exception:
            raise ExternalServiceError("failed to initialize ShotGrid client") from None

    def __repr__(self) -> str:
        """Return a safe repr that does not include credentials."""
        return f"ShotGridGateway(base_url={self._base_url!r})"

    @classmethod
    def from_settings(cls, settings: Settings, *, client_factory: Callable[[], Any] | None = None) -> ShotGridGateway:
        """Construct a gateway from application settings.

        Args:
            settings: immutable application settings.
            client_factory: optional callable that returns a Shotgun client; when
                omitted the real shotgun_api3.Shotgun client is constructed.

        Returns:
            ShotGridGateway: a configured gateway instance.
        """
        return cls(
            base_url=settings.shotgrid_url, script_name=settings.shotgrid_script_name, script_key=settings.shotgrid_script_key, client_factory=client_factory
        )

    def export_page(self, page_id: int) -> str:
        """Export a ShotGrid page and return the raw CSV text.

        Args:
            page_id: the positive integer ID of the page to export.

        Returns:
            str: nonempty CSV text from the ShotGrid export.

        Raises:
            ExternalServiceError: if the client raises, returns a non-string,
                or returns an empty string.
        """
        try:
            result: Any = self._client.export_page(page_id, "csv")
        except Exception:
            raise ExternalServiceError("shotgrid export_page call failed") from None

        if not isinstance(result, str):
            raise ExternalServiceError("shotgrid export_page returned an invalid value")

        if not result:
            raise ExternalServiceError("shotgrid export_page returned empty CSV")

        return result
