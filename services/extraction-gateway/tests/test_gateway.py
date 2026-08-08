import json
import logging

import pytest

from extraction_gateway.app import ModelExtractionResponse
from extraction_gateway.openai_client import (
    _UNSUPPORTED_SCHEMA_KEYWORDS as UNSUPPORTED_SCHEMA_KEYWORDS,
)
from extraction_gateway.openai_client import (
    OpenAIClientError,
    OpenAITimeoutError,
    to_strict_schema,
)

from conftest import make_client


def ledger_entry(revision_id="revision-1", segment_id="seg-1", evidence=None, **extra):
    return {
        "topic": "Release",
        "exact_coach_feedback": "Lead, release the sound.",
        "interpretation": None,
        "applies_to": extra.pop("applies_to", None),
        "song_passage_measure": None,
        "problem_heard_before": None,
        "exercise_or_requested_change": None,
        "observed_result": extra.pop("observed_result", None),
        "next_action_and_owner": None,
        "unresolved_question": None,
        "confidence": 0.82,
        "evidence": evidence
        if evidence is not None
        else [
            {
                "transcript_revision_id": revision_id,
                "start_ms": 1100,
                "end_ms": 2000,
                "segment_ids": [segment_id],
            }
        ],
        "extraction_metadata": {},
        **extra,
    }


def test_happy_path_passes_instructions_and_normalizes_evidence(
    settings, extraction_body, auth_headers
):
    payload = {
        "entries": [
            ledger_entry(
                applies_to="Lead",
                observed_result="That was cleaner after the change.",
            )
        ]
    }
    with make_client(settings, payload=payload) as (client, fake):
        response = client.post("/", json=extraction_body, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["entries"][0]["evidence"][0] == {
        "transcript_revision_id": "revision-1",
        "start_ms": 1000,
        "end_ms": 2500,
        "segment_ids": ["seg-1"],
    }
    assert body["entries"][0]["applies_to"] == "Lead"
    assert body["model_entry_count"] == 1
    assert body["rejected_entry_count"] == 0
    assert body["entries"][0]["extraction_metadata"] == {
        "gateway_model_entry_count": 1,
        "gateway_rejected_entry_count": 0,
    }
    sent = fake.calls[0]["messages"][1]["content"]
    for instruction in extraction_body["instructions"]:
        assert instruction in sent


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong-token"}])
def test_rejects_missing_or_wrong_inbound_auth(
    settings, extraction_body, headers
):
    with make_client(settings, payload={"entries": []}) as (client, fake):
        response = client.post("/", json=extraction_body, headers=headers)

    assert response.status_code == 401
    assert fake.calls == []


def test_drops_fabricated_segment_ids_and_logs_reason(
    settings, extraction_body, auth_headers, caplog
):
    payload = {"entries": [ledger_entry(segment_id="fabricated-segment")]}
    caplog.set_level(logging.WARNING, logger="extraction_gateway.app")
    with make_client(settings, payload=payload) as (client, _):
        response = client.post("/", json=extraction_body, headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {
        "entries": [],
        "model_entry_count": 1,
        "rejected_entry_count": 1,
    }
    assert "unknown_segment_id" in caplog.text
    assert "fabricated-segment" in caplog.text
    assert "all model ledger entries were rejected" in caplog.text
    assert "Lead, release the sound." not in caplog.text


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        (ledger_entry(revision_id="other-revision"), "revision_mismatch"),
        (
            ledger_entry(
                evidence=[
                    {
                        "transcript_revision_id": "revision-1",
                        "start_ms": 3000,
                        "end_ms": 4000,
                        "segment_ids": ["seg-1"],
                    }
                ]
            ),
            "range_mismatch",
        ),
    ],
)
def test_logs_other_citation_rejection_reasons(
    settings, extraction_body, auth_headers, caplog, entry, reason
):
    caplog.set_level(logging.WARNING, logger="extraction_gateway.app")
    with make_client(settings, payload={"entries": [entry]}) as (client, _):
        response = client.post("/", json=extraction_body, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["rejected_entry_count"] == 1
    assert reason in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        {"not_entries": []},
        {"entries": [{"topic": "missing required fields"}]},
    ],
)
def test_model_returning_malformed_or_non_conforming_json_is_clean_error(
    settings, extraction_body, auth_headers, payload
):
    with make_client(settings, payload=payload) as (client, _):
        response = client.post("/", json=extraction_body, headers=auth_headers)

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "invalid_model_response"


def test_empty_evidence_list_is_rejected_as_non_conforming(
    settings, extraction_body, auth_headers
):
    payload = {"entries": [ledger_entry(evidence=[])]}
    with make_client(settings, payload=payload) as (client, _):
        response = client.post("/", json=extraction_body, headers=auth_headers)

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "invalid_model_response"


def test_nulls_unsupported_applies_to_and_observed_result(
    settings, extraction_body, auth_headers
):
    payload = {
        "entries": [
            ledger_entry(applies_to="Baritone", observed_result="The chord locked.")
        ]
    }
    with make_client(settings, payload=payload) as (client, _):
        response = client.post("/", json=extraction_body, headers=auth_headers)

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    assert entry["applies_to"] is None
    assert entry["observed_result"] is None


def test_short_observed_result_does_not_auto_pass(
    settings, extraction_body, auth_headers
):
    payload = {"entries": [ledger_entry(observed_result="sound")]}
    with make_client(settings, payload=payload) as (client, _):
        response = client.post("/", json=extraction_body, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["entries"][0]["observed_result"] is None


def test_faithful_observed_result_paraphrase_can_survive(
    settings, extraction_body, auth_headers
):
    payload = {"entries": [ledger_entry(observed_result="change sounded cleaner")]}
    with make_client(settings, payload=payload) as (client, _):
        response = client.post("/", json=extraction_body, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["entries"][0]["observed_result"] == "change sounded cleaner"


@pytest.mark.parametrize(
    ("exc", "expected_status", "expected_code"),
    [
        (OpenAIClientError("OpenAI request failed"), 502, "openai_error"),
        (OpenAITimeoutError("OpenAI request timed out"), 504, "openai_timeout"),
    ],
)
def test_openai_errors_propagate_as_clean_errors(
    settings, extraction_body, auth_headers, exc, expected_status, expected_code
):
    with make_client(settings, exc=exc) as (client, _):
        response = client.post("/", json=extraction_body, headers=auth_headers)

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code


def _strict_mode_violations(node, path="#"):
    violations = []
    if isinstance(node, dict):
        if "properties" in node or node.get("type") == "object":
            if node.get("additionalProperties") is not False:
                violations.append(f"{path}: additionalProperties is not false")
            missing = set(node.get("properties", {})) - set(node.get("required", []))
            if missing:
                violations.append(f"{path}: not required -> {sorted(missing)}")
        for key, value in node.items():
            if key in UNSUPPORTED_SCHEMA_KEYWORDS:
                violations.append(f"{path}: unsupported keyword {key}")
            violations.extend(_strict_mode_violations(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            violations.extend(_strict_mode_violations(value, f"{path}[{index}]"))
    return violations


def test_ledger_schema_sent_to_openai_satisfies_strict_mode():
    strict = to_strict_schema(ModelExtractionResponse.model_json_schema())

    assert _strict_mode_violations(strict) == []


def test_strict_schema_drops_free_form_maps_and_keeps_ledger_fields():
    strict = to_strict_schema(ModelExtractionResponse.model_json_schema())
    entry = strict["$defs"]["LedgerEntryCreate"]

    assert "extraction_metadata" not in entry["properties"]
    assert "topic" in entry["required"]
    assert "exact_coach_feedback" in entry["required"]


def test_strict_schema_does_not_mutate_the_input():
    original = ModelExtractionResponse.model_json_schema()
    snapshot = json.dumps(original, sort_keys=True)

    to_strict_schema(original)

    assert json.dumps(original, sort_keys=True) == snapshot


def test_paraphrased_coach_feedback_is_nulled_not_stored_as_a_quote(
    settings, extraction_body, auth_headers
):
    payload = {
        "entries": [
            ledger_entry(exact_coach_feedback="The coach asked the lead to relax.")
        ]
    }

    with make_client(settings, payload=payload) as (client, _):
        response = client.post("/", json=extraction_body, headers=auth_headers)

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["exact_coach_feedback"] is None


def test_verbatim_coach_feedback_survives_whitespace_and_case_differences(
    settings, extraction_body, auth_headers
):
    payload = {
        "entries": [
            ledger_entry(exact_coach_feedback="Lead,   release   the   SOUND.")
        ]
    }

    with make_client(settings, payload=payload) as (client, _):
        response = client.post("/", json=extraction_body, headers=auth_headers)

    assert response.json()["entries"][0]["exact_coach_feedback"] == (
        "Lead,   release   the   SOUND."
    )


def test_the_model_is_told_to_quote_verbatim(settings, extraction_body, auth_headers):
    with make_client(settings, payload={"entries": []}) as (client, fake):
        client.post("/", json=extraction_body, headers=auth_headers)

    system_prompt = fake.calls[0]["messages"][0]["content"]
    assert "character for character" in system_prompt
