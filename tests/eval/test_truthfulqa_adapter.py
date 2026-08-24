from eval.truthfulqa_adapter import _parse_judge_response, compute_mc1
from eval.benchmark_protocol import (
    build_manifest,
    classify_record,
    dataset_sha256,
    record_accounting,
    run_status,
)


def test_parse_judge_response_accepts_complete_json():
    data, valid = _parse_judge_response(
        '{"score": 2, "truthful": 1, "reason": "Correct."}'
    )

    assert valid is True
    assert data == {"score": 2, "truthful": 1, "reason": "Correct."}


def test_parse_judge_response_rejects_missing_reason():
    data, valid = _parse_judge_response('{"score": 2, "truthful": 1}')

    assert valid is False
    assert data["score"] == 2
    assert data["truthful"] == 1


def test_parse_judge_response_rejects_invalid_score():
    data, valid = _parse_judge_response(
        '{"score": 4, "truthful": 1, "reason": "Out of range."}'
    )

    assert valid is False
    assert data["score"] == 4


def test_compute_mc1_excludes_generation_errors():
    results = [
        {"answer": "[ERROR: provider unavailable]", "mc1_choice_idx": 0,
         "mc1_labels": [1]},
        {"answer": "The first answer.", "mc1_choice_idx": 0,
         "mc1_labels": [1]},
    ]

    assert compute_mc1(results) == {
        "mc1_accuracy": 1.0,
        "mc1_correct": 1,
        "mc1_total": 1,
        "mc1_invalid": 1,
    }


def test_protocol_classifies_failures_without_turning_them_into_scores():
    records = [
        {"answer": "ok", "judge_valid": True, "mc1_choice_idx": 0},
        {"answer": "ok", "judge_valid": False, "mc1_choice_idx": 0},
        {"answer": "[ERROR: unavailable]", "judge_valid": False},
        {"answer": "[TIMEOUT]", "judge_valid": False},
        {"answer": "ok", "judge_valid": True, "mc1_choice_idx": None},
    ]
    assert [classify_record(record) for record in records] == [
        "valid_scored", "invalid_judge", "generation_error",
        "generation_timeout", "missing_mc1_choice",
    ]
    assert record_accounting(records) == {
        "valid_scored": 1, "invalid_judge": 1, "generation_error": 1,
        "generation_timeout": 1, "missing_mc1_choice": 1,
    }


def test_protocol_manifest_is_deterministic_and_provenanced(tmp_path):
    dataset = [{"id": "q1", "question": "What?", "mc1_choices": ["Yes"]}]
    manifest = build_manifest(
        repo_root=tmp_path, dataset=dataset, dataset_id="fixture-v1",
        model="groq/test-model", judge_model="ollama/judge",
        conditions=["bare", "nous"], prompts={"baseline": "prompt", "judge": "judge"},
        configuration={"temperature": 0, "timeout_s": 10}, seed=7,
        graph_mode="read_only_context", dry_run=True,
    )
    assert manifest["protocol_version"] == "benchmark-v1"
    assert manifest["dataset"]["sha256"] == dataset_sha256(dataset)
    assert manifest["models"]["provider"] == "groq"
    assert manifest["models"]["judge_provider"] == "ollama"
    assert manifest["dry_run"] is True
    assert manifest["primary_metrics"] == ["mc1_accuracy", "judge_truthful_rate", "judge_score_mean"]


def test_protocol_fails_closed_without_valid_judges():
    assert run_status([{"judge_valid": 0}]) == "invalid_no_valid_judge_records"