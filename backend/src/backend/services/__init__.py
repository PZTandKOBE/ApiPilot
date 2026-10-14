"""Business logic.

Empty in Phase 7.1, and deliberately so: routers land first, then the service
that fills them.

Where this sits, and where it does not::

    route      -> resolves path params, calls the service, returns its result
    service    -> owns the transaction and the rules            <-- here
    SQLAlchemy -> ``select()`` / ``session.add()``, written inline

**There is no repository layer.**  A repository earns its keep when two callers
share a query, or when the query needs a policy wrapped around it.  Neither is
true here: the read paths are a handful of ``public_id`` lookups and a couple of
aggregates, each used once, and the models set ``lazy="raise"`` on nearly every
relationship so each query already has to spell out its own loader options.
A layer that only forwards has a cost and no job.

Phase 7.2 adds ``runs.py`` here, which will own:

* the approval re-check (the client's word is not evidence),
* materialising the spec, plan and plan tree that ``test_runs``' NOT NULL
  foreign keys point at,
* fanning the plan out into ``run_scenarios`` / ``run_steps`` / ``run_assertions``,
* the derived ``duration_ms``, ``summary`` and ``last_seq`` values,
* ``constraint_of()`` from ``backend.api.errors`` for the violations that map to
  a 409 rather than a 500.
"""
