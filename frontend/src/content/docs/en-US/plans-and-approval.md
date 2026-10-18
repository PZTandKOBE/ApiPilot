## Plan states

| State | Meaning |
|---|---|
| `draft` | Generated but not submitted for review |
| `in_review` | Waiting for a human review |
| `approved` | Approved and eligible for a formal run |
| `rejected` | Rejected |

**An unapproved plan cannot be executed.** A regenerated version starts as a new draft; approval is not inherited.

## Review checklist

In the plan detail, inspect:

- scenario and step order
- HTTP methods and paths
- extracted variables and their source
- assertion targets, expected values, and descriptions
- risk level and version information

Reject a plan that does not match your intent. Do not run an unreviewed plan.

## Regeneration and versions

When a plan already exists, the UI offers explicit regeneration:

- A new id is created (for example `plan_slug_v2`).
- The old plan content is not overwritten.
- Existing runs keep the plan id they originally used.
- The new plan is a `draft` and must be approved again.
- The current version is derived from the highest version number.

Regeneration requires explicit user confirmation. A normal first-time generation still refuses to silently create a duplicate plan.

## Not implemented

- Deleting, archiving, or rolling back plan versions.
- Full graphical editing of scenarios/steps/assertions.
- A standalone visual workflow or branching canvas.

## Next

After approval, continue to [Run tests](/learn/run-tests).