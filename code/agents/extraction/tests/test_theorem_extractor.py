from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from theorem_extractor.client import ExtractionResponse, GPT55Client, ProviderMetadata
from theorem_extractor.models import (
    ContextItem,
    ContextRelation,
    OmissionReason,
    ProofOmission,
    ProofStatus,
    ProofStep,
    ProofStepRole,
    ResultKind,
    TheoremCandidate,
    TheoremExtractionBatch,
)
from theorem_extractor.pipeline import TheoremExtractionPipeline, _theorem_id


def _complete_candidate() -> TheoremCandidate:
    return TheoremCandidate(
        source_pages=[10],
        kind=ResultKind.PROPOSITION,
        label_verbatim="Proposition 1.1.",
        title_verbatim="",
        statement_verbatim="Proposition 1.1. If $n$ is an integer, then $n=n$.",
        proof_status=ProofStatus.COMPLETE,
        proof_verbatim="Proof. Reflexivity gives $n=n$. This proves the claim. ∎",
        proof_steps=[
            ProofStep(
                order=1,
                role=ProofStepRole.INFERENCE,
                text_verbatim="Proof. Reflexivity gives $n=n$.",
                source_pages=[10],
            ),
            ProofStep(
                order=2,
                role=ProofStepRole.CONCLUSION,
                text_verbatim="This proves the claim. ∎",
                source_pages=[10],
            ),
        ],
        omission=ProofOmission(
            is_omitted=False,
            reason=OmissionReason.NONE,
            marker_verbatim="",
            note="",
        ),
        context_items=[
            ContextItem(
                relation=ContextRelation.LOCAL_DEFINITION,
                label_verbatim="Integer convention.",
                text_verbatim="Integer convention. Throughout, $n\\in\\mathbb Z$.",
                source_pages=[10],
                relevance="Fixes the domain of n.",
            )
        ],
        uncertainties=[],
        confidence=1,
        record_complete_in_chunk=True,
        boundary_note="",
    )


def _omitted_candidate() -> TheoremCandidate:
    return TheoremCandidate(
        source_pages=[11],
        kind=ResultKind.COROLLARY,
        label_verbatim="Corollary 1.2.",
        title_verbatim="",
        statement_verbatim="Corollary 1.2. Every integer equals itself.",
        proof_status=ProofStatus.OMITTED,
        proof_verbatim="",
        proof_steps=[],
        omission=ProofOmission(
            is_omitted=True,
            reason=OmissionReason.NO_PROOF_PRESENT,
            marker_verbatim="",
            note="No proof text occurs before the next section.",
        ),
        context_items=[],
        uncertainties=[],
        confidence=0.99,
        record_complete_in_chunk=True,
        boundary_note="",
    )


def _markdown(path: Path) -> Path:
    path.write_text(
        """---
type: ocr-chunk
document_id: sample-book
---

<!-- pdf-page: 10 -->

## PDF page 10

Integer convention. Throughout, $n\\in\\mathbb Z$.

Proposition 1.1. If $n$ is an integer, then $n=n$.

Proof. Reflexivity gives $n=n$. This proves the claim. ∎

<!-- pdf-page: 11 -->

## PDF page 11

Corollary 1.2. Every integer equals itself.

# Next section
""",
        encoding="utf-8",
    )
    return path


class FakeExtractor:
    model_name = "GPT-5.5"
    deployment_label = "east-US-2-gpt-5.5"

    def __init__(self, candidates: list[TheoremCandidate]) -> None:
        self._candidates = candidates

    def extract(
        self,
        *,
        document_id: str,
        chunk_name: str,
        markdown: str,
    ) -> ExtractionResponse:
        return ExtractionResponse(
            batch=TheoremExtractionBatch(candidates=self._candidates),
            metadata=ProviderMetadata(
                request_id="request-test",
                requested_model=self.model_name,
                resolved_model="gpt-5.5-test",
                deployment=self.deployment_label,
                finish_reason="stop",
                usage={"total_tokens": 100},
            ),
        )


def test_pipeline_writes_complete_and_omitted_proof_records(tmp_path: Path) -> None:
    markdown = _markdown(tmp_path / "chunk.md")
    result = TheoremExtractionPipeline(
        FakeExtractor([_complete_candidate(), _omitted_candidate()])
    ).run([markdown], tmp_path / "pipeline")

    assert result.document_id == "sample-book"
    assert result.status_counts == {"complete": 1, "omitted": 1}
    assert len(result.theorem_ids) == 2

    complete_id = result.theorem_ids[0]
    theorem_path = (
        tmp_path
        / "pipeline"
        / complete_id
        / "extraction"
        / "attempt-001"
        / "theorem.json"
    )
    payload = json.loads(theorem_path.read_text(encoding="utf-8"))
    assert payload["result"]["statement_verbatim"].endswith("$n=n$.")
    assert payload["result"]["proof_steps"][1]["role"] == "conclusion"
    assert payload["provider"]["deployment"] == "east-US-2-gpt-5.5"

    omitted_id = result.theorem_ids[1]
    omitted = json.loads(
        (
            tmp_path
            / "pipeline"
            / omitted_id
            / "extraction"
            / "attempt-001"
            / "theorem.json"
        ).read_text(encoding="utf-8")
    )
    assert omitted["result"]["proof_status"] == "omitted"
    assert omitted["result"]["omission"]["is_omitted"] is True


def test_numbered_theorem_id_is_stable_across_label_title_variants() -> None:
    candidate = _complete_candidate().model_copy(
        update={
            "label_verbatim": "0.15",
            "statement_verbatim": "0.15 A statement.",
            "source_pages": [22],
        }
    )
    titled = candidate.model_copy(
        update={
            "label_verbatim": "0.15 The Principle of Transfinite Induction.",
            "statement_verbatim": "0.15 The Principle of Transfinite Induction. A statement.",
        }
    )
    assert _theorem_id("book", candidate) == _theorem_id("book", titled)
    assert _theorem_id("book", candidate) == "book-p00022-0-15"


def test_pipeline_rejects_non_verbatim_proof(tmp_path: Path) -> None:
    candidate = _complete_candidate().model_copy(
        update={
            "proof_verbatim": (
                "Proof. Reflexivity gives $n=n$. This proves the claim using a hidden lemma. ∎"
            ),
            "proof_steps": [
                ProofStep(
                    order=1,
                    role=ProofStepRole.INFERENCE,
                    text_verbatim=(
                        "Proof. Reflexivity gives $n=n$. "
                        "This proves the claim using a hidden lemma. ∎"
                    ),
                    source_pages=[10],
                )
            ],
        }
    )
    with pytest.raises(ValueError, match="proof_verbatim"):
        TheoremExtractionPipeline(FakeExtractor([candidate])).run(
            [_markdown(tmp_path / "chunk.md")],
            tmp_path / "pipeline",
        )


def test_chunk_validation_is_atomic_before_theorem_writes(tmp_path: Path) -> None:
    invalid = _complete_candidate().model_copy(
        update={
            "source_pages": [11],
            "label_verbatim": "Corollary 1.2.",
            "statement_verbatim": "Corollary 1.2. Every integer equals itself.",
            "proof_verbatim": "Proof. This sentence is not in the source. ∎",
            "proof_steps": [
                ProofStep(
                    order=1,
                    role=ProofStepRole.OTHER,
                    text_verbatim="Proof. This sentence is not in the source. ∎",
                    source_pages=[11],
                )
            ],
            "context_items": [],
        }
    )
    output = tmp_path / "pipeline"
    with pytest.raises(ValueError, match="proof_verbatim"):
        TheoremExtractionPipeline(
            FakeExtractor([_complete_candidate(), invalid])
        ).run(
            [_markdown(tmp_path / "chunk.md")],
            output,
        )
    assert [
        path.name for path in output.iterdir() if path.is_dir() and path.name != "_runs"
    ] == []


def test_pipeline_records_ungrounded_boundary_candidate(tmp_path: Path) -> None:
    candidate = _omitted_candidate().model_copy(
        update={
            "label_verbatim": "unknown boundary-continuation result",
            "statement_verbatim": "A fabricated boundary statement.",
            "record_complete_in_chunk": False,
            "boundary_note": "The beginning is outside this chunk.",
        }
    )
    result = TheoremExtractionPipeline(FakeExtractor([candidate])).run(
        [_markdown(tmp_path / "chunk.md")],
        tmp_path / "pipeline",
    )
    assert result.theorem_ids == ()
    assert result.rejected_candidate_count == 1
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["chunks"][0]["rejected_candidates"] == [
        {
            "label": "unknown boundary-continuation result",
            "reason": "label_not_grounded_in_source",
        }
    ]


def test_pipeline_rejects_worked_example_candidate(tmp_path: Path) -> None:
    candidate = _complete_candidate().model_copy(
        update={
            "label_verbatim": "例 8.44",
            "statement_verbatim": "例 8.44 求一个示例。",
        }
    )
    result = TheoremExtractionPipeline(FakeExtractor([candidate])).run(
        [_markdown(tmp_path / "chunk.md")],
        tmp_path / "pipeline",
    )
    assert result.theorem_ids == ()
    assert result.rejected_candidate_count == 1
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["chunks"][0]["rejected_candidates"] == [
        {
            "label": "例 8.44",
            "reason": "worked_example_not_theorem_like",
        }
    ]


def test_pipeline_rejects_bad_overlap_variant_when_valid_record_exists(
    tmp_path: Path,
) -> None:
    markdown = _markdown(tmp_path / "chunk.md")
    output = tmp_path / "pipeline"
    first = TheoremExtractionPipeline(FakeExtractor([_complete_candidate()])).run(
        [markdown],
        output,
    )
    invalid_overlap = _complete_candidate().model_copy(
        update={
            "statement_verbatim": (
                "Proposition 1.1. If $n$ is an integer, then a different claim holds."
            )
        }
    )
    second = TheoremExtractionPipeline(FakeExtractor([invalid_overlap])).run(
        [markdown],
        output,
    )
    assert len(first.theorem_ids) == 1
    assert second.theorem_ids == ()
    assert second.rejected_candidate_count == 1
    manifest = json.loads((second.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["chunks"][0]["rejected_candidates"] == [
        {
            "label": "Proposition 1.1.",
            "reason": "overlap_candidate_not_grounded_existing_record",
        }
    ]


def test_pipeline_rejects_ungrounded_non_numbered_named_property(
    tmp_path: Path,
) -> None:
    candidate = _omitted_candidate().model_copy(
        update={
            "kind": ResultKind.IDENTITY,
            "label_verbatim": "Integer convention.",
            "statement_verbatim": "Integer convention. This wording was inferred.",
        }
    )
    result = TheoremExtractionPipeline(FakeExtractor([candidate])).run(
        [_markdown(tmp_path / "chunk.md")],
        tmp_path / "pipeline",
    )
    assert result.theorem_ids == ()
    assert result.rejected_candidate_count == 1
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["chunks"][0]["rejected_candidates"] == [
        {
            "label": "Integer convention.",
            "reason": "non_numbered_candidate_not_grounded",
        }
    ]


def test_pipeline_ignores_running_headers_inside_cross_page_proof(
    tmp_path: Path,
) -> None:
    markdown = tmp_path / "cross-page.md"
    markdown.write_text(
        """---
document_id: sample-book
---
<!-- pdf-page: 10 -->
## PDF page 10
8 PROLOGUE
Proposition 2.1. A complete statement.
Proof. First sentence.
<!-- pdf-page: 11 -->
## PDF page 11
**12 $\\quad$ PROLOGUE**
**16** PROLOGUE
Second sentence. ∎
""",
        encoding="utf-8",
    )
    candidate = _complete_candidate().model_copy(
        update={
            "source_pages": [10, 11],
            "label_verbatim": "Proposition 2.1.",
            "statement_verbatim": "Proposition 2.1. A complete statement.",
            "proof_verbatim": "Proof. First sentence. Second sentence. ∎",
            "proof_steps": [
                ProofStep(
                    order=1,
                    role=ProofStepRole.OTHER,
                    text_verbatim="Proof. First sentence. Second sentence. ∎",
                    source_pages=[10, 11],
                )
            ],
            "context_items": [],
        }
    )
    result = TheoremExtractionPipeline(FakeExtractor([candidate])).run(
        [markdown],
        tmp_path / "pipeline",
    )
    assert result.status_counts == {"complete": 1}


def test_pipeline_ignores_chinese_running_headers_inside_cross_page_statement(
    tmp_path: Path,
) -> None:
    markdown = tmp_path / "cross-page-chinese.md"
    markdown.write_text(
        """---
document_id: sample-book
---
<!-- pdf-page: 63 -->
## PDF page 63
定义 8.1 设 $D$ 是非空集，则称 $f$ 是定义在 $D$ 上的函数。$P$ 称为
<!-- pdf-page: 64 -->
## PDF page 64
58 | 第 8 章 多元函数的微分学
函数的自变量。
<!-- pdf-page: 65 -->
## PDF page 65
8.2 多元函数的极限与连续 | 59
下一节正文。
""",
        encoding="utf-8",
    )
    candidate = _omitted_candidate().model_copy(
        update={
            "source_pages": [63, 64],
            "kind": ResultKind.DEFINITION,
            "label_verbatim": "定义 8.1",
            "statement_verbatim": (
                "定义 8.1 设 $D$ 是非空集，则称 $f$ 是定义在 $D$ 上的函数。"
                "$P$ 称为 函数的自变量。"
            ),
            "proof_status": ProofStatus.NOT_APPLICABLE,
            "omission": ProofOmission(
                is_omitted=False,
                reason=OmissionReason.NONE,
                marker_verbatim="",
                note="",
            ),
        }
    )
    result = TheoremExtractionPipeline(FakeExtractor([candidate])).run(
        [markdown],
        tmp_path / "pipeline",
    )
    assert result.status_counts == {"not_applicable": 1}


def test_pipeline_ignores_generated_ocr_warnings_inside_source_proof(
    tmp_path: Path,
) -> None:
    markdown = tmp_path / "proof-with-ocr-warning.md"
    markdown.write_text(
        """---
document_id: sample-book
---
<!-- pdf-page: 77 -->
## PDF page 77
定理 8.3 若两个偏导数连续，则函数可微。
证 先应用中值定理。
*(注：原文中此处有轻微印刷不清，按标准格式处理)*
> OCR warning: Potential OCR ambiguity in the formula
---
<!-- pdf-page: 78 -->
## PDF page 78
---|---
因此函数可微。∎
""",
        encoding="utf-8",
    )
    candidate = _complete_candidate().model_copy(
        update={
            "source_pages": [77, 78],
            "label_verbatim": "定理 8.3",
            "statement_verbatim": "定理 8.3 若两个偏导数连续，则函数可微。",
            "proof_verbatim": "证 先应用中值定理。 因此函数可微。∎",
            "proof_steps": [
                ProofStep(
                    order=1,
                    role=ProofStepRole.OTHER,
                    text_verbatim="证 先应用中值定理。 因此函数可微。∎",
                    source_pages=[77, 78],
                )
            ],
            "context_items": [],
        }
    )
    result = TheoremExtractionPipeline(FakeExtractor([candidate])).run(
        [markdown],
        tmp_path / "pipeline",
    )
    assert result.status_counts == {"complete": 1}


def test_pipeline_normalizes_bold_label_after_unclosed_ocr_math(
    tmp_path: Path,
) -> None:
    markdown = tmp_path / "unclosed-math-before-result.md"
    markdown.write_text(
        """---
document_id: sample-book
---
<!-- pdf-page: 10 -->
## PDF page 10
Damaged earlier OCR: $$x = 1
**Proposition 1.1.** If $n$ is an integer, then $n=n$.
Proof. Reflexivity gives $n=n$. This proves the claim. ∎
""",
        encoding="utf-8",
    )
    result = TheoremExtractionPipeline(
        FakeExtractor([_complete_candidate()])
    ).run([markdown], tmp_path / "pipeline")
    assert result.status_counts == {"complete": 1}


def test_pipeline_clears_inferred_title_not_printed_in_statement(
    tmp_path: Path,
) -> None:
    candidate = _complete_candidate().model_copy(
        update={"title_verbatim": "Reflexivity theorem"}
    )
    output = tmp_path / "pipeline"
    result = TheoremExtractionPipeline(FakeExtractor([candidate])).run(
        [_markdown(tmp_path / "chunk.md")],
        output,
    )
    payload = json.loads(
        (
            output
            / result.theorem_ids[0]
            / "extraction"
            / "attempt-001"
            / "theorem.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["result"]["title_verbatim"] == ""
    assert "cleared the optional title field" in payload["result"]["uncertainties"][-1]


def test_pipeline_removes_ungrounded_optional_context_item(
    tmp_path: Path,
) -> None:
    invalid_context = ContextItem(
        relation=ContextRelation.OTHER,
        label_verbatim="Invented context",
        text_verbatim="This context sentence was not printed.",
        source_pages=[10],
        relevance="Would have supplied extra background.",
    )
    candidate = _complete_candidate().model_copy(
        update={
            "context_items": [
                *_complete_candidate().context_items,
                invalid_context,
            ]
        }
    )
    output = tmp_path / "pipeline"
    result = TheoremExtractionPipeline(FakeExtractor([candidate])).run(
        [_markdown(tmp_path / "chunk.md")],
        output,
    )
    payload = json.loads(
        (
            output
            / result.theorem_ids[0]
            / "extraction"
            / "attempt-001"
            / "theorem.json"
        ).read_text(encoding="utf-8")
    )
    assert len(payload["result"]["context_items"]) == 1
    assert "removed 1 optional context item" in payload["result"]["uncertainties"][-1]


def test_pipeline_collapses_incomplete_step_coverage_to_verbatim_step(
    tmp_path: Path,
) -> None:
    candidate = _complete_candidate().model_copy(
        update={
            "proof_steps": [
                ProofStep(
                    order=1,
                    role=ProofStepRole.INFERENCE,
                    text_verbatim="Proof. Reflexivity gives $n=n$.",
                    source_pages=[10],
                )
            ]
        }
    )
    output = tmp_path / "pipeline"
    result = TheoremExtractionPipeline(FakeExtractor([candidate])).run(
        [_markdown(tmp_path / "chunk.md")],
        output,
    )
    payload = json.loads(
        (
            output
            / result.theorem_ids[0]
            / "extraction"
            / "attempt-001"
            / "theorem.json"
        ).read_text(encoding="utf-8")
    )
    assert len(payload["result"]["proof_steps"]) == 1
    assert (
        payload["result"]["proof_steps"][0]["text_verbatim"]
        == payload["result"]["proof_verbatim"]
    )
    assert "exhaustive verbatim evidence step" in payload["result"]["uncertainties"][-1]


def test_client_uses_bearer_chat_completions_and_strict_schema() -> None:
    candidate = _complete_candidate()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-secret"
        body = json.loads(request.content)
        assert body["model"] == "GPT-5.5"
        assert body["reasoning_effort"] == "medium"
        assert "max_tokens" not in body
        assert body["max_completion_tokens"] == 4096
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(
            200,
            json={
                "id": "request-123",
                "model": "gpt-5.5-2026-04-24",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": TheoremExtractionBatch(
                                candidates=[candidate]
                            ).model_dump_json(),
                        },
                    }
                ],
                "usage": {"total_tokens": 200},
            },
        )

    with GPT55Client(
        api_key="test-secret",
        endpoint="https://example.test/api/v1/start",
        max_completion_tokens=4096,
        max_attempts=1,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = client.extract(
            document_id="sample",
            chunk_name="chunk.md",
            markdown="<!-- pdf-page: 10 --> Proposition 1.1.",
        )
    assert response.metadata.request_id == "request-123"
    assert response.metadata.resolved_model == "gpt-5.5-2026-04-24"
    assert response.batch.candidates[0].proof_status == ProofStatus.COMPLETE
