## Start a run

An approved plan can be created as a run. The backend executor performs the work; the browser does not send target requests directly.

Follow:

- overall status: `queued`, `running`, `passed`, `failed`, `cancelled`
- scenario and step states
- assertion results
- saved evidence
- run event stream

## Multi-request flows and runtime variables

A run can contain several request steps. The executor supports:

- extracting variables from a response (for example a token or resource id)
- using runtime values in later steps
- runtime values taking precedence over initial environment values within the run
- failing before HTTP when a required variable is missing

The run detail separates **Initial variables** and **Runtime variables**. Runtime values are not written into run history; only names/scope are shown.

## Assertions

The current common assertions are `status`, `header`, and `field`. `schema` assertions are not implemented and are skipped.

A failed assertion marks the run failed, but a target 4xx/5xx is not automatically a platform error; the assertion rules decide pass/fail.

## Cancellation and events

Runs can be cancelled, and the cancellation state is persisted. Events are streamed over SSE and support `Last-Event-ID` resumption.

There is a known recovery gap: the backend has no executor lease/heartbeat for a `running` process, so it cannot always distinguish a live run from a dead one after a restart.

## Next

See [Run history](/learn/run-history), or generate a [PDF report](/learn/pdf-reports) from a terminal run.