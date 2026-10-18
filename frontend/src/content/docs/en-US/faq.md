## Where is the visual workflow?

Not built. ApiPilot has Scenarios, Steps, and Assertions inside test plans, but no canvas editor, branching orchestration, workflow templates, or a workflow-specific version system. Do not mistake the plan tree for a graphical workflow.

## Can I register or log in?

Not yet. The current phase is Guest-first. Registration, login, and official cloud guest quotas are not implemented; the existing login surface is not a working account system.

## Does generating a PDF rerun tests or call AI?

No. It reads an existing terminal run detail, renders real PDF bytes, and persists them. It does not call the target API or the model provider.

## Does the report include request/response bodies?

No. Runs do not persist those bodies, headers, or variable values. The report does not invent them and redacts secrets it can identify.

## Which assertions exist?

Current common assertions are `status`, `header`, and `field`. `schema` assertions are not implemented and are skipped.

## Why can’t I run my plan?

Only an approved plan can create a formal run. Approve it in the plan detail, and check whether a regenerated version is still a `draft`.

## Why do old plans remain?

Regeneration adds a new version instead of overwriting the old plan or changing historical runs. The current version is derived from the highest version. Deleting/rolling back versions is not implemented.

## Is YAML OpenAPI supported?

The documented product path primarily assumes JSON OpenAPI. Do not assume every YAML feature is supported; trust the actual parse result.

## Is it production-ready?

No. ApiPilot is Alpha and still needs fuller run recovery, CI/CD, and broader security validation.

## Back to the start

- [Overview](/learn/overview)
- [Quickstart](/learn/quickstart)
- [Security and privacy](/learn/security-and-privacy)