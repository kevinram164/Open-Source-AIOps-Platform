"""Application entrypoint."""

import uvicorn

from rca_agent.config import settings
from rca_agent.main import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "rca_agent.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
