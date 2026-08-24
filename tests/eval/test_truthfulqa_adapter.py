from eval.truthfulqa_adapter import _parse_judge_response


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