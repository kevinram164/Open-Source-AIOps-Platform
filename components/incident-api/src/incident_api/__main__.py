"""Module entrypoint."""

import uvicorn

from incident_api.main import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(), host="0.0.0.0", port=8080)
