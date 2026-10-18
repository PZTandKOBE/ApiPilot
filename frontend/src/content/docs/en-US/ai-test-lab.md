## What AI Test Lab does

AI Test Lab takes an OpenAPI spec and runs this flow:

1. Parse the document.
2. Analyze endpoints, parameters, security declarations, and dependencies.
3. Generate a candidate test plan (scenario / step / assertion).
4. Validate the plan and make it reviewable.

The model proposes a plan; validation and eventual execution are deterministic backend responsibilities.

## Workflow

1. Open the project’s AI Test Lab.
2. Paste/import the OpenAPI document.
3. Run analysis.
4. Wait for the task to finish and inspect the understanding/analysis result.
5. Generate a test plan.
6. Review it, then continue to approval.

The UI reports task status, errors, and retryable states. If a task fails, inspect the error rather than repeatedly submitting the same request.

## Models and deterministic mode

DeepSeek can be configured for analysis/planning. For offline demos or no API key, set this before starting the backend:

~~~powershell
$env:AGENT_ANALYZER = 'deterministic'
$env:AGENT_PLANNER = 'deterministic'
~~~

The deterministic path does not call an external model, but its coverage is defined by local rules and is not equivalent to arbitrary model output.

## Security facts

OpenAPI `security` is classified as:

- no security declaration
- explicitly public
- requires authentication
- authentication optional

These facts influence whether the deterministic planner creates an authentication scenario. They do not replace real authorization testing or allow the executor to guess every credential scheme.

## Next

After plan generation, read [Plans and approval](/learn/plans-and-approval).