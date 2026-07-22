from pdf_ocr_agent.gemini import _is_retryable


def test_retryable_demand_error() -> None:
    assert _is_retryable(RuntimeError("model is experiencing high demand; try later"))


def test_non_retryable_validation_error() -> None:
    assert not _is_retryable(ValueError("schema is invalid"))
