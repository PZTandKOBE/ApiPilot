## Create a project

Open the console Projects page and enter a project name and optional Base URL.

The Base URL is the environment used when a run sends requests. Point it at your own test environment, not an arbitrary external service. ApiPilot applies SSRF protections; whether a local/internal address is allowed depends on deployment configuration.

## Import an OpenAPI spec

Use AI Test Lab inside the project to import or paste an OpenAPI document. JSON is the primary documented path; trust the parsed result shown by the product.

After import, check:

- document title and version
- endpoint count and paths
- declared security/auth requirements
- parameters and response statuses

If parsing fails, check the JSON syntax first, then see [Troubleshooting](/learn/troubleshooting).

## Project boundary

A project scopes most resources:

- Plans, runs, and reports belong to a project.
- Report reads/downloads are project-scoped; cross-project IDs return 404.
- API Client requests go through the backend proxy rather than directly from the browser.

## Next

Use the spec in [AI Test Lab](/learn/ai-test-lab), then review the generated plan in [Plans and approval](/learn/plans-and-approval).