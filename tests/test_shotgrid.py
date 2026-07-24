"""Tests for the ShotGrid adapter module."""

from __future__ import annotations

import sys
from types import SimpleNamespace
import builtins
from unittest.mock import MagicMock

import pytest

from red_team_prop_threader.domain import ImportResult
from red_team_prop_threader._errors import ExternalServiceError, ImportValidationError


_EXPECTED_HOST = "respawn.shotgunstudio.com"
_BASE_URL = "https://respawn.shotgunstudio.com"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_gateway(return_value: object = "Asset Name,Entity ID\nS31 Chair,101\n") -> object:
    """Build a ShotGridGateway with an injected mock client."""
    from red_team_prop_threader.shotgrid import ShotGridGateway

    mock_client = MagicMock()
    mock_client.export_page.return_value = return_value
    return ShotGridGateway(base_url=_BASE_URL, script_name="test-script", script_key="test-key", client_factory=lambda: mock_client)


# ---------------------------------------------------------------------------
# parse_page_id — valid cases
# ---------------------------------------------------------------------------


def test_parse_page_id_valid() -> None:
    """Valid URL returns positive page ID."""
    from red_team_prop_threader.shotgrid import parse_page_id

    assert parse_page_id("https://respawn.shotgunstudio.com/page/23280", _EXPECTED_HOST) == 23280


def test_parse_page_id_trailing_slash() -> None:
    """URL with a single trailing slash is accepted."""
    from red_team_prop_threader.shotgrid import parse_page_id

    assert parse_page_id("https://respawn.shotgunstudio.com/page/100/", _EXPECTED_HOST) == 100


def test_parse_page_id_host_case_insensitive() -> None:
    """Hostname comparison is case-insensitive."""
    from red_team_prop_threader.shotgrid import parse_page_id

    assert parse_page_id("https://RESPAWN.SHOTGUNSTUDIO.COM/page/1", _EXPECTED_HOST) == 1


# ---------------------------------------------------------------------------
# parse_page_id — rejection cases
# ---------------------------------------------------------------------------


def test_parse_page_id_rejects_http() -> None:
    """Non-HTTPS scheme raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError):
        parse_page_id("http://respawn.shotgunstudio.com/page/1", _EXPECTED_HOST)


def test_parse_page_id_rejects_wrong_host() -> None:
    """Wrong hostname raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError):
        parse_page_id("https://other.shotgunstudio.com/page/1", _EXPECTED_HOST)


def test_parse_page_id_rejects_subdomain() -> None:
    """Subdomain of expected host raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError):
        parse_page_id("https://sub.respawn.shotgunstudio.com/page/1", _EXPECTED_HOST)


def test_parse_page_id_rejects_userinfo() -> None:
    """URL with userinfo raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError):
        parse_page_id("https://user:pass@respawn.shotgunstudio.com/page/1", _EXPECTED_HOST)


def test_parse_page_id_rejects_unexpected_port() -> None:
    """URL with an explicit non-standard port raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError):
        parse_page_id("https://respawn.shotgunstudio.com:8443/page/1", _EXPECTED_HOST)


def test_parse_page_id_rejects_no_path() -> None:
    """URL with no page path raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError):
        parse_page_id("https://respawn.shotgunstudio.com/", _EXPECTED_HOST)


def test_parse_page_id_rejects_wrong_path() -> None:
    """URL with a non-page path raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError):
        parse_page_id("https://respawn.shotgunstudio.com/detail/Asset/1", _EXPECTED_HOST)


def test_parse_page_id_rejects_extra_segments() -> None:
    """URL with extra path segments after page ID raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError):
        parse_page_id("https://respawn.shotgunstudio.com/page/1/extra", _EXPECTED_HOST)


def test_parse_page_id_rejects_zero_id() -> None:
    """Page ID of zero raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError):
        parse_page_id("https://respawn.shotgunstudio.com/page/0", _EXPECTED_HOST)


def test_parse_page_id_rejects_negative_id() -> None:
    """Negative page path segment raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError):
        parse_page_id("https://respawn.shotgunstudio.com/page/-1", _EXPECTED_HOST)


def test_parse_page_id_rejects_non_integer_id() -> None:
    """Non-integer page path segment raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError):
        parse_page_id("https://respawn.shotgunstudio.com/page/abc", _EXPECTED_HOST)


def test_parse_page_id_rejects_fragment() -> None:
    """URL with a fragment raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError):
        parse_page_id("https://respawn.shotgunstudio.com/page/1#section", _EXPECTED_HOST)


def test_parse_page_id_rejects_query() -> None:
    """URL with a query string raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError):
        parse_page_id("https://respawn.shotgunstudio.com/page/1?filter=foo", _EXPECTED_HOST)


def test_parse_page_id_error_does_not_echo_query_values() -> None:
    """ImportValidationError does not echo query string values."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError) as exc_info:
        parse_page_id("https://respawn.shotgunstudio.com/page/1?token=SENTINEL_SECRET", _EXPECTED_HOST)
    assert "SENTINEL_SECRET" not in str(exc_info.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://[invalid/page/1",
        "https://respawn.shotgunstudio.com:not-a-port/page/1",
        "https://respawn.shotgunstudio.com:70000/page/1",
        "https://respawn.shotgunstudio.com:/page/1",
    ],
)
def test_parse_page_id_rejects_malformed_authority_safely(url: str) -> None:
    """Malformed authorities become static validation errors."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError, match="invalid authority") as exc_info:
        parse_page_id(url, _EXPECTED_HOST)
    assert url not in str(exc_info.value)


def test_parse_page_id_accepts_bracketed_ipv6_default_port() -> None:
    """Bracketed IPv6 with the HTTPS default port is parsed safely."""
    from red_team_prop_threader.shotgrid import parse_page_id

    assert parse_page_id("https://[2001:db8::1]:443/page/1", "2001:db8::1") == 1


def test_parse_page_id_rejects_ipv6_nonstandard_port() -> None:
    """Bracketed IPv6 with a nonstandard port is rejected."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError, match="port"):
        parse_page_id("https://[2001:db8::1]:8443/page/1", "2001:db8::1")


def test_parse_page_id_rejects_empty_userinfo() -> None:
    """An empty username before an at-sign is still userinfo."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError, match="credentials"):
        parse_page_id("https://@respawn.shotgunstudio.com/page/1", _EXPECTED_HOST)


def test_parse_page_id_rejects_multiple_trailing_slashes() -> None:
    """Only one optional trailing slash is accepted."""
    from red_team_prop_threader.shotgrid import parse_page_id

    with pytest.raises(ImportValidationError, match="path"):
        parse_page_id("https://respawn.shotgunstudio.com/page/1//", _EXPECTED_HOST)


# ---------------------------------------------------------------------------
# build_asset_url
# ---------------------------------------------------------------------------


def test_build_asset_url_valid() -> None:
    """Valid base URL and entity ID produce correct asset URL."""
    from red_team_prop_threader.shotgrid import build_asset_url

    url = build_asset_url(_BASE_URL, 101)
    assert url == "https://respawn.shotgunstudio.com/detail/Asset/101"


def test_build_asset_url_rejects_http() -> None:
    """Non-HTTPS base URL raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import build_asset_url

    with pytest.raises(ImportValidationError):
        build_asset_url("http://respawn.shotgunstudio.com", 1)


def test_build_asset_url_rejects_no_hostname() -> None:
    """Base URL without hostname raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import build_asset_url

    with pytest.raises(ImportValidationError):
        build_asset_url("https://", 1)


def test_build_asset_url_rejects_credentials() -> None:
    """Base URL with credentials raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import build_asset_url

    with pytest.raises(ImportValidationError):
        build_asset_url("https://user:pass@example.com", 1)


def test_build_asset_url_rejects_query() -> None:
    """Base URL with a query string raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import build_asset_url

    with pytest.raises(ImportValidationError):
        build_asset_url("https://example.com?key=val", 1)


def test_build_asset_url_rejects_fragment() -> None:
    """Base URL with a fragment raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import build_asset_url

    with pytest.raises(ImportValidationError):
        build_asset_url("https://example.com#section", 1)


@pytest.mark.parametrize(
    "base_url", ["https://[invalid", "https://example.com:not-a-port", "https://example.com:70000", "https://example.com:", "https://[2001:db8::1]:8443"]
)
def test_build_asset_url_rejects_malformed_or_unexpected_authority(base_url: str) -> None:
    """Malformed authorities and nonstandard ports fail safely."""
    from red_team_prop_threader.shotgrid import build_asset_url

    with pytest.raises(ImportValidationError):
        build_asset_url(base_url, 1)


def test_build_asset_url_accepts_bracketed_ipv6_default_port() -> None:
    """Bracketed IPv6 and explicit port 443 remain valid."""
    from red_team_prop_threader.shotgrid import build_asset_url

    assert build_asset_url("https://[2001:db8::1]:443/", 1) == "https://[2001:db8::1]:443/detail/Asset/1"


def test_build_asset_url_rejects_empty_userinfo() -> None:
    """An empty username in the base URL is rejected."""
    from red_team_prop_threader.shotgrid import build_asset_url

    with pytest.raises(ImportValidationError, match="credentials"):
        build_asset_url("https://@example.com", 1)


@pytest.mark.parametrize("entity_id", [0, -1, "1", 1.0, True])
def test_build_asset_url_rejects_non_positive_or_non_integer_entity_ids(entity_id: object) -> None:
    """Runtime callers cannot bypass positive integer entity ID validation."""
    from red_team_prop_threader.shotgrid import build_asset_url

    with pytest.raises(ImportValidationError, match="positive integer"):
        build_asset_url(_BASE_URL, entity_id)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# parse_export_csv — mandatory TDD cases from spec
# ---------------------------------------------------------------------------


def test_parse_export_deduplicates_ids_and_preserves_first_order() -> None:
    """Duplicate entity IDs are deduplicated preserving first occurrence."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    csv_text = "Asset Name,Entity ID\nS31 Chair,101\nS31 Lamp,102\nS31 Chair duplicate,101\n"
    result = parse_export_csv(csv_text, "https://respawn.shotgunstudio.com")
    assert [asset.entity_id for asset in result.assets] == [101, 102]
    assert result.duplicate_count == 1


def test_parse_export_rejects_more_than_thirty_rows() -> None:
    """More than 30 raw rows raises ImportValidationError mentioning 30."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    rows = "\n".join(f"S31 Asset {index},{index}" for index in range(1, 32))
    with pytest.raises(ImportValidationError, match="30"):
        parse_export_csv(f"Asset Name,Entity ID\n{rows}\n", "https://respawn.shotgunstudio.com")


# ---------------------------------------------------------------------------
# parse_export_csv — valid cases
# ---------------------------------------------------------------------------


def test_parse_export_csv_valid_basic() -> None:
    """Valid CSV returns assets in order with correct fields."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    csv_text = "Asset Name,Entity ID\nS31 Chair,101\nS31 Lamp,102\n"
    result = parse_export_csv(csv_text, _BASE_URL)
    assert isinstance(result, ImportResult)
    assert len(result.assets) == 2
    assert result.assets[0].entity_id == 101
    assert result.assets[0].name == "S31 Chair"
    assert result.assets[0].source_index == 0
    assert result.assets[1].entity_id == 102
    assert result.assets[1].source_index == 1
    assert result.duplicate_count == 0


def test_parse_export_csv_accepts_exactly_thirty_rows() -> None:
    """Exactly 30 rows is accepted without error."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    rows = "\n".join(f"Asset {i},{i}" for i in range(1, 31))
    result = parse_export_csv(f"Asset Name,Entity ID\n{rows}", _BASE_URL)
    assert len(result.assets) == 30


def test_parse_export_csv_raw_row_limit_before_dedupe() -> None:
    """31 raw rows with duplicates still raises even if deduped count would be <=30."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    rows = "\n".join(f"Asset {i},{i}" for i in range(1, 31))
    dup = "Asset 1 dup,1"
    with pytest.raises(ImportValidationError, match="30"):
        parse_export_csv(f"Asset Name,Entity ID\n{rows}\n{dup}\n", _BASE_URL)


def test_parse_export_csv_case_insensitive_headers() -> None:
    """Headers are matched case-insensitively."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    csv_text = "asset name,entity id\nS31 Chair,101\n"
    result = parse_export_csv(csv_text, _BASE_URL)
    assert result.assets[0].entity_id == 101


def test_parse_export_csv_accepts_id_alias_for_entity_id() -> None:
    """ShotGrid page exports that use Id are accepted as Entity ID."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    result = parse_export_csv("Asset Name,Id\nS31 Chair,101\n", _BASE_URL)
    assert result.assets[0].entity_id == 101
    assert result.assets[0].name == "S31 Chair"


def test_parse_export_csv_prefers_entity_id_over_id_alias() -> None:
    """When both Entity ID and Id exist, Entity ID wins."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    csv_text = "Asset Name,Id,Entity ID\nWrong Name,999,101\n"
    result = parse_export_csv(csv_text, _BASE_URL)
    assert result.assets[0].entity_id == 101


def test_parse_export_csv_rejects_duplicate_id_alias_header() -> None:
    """Duplicate Id headers raise ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    with pytest.raises(ImportValidationError, match="Entity ID"):
        parse_export_csv("Asset Name,Id,Id\nS31 Chair,101,101\n", _BASE_URL)


def test_parse_export_csv_whitespace_stripped_headers() -> None:
    """Headers with surrounding whitespace are matched after stripping."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    csv_text = " Asset Name , Entity ID \nS31 Chair,101\n"
    result = parse_export_csv(csv_text, _BASE_URL)
    assert result.assets[0].entity_id == 101


def test_parse_export_csv_extra_columns_ignored() -> None:
    """Extra columns in CSV are silently ignored."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    csv_text = "Asset Name,Entity ID,Status\nS31 Chair,101,Active\n"
    result = parse_export_csv(csv_text, _BASE_URL)
    assert result.assets[0].entity_id == 101


def test_parse_export_csv_accepts_utf8_bom() -> None:
    """One UTF-8 BOM before the first header is ignored."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    result = parse_export_csv("\ufeffAsset Name,Entity ID\r\nS31 Chair,101\r\n", _BASE_URL)
    assert result.assets[0].name == "S31 Chair"


def test_parse_export_csv_accepts_quoted_comma() -> None:
    """Quoted commas remain part of an asset name."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    result = parse_export_csv('Asset Name,Entity ID\r\n"Chair, Large",101\r\n', _BASE_URL)
    assert result.assets[0].name == "Chair, Large"


def test_parse_export_csv_accepts_quoted_newline() -> None:
    """Quoted newlines remain part of an asset name."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    result = parse_export_csv('Asset Name,Entity ID\r\n"Chair\r\nLarge",101\r\n', _BASE_URL)
    assert result.assets[0].name == "Chair\r\nLarge"


def test_parse_export_csv_rejects_malformed_quotes_safely() -> None:
    """Strict CSV parser errors become static import validation errors."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    sentinel = "SENTINEL_CSV_CONTENT"
    with pytest.raises(ImportValidationError, match="malformed CSV") as exc_info:
        parse_export_csv(f'Asset Name,Entity ID\r\n"unclosed {sentinel},101\r\n', _BASE_URL)
    assert sentinel not in str(exc_info.value)


def test_parse_export_csv_rejects_overwide_rows() -> None:
    """Rows with undeclared cells are rejected as malformed."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    with pytest.raises(ImportValidationError, match="malformed"):
        parse_export_csv("Asset Name,Entity ID\r\nChair,101,unexpected\r\n", _BASE_URL)


def test_parse_export_csv_asset_url_format() -> None:
    """Asset URL is constructed as <base_url>/detail/Asset/<entity_id>."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    result = parse_export_csv("Asset Name,Entity ID\nS31 Chair,101\n", _BASE_URL)
    assert result.assets[0].url == f"{_BASE_URL}/detail/Asset/101"


def test_parse_export_csv_stable_source_index() -> None:
    """source_index reflects original zero-based data-row position."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    csv_text = "Asset Name,Entity ID\nA,1\nB,2\nC,3\n"
    result = parse_export_csv(csv_text, _BASE_URL)
    assert [a.source_index for a in result.assets] == [0, 1, 2]


def test_parse_export_csv_source_index_on_dedup() -> None:
    """source_index of kept asset reflects the first occurrence's row index."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    csv_text = "Asset Name,Entity ID\nA,1\nB,2\nA dup,1\n"
    result = parse_export_csv(csv_text, _BASE_URL)
    a1 = next(a for a in result.assets if a.entity_id == 1)
    assert a1.source_index == 0


# ---------------------------------------------------------------------------
# parse_export_csv — rejection cases
# ---------------------------------------------------------------------------


def test_parse_export_csv_rejects_missing_asset_name_header() -> None:
    """Missing Asset Name header raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    with pytest.raises(ImportValidationError):
        parse_export_csv("Entity ID\n101\n", _BASE_URL)


def test_parse_export_csv_rejects_missing_entity_id_header() -> None:
    """Missing Entity ID header raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    with pytest.raises(ImportValidationError):
        parse_export_csv("Asset Name\nS31 Chair\n", _BASE_URL)


def test_parse_export_csv_rejects_duplicate_entity_id_header() -> None:
    """Duplicate Entity ID header raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    with pytest.raises(ImportValidationError):
        parse_export_csv("Asset Name,Entity ID,Entity ID\nS31 Chair,101,101\n", _BASE_URL)


def test_parse_export_csv_rejects_zero_data_rows() -> None:
    """CSV with header but no data rows raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    with pytest.raises(ImportValidationError):
        parse_export_csv("Asset Name,Entity ID\n", _BASE_URL)


def test_parse_export_csv_rejects_blank_name() -> None:
    """Row with blank asset name raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    with pytest.raises(ImportValidationError):
        parse_export_csv("Asset Name,Entity ID\n  ,101\n", _BASE_URL)


def test_parse_export_csv_rejects_missing_entity_id_cell() -> None:
    """Row with fewer fields than headers (missing entity ID) raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    with pytest.raises(ImportValidationError):
        parse_export_csv("Asset Name,Entity ID\nS31 Chair\n", _BASE_URL)


def test_parse_export_csv_rejects_non_ascii_entity_id() -> None:
    """Non-ASCII entity ID raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    with pytest.raises(ImportValidationError):
        parse_export_csv("Asset Name,Entity ID\nS31 Chair,\uff10\uff11\uff10\n", _BASE_URL)


def test_parse_export_csv_rejects_zero_entity_id() -> None:
    """Entity ID of zero raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    with pytest.raises(ImportValidationError):
        parse_export_csv("Asset Name,Entity ID\nS31 Chair,0\n", _BASE_URL)


def test_parse_export_csv_rejects_negative_entity_id() -> None:
    """Negative entity ID raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    with pytest.raises(ImportValidationError):
        parse_export_csv("Asset Name,Entity ID\nS31 Chair,-1\n", _BASE_URL)


def test_parse_export_csv_rejects_non_integer_entity_id() -> None:
    """Non-integer entity ID raises ImportValidationError."""
    from red_team_prop_threader.shotgrid import parse_export_csv

    with pytest.raises(ImportValidationError):
        parse_export_csv("Asset Name,Entity ID\nS31 Chair,not-a-number\n", _BASE_URL)


# ---------------------------------------------------------------------------
# ShotGridGateway — success
# ---------------------------------------------------------------------------


def test_gateway_export_page_returns_csv() -> None:
    """Gateway returns CSV text from the injected client's export_page call."""
    from red_team_prop_threader.shotgrid import ShotGridGateway

    mock_client = MagicMock()
    mock_client.export_page.return_value = "Asset Name,Entity ID\nS31 Chair,101\n"
    gw = ShotGridGateway(base_url=_BASE_URL, script_name="test-script", script_key="test-key", client_factory=lambda: mock_client)
    result = gw.export_page(23280)
    mock_client.export_page.assert_called_once_with(23280, "csv")
    assert "Asset Name" in result


def test_gateway_from_settings_constructs_gateway() -> None:
    """ShotGridGateway.from_settings constructs a usable gateway."""
    from red_team_prop_threader.config import Settings
    from red_team_prop_threader.shotgrid import ShotGridGateway

    settings = Settings(
        slack_bot_token="xoxb-test",
        slack_signing_secret="signing-secret",
        slack_app_token="xapp-test",
        shotgrid_script_name="test-script",
        shotgrid_script_key="test-key",
        shotgrid_url=_BASE_URL,
        slack_public_base_url="https://example.invalid",
        shotgrid_test_page_id=23280,
        database_url="sqlite:///test.db",
        test_postgres_url=None,
        canvas_timezone="America/Los_Angeles",
        web_host="127.0.0.1",
        web_port=3000,
        worker_poll_seconds=2,
        tunnel_command=None,
        tunnel_health_url=None,
    )
    mock_client = MagicMock()
    mock_client.export_page.return_value = "Asset Name,Entity ID\nS31 Chair,101\n"
    gw = ShotGridGateway.from_settings(settings, client_factory=lambda: mock_client)
    result = gw.export_page(23280)
    assert result


# ---------------------------------------------------------------------------
# ShotGridGateway — error translation
# ---------------------------------------------------------------------------


def test_gateway_export_page_client_exception_raises_external_service_error() -> None:
    """Client runtime exception is wrapped in ExternalServiceError."""
    from red_team_prop_threader.shotgrid import ShotGridGateway

    mock_client = MagicMock()
    mock_client.export_page.side_effect = RuntimeError("network failure")
    gw = ShotGridGateway(base_url=_BASE_URL, script_name="test-script", script_key="test-key", client_factory=lambda: mock_client)
    with pytest.raises(ExternalServiceError):
        gw.export_page(23280)


def test_gateway_export_error_does_not_leak_message_or_cause() -> None:
    """Export failures expose neither the unsafe message nor cause."""
    from red_team_prop_threader.shotgrid import ShotGridGateway

    sentinel = "SENTINEL_EXPORT_SECRET"
    mock_client = MagicMock()
    mock_client.export_page.side_effect = RuntimeError(sentinel)
    gw = ShotGridGateway(base_url=_BASE_URL, script_name="test-script", script_key="test-key", client_factory=lambda: mock_client)

    with pytest.raises(ExternalServiceError) as exc_info:
        gw.export_page(23280)
    assert sentinel not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert str(exc_info.value) == "shotgrid export_page call failed"


def test_gateway_export_classifies_retired_page_fault() -> None:
    """Retired-page Faults become a concrete user-safe message."""
    from red_team_prop_threader.shotgrid import ShotGridGateway

    mock_client = MagicMock()
    mock_client.export_page.side_effect = RuntimeError("Trying to perform export for retired Page id=99")
    gw = ShotGridGateway(base_url=_BASE_URL, script_name="test-script", script_key="test-key", client_factory=lambda: mock_client)
    with pytest.raises(ExternalServiceError, match="page 99 is retired"):
        gw.export_page(99)


def test_gateway_export_classifies_export_not_available_fault() -> None:
    """Canvas/non-exportable page Faults become concrete guidance."""
    from red_team_prop_threader.shotgrid import ShotGridGateway

    mock_client = MagicMock()
    mock_client.export_page.side_effect = RuntimeError("Export for Page id=23446 not available")
    gw = ShotGridGateway(base_url=_BASE_URL, script_name="test-script", script_key="test-key", client_factory=lambda: mock_client)
    with pytest.raises(ExternalServiceError, match="not API-exportable"):
        gw.export_page(23446)


def test_gateway_export_page_non_string_return_raises_external_service_error() -> None:
    """Non-string return value from client raises ExternalServiceError."""
    gw = _make_gateway(return_value=42)
    with pytest.raises(ExternalServiceError):
        gw.export_page(23280)  # type: ignore[union-attr]


def test_gateway_export_page_empty_string_raises_external_service_error() -> None:
    """Empty string return from client raises ExternalServiceError."""
    gw = _make_gateway(return_value="")
    with pytest.raises(ExternalServiceError):
        gw.export_page(23280)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# ShotGridGateway — credential safety
# ---------------------------------------------------------------------------


def test_gateway_repr_does_not_expose_script_key() -> None:
    """repr(ShotGridGateway) does not include the script key."""
    from red_team_prop_threader.shotgrid import ShotGridGateway

    gw = ShotGridGateway(base_url=_BASE_URL, script_name="test-script", script_key="SENTINEL_KEY_VALUE", client_factory=lambda: MagicMock())
    assert "SENTINEL_KEY_VALUE" not in repr(gw)


def test_gateway_normalizes_base_url_in_repr() -> None:
    """Gateway stores a normalized validated base URL."""
    from red_team_prop_threader.shotgrid import ShotGridGateway

    gw = ShotGridGateway(base_url=f"{_BASE_URL}/", script_name="test-script", script_key="test-key", client_factory=lambda: MagicMock())
    assert repr(gw) == f"ShotGridGateway(base_url={_BASE_URL!r})"


@pytest.mark.parametrize(("script_name", "script_key"), [("", "key"), ("   ", "key"), ("name", ""), ("name", "   ")])
def test_gateway_rejects_blank_script_credentials(script_name: str, script_key: str) -> None:
    """Script names and keys must contain non-whitespace text."""
    from red_team_prop_threader.shotgrid import ShotGridGateway

    with pytest.raises(ImportValidationError):
        ShotGridGateway(base_url=_BASE_URL, script_name=script_name, script_key=script_key, client_factory=lambda: MagicMock())


def test_gateway_factory_failure_is_static_and_safe() -> None:
    """Injected client factory failures become static external errors."""
    from red_team_prop_threader.shotgrid import ShotGridGateway

    sentinel = "SENTINEL_FACTORY_SECRET"

    def fail_factory() -> object:
        raise RuntimeError(sentinel)

    with pytest.raises(ExternalServiceError, match="initialize") as exc_info:
        ShotGridGateway(base_url=_BASE_URL, script_name="test-script", script_key="test-key", client_factory=fail_factory)
    assert sentinel not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_gateway_lazy_import_failure_is_static_and_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lazy shotgun_api3 import failures become static external errors."""
    from red_team_prop_threader.shotgrid import ShotGridGateway

    sentinel = "SENTINEL_IMPORT_SECRET"
    original_import = builtins.__import__

    def fail_shotgun_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "shotgun_api3":
            raise ImportError(sentinel)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_shotgun_import)
    with pytest.raises(ExternalServiceError, match="initialize") as exc_info:
        ShotGridGateway(base_url=_BASE_URL, script_name="test-script", script_key="test-key")
    assert sentinel not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_gateway_client_construction_failure_is_static_and_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shotgun client constructor failures become static external errors."""
    from red_team_prop_threader.shotgrid import ShotGridGateway

    sentinel = "SENTINEL_CONSTRUCTOR_SECRET"

    def fail_constructor(*args: object, **kwargs: object) -> object:
        raise RuntimeError(sentinel)

    monkeypatch.setitem(sys.modules, "shotgun_api3", SimpleNamespace(Shotgun=fail_constructor))
    with pytest.raises(ExternalServiceError, match="initialize") as exc_info:
        ShotGridGateway(base_url=_BASE_URL, script_name="test-script", script_key="test-key")
    assert sentinel not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
