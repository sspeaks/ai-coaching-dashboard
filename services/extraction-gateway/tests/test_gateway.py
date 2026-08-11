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


def _many_segments(count: int) -> list[dict]:
    return [
        {
            "segment_id": f"seg-{index}",
            "start_ms": index * 1000,
            "end_ms": index * 1000 + 900,
            "text": f"Coach: Lead, release the sound on bar {index}.",
            "provider_speaker_label": "SPEAKER_00",
        }
        for index in range(count)
    ]


def test_long_transcripts_are_extracted_in_overlapping_windows(
    settings, extraction_body, auth_headers
):
    extraction_body["segments"] = _many_segments(500)
    settings = settings.model_copy(
        update={"window_segment_count": 200, "window_overlap_segments": 15}
    )

    with make_client(settings, payload={"entries": []}) as (client, fake):
        response = client.post("/", json=extraction_body, headers=auth_headers)

    assert response.status_code == 200
    # 500 segments in windows of 200 with 15 overlapping: 0-199, 185-384, 370-499.
    assert len(fake.calls) == 3
    sent_ids = [
        [s["segment_id"] for s in json.loads(call["messages"][1]["content"])["segments"]]
        for call in fake.calls
    ]
    assert [len(ids) for ids in sent_ids] == [200, 200, 130]
    # Every segment must reach the model, or that stretch of the session is
    # silently unexamined -- the bug this windowing exists to fix.
    assert {sid for ids in sent_ids for sid in ids} == {
        s["segment_id"] for s in extraction_body["segments"]
    }
    assert sent_ids[1][0] == "seg-185"


def test_short_transcripts_still_use_a_single_request(
    settings, extraction_body, auth_headers
):
    with make_client(settings, payload={"entries": []}) as (client, fake):
        client.post("/", json=extraction_body, headers=auth_headers)

    assert len(fake.calls) == 1


def test_entries_repeated_across_overlapping_windows_are_deduplicated(
    settings, extraction_body, auth_headers
):
    extraction_body["segments"] = _many_segments(500)
    settings = settings.model_copy(
        update={"window_segment_count": 200, "window_overlap_segments": 15}
    )
    duplicate = ledger_entry(topic="Vocal Technique")
    duplicate["evidence"] = [
        {
            "transcript_revision_id": "revision-1",
            "start_ms": 0,
            "end_ms": 900,
            "segment_ids": ["seg-0"],
        }
    ]

    with make_client(settings, payload={"entries": [duplicate]}) as (client, _):
        response = client.post("/", json=extraction_body, headers=auth_headers)

    body = response.json()
    assert len(body["entries"]) == 1
    assert body["model_entry_count"] == 3


def test_a_failing_window_fails_the_whole_extraction(
    settings, extraction_body, auth_headers
):
    from extraction_gateway.openai_client import OpenAIClientError

    extraction_body["segments"] = _many_segments(500)
    settings = settings.model_copy(update={"window_segment_count": 200})

    # Returning the windows that did succeed would silently drop whole minutes
    # of the session, which is exactly what this feature prevents.
    with make_client(settings, exc=OpenAIClientError("upstream exploded")) as (
        client,
        _,
    ):
        response = client.post("/", json=extraction_body, headers=auth_headers)

    assert response.status_code == 502


def test_a_truncated_model_response_is_an_error_not_a_short_extraction():
    import httpx

    from extraction_gateway.config import Settings
    from extraction_gateway.openai_client import OpenAIClient, OpenAIClientError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": '{"entries": []}'},
                    }
                ]
            },
        )

    client = OpenAIClient(
        Settings(openai_api_key="k", inbound_api_key="test-shared-gateway-token")
    )
    transport = httpx.MockTransport(handler)
    original = httpx.Client

    class PatchedClient(httpx.Client):
        def __init__(self, **kwargs):
            kwargs["transport"] = transport
            super().__init__(**kwargs)

    httpx.Client = PatchedClient
    try:
        with pytest.raises(OpenAIClientError, match="finish_reason"):
            client.extract_json(messages=[], schema={"type": "object"})
    finally:
        httpx.Client = original


def summary_request(**extra):
    return {
        "schema_version": "coaching-ledger-v1",
        "session": {"id": "session-1", "title": "Coaching session"},
        "transcript_revision_id": "revision-1",
        "theme_count": 5,
        "entries": [
            {
                "id": "entry-1",
                "topic": "Release",
                "exact_coach_feedback": "Lead, release the sound.",
                "interpretation": None,
                "applies_to": None,
                "exercise_or_requested_change": None,
                "next_action_and_owner": None,
                "start_ms": 1000,
                "end_ms": 2500,
            }
        ],
        **extra,
    }


def test_summary_themes_cite_only_supplied_entries(settings, auth_headers):
    payload = {
        "themes": [
            {
                "title": "Releasing the sound",
                "summary": "Worked on releasing tension.",
                "ledger_entry_ids": ["entry-1", "entry-does-not-exist"],
            }
        ]
    }

    with make_client(settings, payload=payload) as (client, _):
        response = client.post(
            "/summarize", json=summary_request(), headers=auth_headers
        )

    assert response.status_code == 200
    themes = response.json()["themes"]
    # An id we never supplied is an invented citation and must not survive.
    assert themes[0]["ledger_entry_ids"] == ["entry-1"]


def test_a_theme_left_with_no_real_entries_is_discarded(settings, auth_headers):
    payload = {
        "themes": [
            {
                "title": "Invented",
                "summary": "Nothing real backs this.",
                "ledger_entry_ids": ["nope"],
            }
        ]
    }

    with make_client(settings, payload=payload) as (client, _):
        response = client.post(
            "/summarize", json=summary_request(), headers=auth_headers
        )

    assert response.json()["themes"] == []


def test_an_entry_is_claimed_by_only_one_theme(settings, auth_headers):
    payload = {
        "themes": [
            {
                "title": "First",
                "summary": "First theme.",
                "ledger_entry_ids": ["entry-1"],
            },
            {
                "title": "Second",
                "summary": "Second theme claiming the same entry.",
                "ledger_entry_ids": ["entry-1"],
            },
        ]
    }

    with make_client(settings, payload=payload) as (client, _):
        response = client.post(
            "/summarize", json=summary_request(), headers=auth_headers
        )

    themes = response.json()["themes"]
    assert [theme["title"] for theme in themes] == ["First"]


def test_summarizing_nothing_does_not_call_the_model(settings, auth_headers):
    with make_client(settings, payload={"themes": []}) as (client, fake):
        response = client.post(
            "/summarize", json=summary_request(entries=[]), headers=auth_headers
        )

    assert response.json()["themes"] == []
    assert fake.calls == []


def test_summarize_requires_authentication(settings):
    with make_client(settings, payload={"themes": []}) as (client, _):
        response = client.post("/summarize", json=summary_request())

    assert response.status_code == 401


# --- Consolidation endpoint tests ---


def consolidation_request(**extra):
    return {
        "schema_version": "coaching-ledger-v1",
        "session": {"id": "session-1", "title": "Coaching session"},
        "entries": [
            {
                "id": "entry-1",
                "topic": "Release",
                "exact_coach_feedback": "Lead, release the sound.",
                "interpretation": None,
                "applies_to": None,
                "exercise_or_requested_change": None,
                "next_action_and_owner": None,
                "start_ms": 1000,
                "end_ms": 2500,
            },
            {
                "id": "entry-2",
                "topic": "Release exercise",
                "exact_coach_feedback": "Try that again with less tension.",
                "interpretation": None,
                "applies_to": None,
                "exercise_or_requested_change": None,
                "next_action_and_owner": None,
                "start_ms": 3000,
                "end_ms": 4500,
            },
        ],
        **extra,
    }


def test_consolidation_groups_entries(settings, auth_headers):
    payload = {
        "groups": [
            {
                "canonical_topic": "Releasing tension",
                "entry_ids": ["entry-1", "entry-2"],
            }
        ]
    }

    with make_client(settings, payload=payload) as (client, _):
        response = client.post(
            "/consolidate", json=consolidation_request(), headers=auth_headers
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["groups"]) == 1
    assert data["groups"][0]["entry_ids"] == ["entry-1", "entry-2"]
    assert data["ungrouped_entry_ids"] == []


def test_consolidation_assigns_ungrouped_entries_to_singletons(settings, auth_headers):
    # Model only groups entry-1, forgetting entry-2
    payload = {
        "groups": [
            {
                "canonical_topic": "Release",
                "entry_ids": ["entry-1"],
            }
        ]
    }

    with make_client(settings, payload=payload) as (client, _):
        response = client.post(
            "/consolidate", json=consolidation_request(), headers=auth_headers
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["groups"]) == 2
    assert data["ungrouped_entry_ids"] == ["entry-2"]


def test_consolidation_drops_unknown_entry_ids(settings, auth_headers):
    payload = {
        "groups": [
            {
                "canonical_topic": "Release",
                "entry_ids": ["entry-1", "entry-invented"],
            }
        ]
    }

    with make_client(settings, payload=payload) as (client, _):
        response = client.post(
            "/consolidate", json=consolidation_request(), headers=auth_headers
        )

    assert response.status_code == 200
    groups = response.json()["groups"]
    # entry-invented is dropped; entry-2 becomes a singleton
    entry_ids_flat = [eid for g in groups for eid in g["entry_ids"]]
    assert "entry-invented" not in entry_ids_flat
    assert "entry-1" in entry_ids_flat
    assert "entry-2" in entry_ids_flat


def test_consolidation_empty_entries_returns_empty(settings, auth_headers):
    with make_client(settings, payload={"groups": []}) as (client, fake):
        response = client.post(
            "/consolidate",
            json=consolidation_request(entries=[]),
            headers=auth_headers,
        )

    assert response.status_code == 200
    assert response.json() == {"groups": [], "ungrouped_entry_ids": []}
    assert fake.calls == []


def test_consolidation_requires_authentication(settings):
    with make_client(settings, payload={"groups": []}) as (client, _):
        response = client.post("/consolidate", json=consolidation_request())

    assert response.status_code == 401
