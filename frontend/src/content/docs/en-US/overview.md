ApiPilot is an AI-assisted API testing platform. It brings OpenAPI understanding, test-plan generation and approval, deterministic backend execution, run inspection, and PDF reports into one workspace.

> ApiPilot is still in Early Development / Alpha. Automated tests and the main workflows exist, but treat it as an evolving tool, not a production testing service.

## What it is for

- Reading an OpenAPI document and understanding endpoints, parameters, security facts, and dependencies.
- Generating a reviewable candidate test plan with an AI model.
- Executing approved plans through a deterministic backend executor, including multi-request flows, runtime variables, and assertions.
- Turning a terminal run into a real, persisted PDF report.

## Try Us and Learn Us

**Try Us** opens the product console: projects, API client, AI Test Lab, plans, runs, and reports.

**Learn Us** is this documentation portal. It explains setup and product behavior. It does not create runs or share route state with the console.

## Implemented today

- Guest-session projects, secure API client, and OpenAPI analysis.
- AI test-plan generation, approval/rejection, and versioned regeneration.
- Multi-request runs, runtime variable extraction, common assertions, SSE events, cancellation, and history.
- Server-side PDF generation for terminal runs, database persistence, and a report center with view/download/print.

## Not implemented today

- A standalone visual workflow module: no canvas, branching editor, or workflow templates.
- Registration/login or cloud quotas.
- Complete persistence of request/response bodies, headers, or variable values.
- Docker or CI/CD deployment automation.

## Next

- First run: [Quickstart](/learn/quickstart).
- Local deployment: [Self-hosting](/learn/self-hosting).
- Report details: [PDF reports](/learn/pdf-reports).