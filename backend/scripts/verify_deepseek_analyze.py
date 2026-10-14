"""Optional live smoke test for the analyze stage (Phase 8.3 Step 1).

    DEEPSEEK_API_KEY=... python scripts/verify_deepseek_analyze.py

**Not part of any suite.**  It is skipped, with exit code 0, when there is no
key, so a checkout without credentials can still run everything else.  When a key
is present it makes exactly one real call and reports:

* PASS or FAIL,
* which model answered,
* the shape of the answer (counts per section, and the field names it used),
* the validation verdict from the two layers this pipeline applies.

It never prints the prompt, never prints the answer, and never writes the key
anywhere.  The details it does print are the same ones the server logs.

The document is built in, so this needs no database and no project: it is a test
of the model and of the validation around it, and nothing else.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:  # installed package (uv_build src-layout); fall back for a bare checkout
    import backend  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on how it is invoked
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backend.services import agent_analyzer, agent_plan  # noqa: E402
from backend.services.agent_plan import PlanPipelineError  # noqa: E402
from backend.services.llm import LLMError  # noqa: E402

__all__ = ["main"]

DOCUMENT: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {
        "title": "Smoke Shop API",
        "version": "1.0.0",
        "description": "A small shop. Buy things.",
    },
    "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}},
    "security": [{"bearerAuth": []}],
    "paths": {
        "/auth/login": {
            "post": {
                "tags": ["auth"],
                "summary": "Exchange credentials for a token",
                "security": [],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"token": {"type": "string"}},
                                }
                            }
                        },
                    }
                },
            }
        },
        "/products": {
            "get": {
                "tags": ["catalogue"],
                "summary": "List products",
                "responses": {"200": {"description": "ok"}},
            }
        },
        "/orders/{orderId}": {
            "get": {
                "tags": ["orders"],
                "summary": "Read one order",
                "responses": {"200": {"description": "ok"}},
            }
        },
    },
}

TASK = "Understand this shop API well enough to test its order flow."


def shape_of(understanding: agent_plan.Understanding) -> dict[str, Any]:
    """The answer's shape, never its content: counts and the field names used."""
    return {
        "endpoints": len(understanding.endpoints),
        "resources": len(understanding.resources),
        "dependencies": len(understanding.dependencies),
        "risks": len(understanding.risks),
        "findings": len(understanding.findings),
        "dependencyKinds": sorted({d.kind for d in understanding.dependencies}),
        "riskLevels": sorted({r.level for r in understanding.risks}),
        "riskCategories": sorted({r.category for r in understanding.risks}),
        "findingResults": sorted({f.result for f in understanding.findings}),
    }


async def main() -> int:
    if not (os.getenv("DEEPSEEK_API_KEY") or "").strip():
        print("SKIPPED  DEEPSEEK_API_KEY is not set; no live call was made.")
        print("         The stubbed pipeline suite is scripts/verify_agent_analyze.py.")

        return 0

    model = (os.getenv("DEEPSEEK_MODEL") or "").strip() or "deepseek-flash"
    base = (os.getenv("DEEPSEEK_BASE_URL") or "").strip() or "https://api.deepseek.com"
    prompt = agent_analyzer.load_prompt()

    parsed = agent_plan.parse_document(
        agent_plan.decode_document(json.dumps(DOCUMENT)),
        project_id="prj_smoke",
        spec_id="spec_smoke",
        slug="smoke",
        filename="smoke.json",
        source="upload",
    )

    print("live analyze smoke test")
    print(f"  base url      {base}")
    print(f"  model         {model}")
    print(f"  prompt        {prompt.name} v{prompt.version} ({len(prompt.text)} chars)")
    print(f"  document      {len(parsed.endpoints)} endpoints")

    started = time.monotonic()

    try:
        # The real path: the real client, the real prompt, both validators.
        understanding = (
            await agent_analyzer.analyze_with_model(
                parsed, task=TASK, document=DOCUMENT
            )
        ).understanding
    except PlanPipelineError as refusal:
        print(f"\nFAIL  the answer was refused: {refusal.detail}")
        print(f"      after {time.monotonic() - started:.1f}s")

        return 1
    except LLMError as error:  # pragma: no cover - analyze_with_model wraps these
        print(f"\nFAIL  the call failed: {error.detail}")

        return 1

    elapsed = time.monotonic() - started

    print("\nPASS  one call, structured answer, both validation layers passed")
    print(f"  elapsed       {elapsed:.1f}s")
    print("  shape         " + json.dumps(shape_of(understanding), sort_keys=True))
    print("  validation    schema (pydantic, extra=forbid) + domain (ids, categories, evidence)")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
