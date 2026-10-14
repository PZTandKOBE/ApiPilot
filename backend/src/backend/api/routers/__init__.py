"""HTTP routers.

Kept as a bare docstring on purpose: importing this package must not pull in
the routers, so that ``create_app()`` stays the single place where the URL
surface is assembled and can be read top to bottom in one screen.
"""
