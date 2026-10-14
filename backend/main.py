"""Entry point.

The app is assembled in ``backend/app.py``; this module is the thing uvicorn and
``uv run backend`` point at.  The two routes below predate the API and are kept
as they were -- they are the fastest way to check the process is up, and moving
them into a router would change their paths for no gain.
"""

from backend.app import create_app

app = create_app()


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}
