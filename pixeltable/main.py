"""FastAPI application for the Pixeltable knowledge-base benchmark."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

import setup_pixeltable
from routers import agent, data, search


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    setup_pixeltable.init()
    yield


app = FastAPI(title='Pixeltable Knowledge Base', lifespan=lifespan)

app.include_router(data.router)
app.include_router(search.router)
app.include_router(agent.router)

if __name__ == '__main__':
    import uvicorn

    uvicorn.run('main:app', host='0.0.0.0', port=8000, reload=True)
