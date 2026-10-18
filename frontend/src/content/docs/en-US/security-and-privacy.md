## Secrets

- Database passwords, model API keys, and tokens belong in `backend/.env` or deployment secrets.
- Do not commit `.env`, real keys, certificates, or logs containing credentials.
- Documentation and examples use placeholders only.
- The repository ignores `.env`, but still check before committing.

## Identity

ApiPilot currently uses Guest-first identity:

- The frontend authenticates with the `X-Guest-Session` header.
- The backend checks project/resource access through the guest session.
- Registration/login is not implemented; a login screen does not mean a real account system exists.
- Do not forward the guest session to the target API.

## Report redaction

The PDF generator handles:

- URL userinfo and query values
- Authorization / Bearer / Basic
- Cookie / token / password / secret-like values
- JWT and common API key shapes
- variable values (the report shows counts, not values)
- field/header assertion actuals by default; status actual may be shown

Reports use only persisted run detail and do not fabricate request/response bodies or headers.

## Project isolation

Report creation, listing, viewing, and downloading are project-scoped. A report id from another project is not readable and returns 404 rather than revealing existence.

## Data lifecycle

- Run history, events, evidence, and reports follow the database’s retention policy.
- Collections / Request History are still stored in browser localStorage and do not sync across devices.
- Automated deletion/archive is not a product feature; do not rely on automatic cleanup.

## Target API safety

The project API Client sends through the backend HTTP proxy, including SSRF address validation, DNS/IP checks, TLS verification, and size limits. It is not a production WAF and does not guarantee every internal test address is allowed.

## Next

See [Configuration](/learn/configuration) and [FAQ](/learn/faq).