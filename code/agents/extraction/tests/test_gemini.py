from pdf_ocr_agent.gemini import (
    _is_retryable,
    _merge_enrichment,
    _needs_candidate_recovery,
    _needs_context_enrichment,
)
from pdf_ocr_agent.models import (
    ChunkExtraction,
    PageObservation,
    Prerequisite,
    SourceAnchor,
    TheoremCandidate,
)


def test_retryable_demand_error() -> None:
    assert _is_retryable(RuntimeError("model is experiencing high demand; try later"))


def test_non_retryable_validation_error() -> None:
    assert not _is_retryable(ValueError("schema is invalid"))


def test_candidate_recovery_only_when_labels_exist() -> None:
    labeled = ChunkExtraction(
        chunk_summary="test",
        pages=[
            PageObservation(
                page_number=1,
                transcription="0.1 Theorem. A.",
                detected_labels=["0.1 Theorem"],
                confidence=1,
            )
        ],
    )
    assert _needs_candidate_recovery(labeled)
    assert not _needs_candidate_recovery(ChunkExtraction(chunk_summary="blank"))


def _candidate() -> TheoremCandidate:
    return TheoremCandidate(
        local_id="t1",
        kind="theorem",
        original_text="A implies A.",
        normalized_statement="A implies A.",
        conclusion="A implies A",
        source_anchor=SourceAnchor(page_start=1, page_end=1),
        confidence=0.9,
    )


def test_enrichment_preserves_locked_statement() -> None:
    original = _candidate()
    changed = original.model_copy(
        update={
            "original_text": "Changed text",
            "prerequisites": [
                Prerequisite(
                    label="Definition A",
                    kind="definition",
                    statement="A is a proposition.",
                    relation="Defines A",
                    source_status="quoted",
                    source_page=1,
                    confidence=1,
                )
            ],
        }
    )
    merged = _merge_enrichment([original], [changed])[0]
    assert merged.original_text == "A implies A."
    assert merged.prerequisites[0].label == "Definition A"
    chunk = ChunkExtraction(
        chunk_summary="test",
        pages=[PageObservation(page_number=1, transcription="A", confidence=1)],
        candidates=[original],
    )
    assert _needs_context_enrichment(chunk)
