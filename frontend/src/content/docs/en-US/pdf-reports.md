## Loop

~~~text
terminal run
  → Generate & save PDF
  → server renders real PDF bytes
  → PDF + metadata saved in PostgreSQL
  → Test Reports list
  → open inline / download / print
~~~

Only `passed`, `failed`, and `cancelled` runs can generate a report. `queued` and `running` are refused.

## Generate

Open a terminal run’s PDF report preview and choose **Generate & save PDF**. After success you can:

- open the saved report immediately;
- go to **Test Reports** in the sidebar;
- refresh the page and read the report list from the server.

The report body comes from the run detail. Generation does not re-call the target API or the AI provider.

## Report center

The center lists saved records for the project, including report name, run ID, run status, generation time, and file size. You can:

- **Open PDF** inline;
- **Download** the file;
- **Print** from the browser PDF viewer.

Opening/downloading requires the guest session and project access.

## Server implementation

- Renderer: `backend/src/backend/services/report_pdf.py`
- Table: `run_reports`
- PDF column: `content` (bytea)
- Migration: `c33a1b2c3d4e_create_run_reports.py`
- API:
  - `POST /api/projects/{project_id}/runs/{run_id}/reports`
  - `GET /api/projects/{project_id}/reports`
  - `GET /api/projects/{project_id}/reports/{report_id}/file`
  - `GET /api/projects/{project_id}/reports/{report_id}/download`

## What is not in the report

Runs do not persist request/response bodies, headers, environment values, or runtime variable values. The report does not invent them. URL query values, Authorization/Cookie/token-like values are redacted; field/header assertion actual values are hidden by default.

See [Security and privacy](/learn/security-and-privacy).