"""Optional live smoke test for the plan stage (Phase 8.3 Step 2).

    DEEPSEEK_API_KEY=... python scripts/verify_deepseek_generate_plan.py

**Not part of any suite.**  It is skipped, with exit code 0, when there is no
key, so a checkout without credentials can still run everything else.

It makes exactly **one** model call.  The understanding comes from the
deterministic analyzer, locally, so the call it pays for is the one under test:
does DeepSeek design a plan that the frozen contract accepts?

It reports PASS or FAIL, the model, the elapsed time, the shape of the plan, the
kinds it uses, the validator's verdict and the token usage.  It never prints the
prompt, never prints the answer, and never writes the key anywhere.  Persistence
is not exercised here (that needs a database); the stubbed pipeline suite covers
it end to end.

    python scripts/verify_deepseek_generate_plan.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

try:  # installed package (uv_build src-layout); fall back for a bare checkout
    import backend  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on how it is invoked
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("AGENT_ANALYZER", "deterministic")
"""The understanding is computed here, by the rules: one API call, the one under
test."""

from backend.schemas.run import PlanPayload  # noqa: E402
from backend.services import agent_analyzer, agent_plan  # noqa: E402
from backend.services.agent_plan import PlanInvalid, PlanPipelineError  # noqa: E402
from backend.services.llm import (  # noqa: E402
    LLMError,
    LLMResult,
    DeepSeekLLMClient,
    deepseek_config,
)

__all__ = ["main"]

PROJECT_PUBLIC_ID = "prj_smoke_plan"
TASK = "Design a test plan for the shop's order flow, and cover the token."


class RecordingClient:
    """The real client, with its answer's metadata kept for the report.

    It implements the client protocol and delegates every call, so the request on
    the wire is the production one; it simply remembers what came back, because
    the report needs the usage numbers and the pipeline has no reason to return
    them.
    """

    def __init__(self, inner: DeepSeekLLMClient) -> None:
        self._inner = inner
        self.usage: Mapping[str, Any] | None = None
        self.request_id: str | None = None

    @property
    def model(self) -> str:
        return self._inner.model

    async def complete_json(
        self,
        *,
        instructions: str,
        turns: Sequence[str],
        schema: Mapping[str, Any],
        schema_name: str,
    ) -> LLMResult:
        result = await self._inner.complete_json(
            instructions=instructions, turns=turns, schema=schema, schema_name=schema_name
        )
        self.usage = result.usage
        self.request_id = result.request_id

        return result


def shape_of(plan: PlanPayload) -> dict[str, Any]:
    """The plan's shape, never its prose: keys, kinds and counts."""
    return {
        "scenarios": len(plan.scenarios),
        "steps": sum(len(scenario.steps) for scenario in plan.scenarios),
        "assertions": sum(len(scenario.assertions) for scenario in plan.scenarios),
        "scenarioKeys": [scenario.id for scenario in plan.scenarios],
        "stepKinds": sorted(
            {step.kind for scenario in plan.scenarios for step in scenario.steps}
        ),
        "assertionKinds": sorted(
            {assertion.kind for scenario in plan.scenarios for assertion in scenario.assertions}
        ),
        "riskLevel": plan.risk_level,
        "status": plan.status,
    }


def smoke_document() -> tuple[Mapping[str, Any], str]:
    """The document and task the analyze smoke uses, so both test the same API."""
    spec = importlib.util.spec_from_file_location(
        "verify_deepseek_analyze", Path(__file__).with_name("verify_deepseek_analyze.py")
    )
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    return module.DOCUMENT, module.TASK


async def main() -> int:
    if not (os.getenv("DEEPSEEK_API_KEY") or "").strip():
        print("SKIPPED  DEEPSEEK_API_KEY is not set; no live call was made.")
        print("         The stubbed pipeline suite is scripts/verify_agent_generate_plan.py.")

        return 0

    model = (os.getenv("DEEPSEEK_MODEL") or "").strip() or "deepseek-flash"
    base = (os.getenv("DEEPSEEK_BASE_URL") or "").strip() or "https://api.deepseek.com"
    prompt = agent_analyzer.load_prompt(agent_analyzer.PLAN_PROMPT_NAME)
    document, task = smoke_document()

    parsed = agent_plan.parse_document(
        agent_plan.decode_document(json.dumps(document)),
        project_id=PROJECT_PUBLIC_ID,
        spec_id="spec_smoke_plan",
        slug="smoke_plan",
        filename="smoke-plan.json",
        source="upload",
    )

    # One API call, and it is the plan's: the understanding is the rule engine's.
    understanding = agent_plan.analyze(parsed)
    client = RecordingClient(DeepSeekLLMClient(deepseek_config()))

    print("live plan smoke test")
    print(f"  base url      {base}")
    print(f"  model         {model}")
    print(f"  prompt        {prompt.name} v{prompt.version} ({len(prompt.text)} chars)")
    print(f"  document      {len(parsed.endpoints)} endpoints")
    print(f"  understanding {len(understanding.risks)} risks, "
          f"{len(understanding.dependencies)} dependencies (deterministic, local)")

    started = time.monotonic()

    try:
        plan = (
            await agent_analyzer.plan_with_model(
                parsed, understanding, task=task, client=client
            )
        ).plan
    except PlanPipelineError as refusal:
        print(f"\nFAIL  the design was refused: {refusal.detail}")
        print(f"      after {time.monotonic() - started:.1f}s")

        return 1
    except LLMError as error:  # pragma: no cover - plan_with_model wraps these
        print(f"\nFAIL  the call failed: {error.detail}")

        return 1

    elapsed = time.monotonic() - started

    try:
        agent_plan.validate_plan(
            plan,
            project_id=parsed.spec.project_id,
            spec_id=parsed.spec.id,
            expected_plan_id=f"plan_{parsed.spec.slug}",
        )
        verdict = "PASS (contract rules: keys, indices, targets, variable provenance)"
    except PlanInvalid as invalid:
        print(f"\nFAIL  the plan was refused by the validator: {invalid.detail}")
        print(f"      after {elapsed:.1f}s")

        return 1

    usage = dict(client.usage or {})

    print("\nPASS  one call, strict structured design, contract validation passed")
    print(f"  elapsed       {elapsed:.1f}s")
    print("  shape         " + json.dumps(shape_of(plan), sort_keys=True))
    print(f"  validation    {verdict}")
    print(
        "  usage         input_tokens={0} output_tokens={1} total_tokens={2}".format(
            usage.get("input_tokens"),
            usage.get("output_tokens"),
            usage.get("total_tokens"),
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
