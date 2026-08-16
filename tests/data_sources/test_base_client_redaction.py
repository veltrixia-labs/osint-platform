"""Tests for credential redaction in outbound-request error messages.

requests builds its HTTPError message as "<status> <reason> for url: <full url>",
and Response.url carries the query string — so every client that sends its key as
a query parameter leaks it the moment that exception is logged or returned.
redact_credentials blanks the value and nothing else.

The negative cases below are the point of this file: the diagnostic content of
these messages (which series, which symbol, which dataset, which status) is the
only reason to log them at all, so a future edit to the alternation that starts
eating those is a regression even though nothing raises.

Every credential value here is fabricated.
"""
from data_sources.base_client import redact_credentials

_FAKE = "FAKE-NOT-A-REAL-KEY-0000"


def test_each_credential_parameter_name_is_redacted():
    for name in (
        "api_key",
        "apikey",
        "key",
        "UserID",
        "appId",
        "access_token",
        "registrationkey",
    ):
        out = redact_credentials(f"400 for url: https://example.test/x?{name}={_FAKE}")
        assert f"{name}=REDACTED" in out, name
        assert _FAKE not in out, name


def test_redaction_is_case_insensitive():
    for name in ("ACCESS_TOKEN", "apiKey", "USERID", "AppID"):
        out = redact_credentials(f"400 for url: https://example.test/x?{name}={_FAKE}")
        assert _FAKE not in out, name
        assert "REDACTED" in out, name


def test_credential_first_in_query_string():
    out = redact_credentials(
        f"400 for url: https://example.test/data?api_key={_FAKE}&series_id=GPRH"
    )
    assert out == "400 for url: https://example.test/data?api_key=REDACTED&series_id=GPRH"


def test_credential_mid_query_string():
    out = redact_credentials(
        f"400 for url: https://example.test/data?series_id=GPRH&api_key={_FAKE}&file_type=json"
    )
    assert out == (
        "400 for url: https://example.test/data"
        "?series_id=GPRH&api_key=REDACTED&file_type=json"
    )


def test_non_secret_parameters_survive():
    msg = (
        f"400 for url: https://example.test/q?series_id=GPRH&symbol=SPY"
        f"&statsDataId=0003427113&frequency=weekly&datasetname=GDPbyIndustry"
        f"&file_type=json&api_key={_FAKE}"
    )
    out = redact_credentials(msg)
    for survivor in (
        "series_id=GPRH",
        "symbol=SPY",
        "statsDataId=0003427113",
        "frequency=weekly",
        "datasetname=GDPbyIndustry",
        "file_type=json",
    ):
        assert survivor in out, survivor
    assert _FAKE not in out


def test_parameter_merely_ending_in_key_is_not_redacted():
    # The [?&] anchor is what stops "key" matching the tail of another name.
    for benign in ("sortkey", "monkey", "passkey"):
        msg = f"400 for url: https://example.test/x?{benign}=visible-value"
        assert redact_credentials(msg) == msg, benign


def test_message_without_query_string_is_unchanged():
    msg = "Expecting value: line 1 column 1 (char 0)"
    assert redact_credentials(msg) == msg


def test_worldbank_style_message_is_unchanged():
    msg = (
        "500 Server Error: Internal Server Error for url: "
        "https://example.test/v2/country/US/indicator/NY.GDP.MKTP.CD"
        "?format=json&per_page=1000"
    )
    assert redact_credentials(msg) == msg


def test_none_returns_empty_string():
    assert redact_credentials(None) == ""


def test_status_reason_scheme_host_and_path_survive():
    out = redact_credentials(
        "404 Client Error: Not Found for url: "
        f"https://example.test/fred/series/observations?api_key={_FAKE}&limit=50"
    )
    assert out.startswith("404 Client Error: Not Found for url: ")
    assert "https://example.test/fred/series/observations" in out
    assert "limit=50" in out
    assert _FAKE not in out


def test_accepts_an_exception_object_not_just_a_string():
    exc = ValueError(f"400 for url: https://example.test/x?apikey={_FAKE}&z=1")
    out = redact_credentials(exc)
    assert "apikey=REDACTED" in out
    assert "z=1" in out
    assert _FAKE not in out
