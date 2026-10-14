"""HTTP layer: dependencies, error handling and routers.

No business logic lives in this package.  A route resolves its path parameters,
calls a service, and returns what the service produced; a service owns the
transaction and the rules.  Where the two meet is ``backend/services/``.
"""
