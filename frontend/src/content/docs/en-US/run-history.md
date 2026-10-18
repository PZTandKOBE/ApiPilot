## Run list

The project Runs page lists historical runs. A detail page shows:

- status and the actual `planId`
- created/started/finished times and duration
- scenario, step, and assertion states
- failure information and saved evidence
- variable count and Initial/Runtime variables
- report entry

## Debugging a failure

Suggested order:

1. Read the run status and failure summary.
2. Find the first failed step, not only the last assertion.
3. Check the HTTP method/path, response status, and expected assertion.
4. Check whether dependencies were extracted successfully.
5. Inspect saved evidence; request/response bodies and headers are not normally persisted.

Run history is not a full network capture. ApiPilot only shows data that was actually persisted.

## Reports

A `passed`, `failed`, or `cancelled` run can produce a PDF. Generating a report does not re-execute the run; it reads the saved run detail.

See [PDF reports](/learn/pdf-reports).