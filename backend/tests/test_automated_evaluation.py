from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from app.automated_evaluation import answer_matches, generate_cases
from app.config import Settings
from app.db import EvidenceChunk, EvidenceSource
from app.groq_evaluation import GroqCompletion
from app.main import create_app


class FakeGroq:
    def complete(self, *, model: str, prompt: str, temperature: float = 0.0) -> GroqCompletion:
        lowered = prompt.lower()
        if "price" in lowered:
            answer = "The AeroFit price is 4999."
        elif "return days" in lowered:
            answer = "The return window is 30 days."
        elif "in stock" in lowered:
            answer = "Yes, it is available."
        else:
            answer = "It is available in Blue."
        return GroqCompletion(answer, model, 25, 10, 8)


def test_exact_matching_handles_numbers_booleans_and_strings() -> None:
    assert answer_matches(3499, "It costs Rs 3,499 today.")
    assert not answer_matches(3499, "It costs Rs 13,499 today.")
    assert answer_matches(False, "No, it is not available.")
    assert answer_matches("Midnight Blue", "The colour is midnight blue.")


def test_json_case_generation_keeps_source_provenance() -> None:
    source = EvidenceSource(
        id="source-1",
        model_id="model-1",
        name="Catalog",
        filename="catalog.json",
        media_type="application/json",
        content_hash="hash",
        corpus_version="evidence-hash",
        status="approved",
        extraction_method="deterministic",
        chunk_count=1,
    )
    source.chunks = [
        EvidenceChunk(
            id="chunk-1",
            source_id="source-1",
            ordinal=0,
            text='{"name":"AeroFit","price":3499}',
            evidence_quote='{"name":"AeroFit","price":3499}',
            locator={"json_path": "$.products[0]"},
            content_hash="chunk-hash",
            validation_status="deterministic",
        )
    ]

    cases = generate_cases([source], max_questions=3, variants=3)

    assert len(cases) == 3
    assert cases[0].question == "What is the price for AeroFit?"
    assert cases[0].expected == "3499"
    assert cases[0].locator == {"json_path": "$.products[0]"}


def test_automated_evaluation_runs_model_and_creates_health_snapshot() -> None:
    app = create_app(Settings(database_url="sqlite://", environment="test", minimum_sample_size=20))
    with TestClient(app) as client:
        app.state.service.groq_client = FakeGroq()
        model = client.post(
            "/api/v1/models",
            json={
                "name": "ShopAssist",
                "provider": "groq",
                "initial_version": {
                    "label": "test",
                    "model_identifier": "fake-model",
                    "prompt_version": "v1",
                },
            },
        ).json()
        content = json.dumps(
            {
                "products": [
                    {
                        "name": "AeroFit",
                        "price": 3499,
                        "return_days": 30,
                        "in_stock": True,
                        "colour": "Black",
                    }
                ]
            }
        ).encode()
        imported = client.post(
            f"/api/v1/models/{model['id']}/evidence-sources/import",
            json={
                "filename": "catalog.json",
                "content_base64": base64.b64encode(content).decode(),
                "actor": "test",
            },
        ).json()
        client.post(
            f"/api/v1/evidence-sources/{imported['id']}/review",
            json={"status": "approved", "actor": "test"},
        )

        response = client.post(
            f"/api/v1/models/{model['id']}/automated-evaluations",
            json={"max_questions": 20, "variants_per_fact": 5, "actor": "test"},
        )

    assert response.status_code == 201
    result = response.json()
    assert result["generated_questions"] == 20
    assert result["passed_questions"] == 10
    assert result["failed_questions"] == 10
    assert result["health_score"] is not None
    assert result["snapshot"]["sample_size"] == 20
    assert all(case["source_name"] == "catalog" for case in result["cases"])
