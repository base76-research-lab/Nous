from eval.truthfulqa_adapter import _parse_judge_response, compute_mc1


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