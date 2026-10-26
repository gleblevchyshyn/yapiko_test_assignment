from contextlib import asynccontextmanager

import instructor
from fastapi import FastAPI
from openai import AsyncOpenAI

from .api import router
from .config import get_settings
from .menu import StopListProvider, load_menu
from .prompts import build_system_prompt


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    menu = load_menu(settings.menu_path)
    app.state.stop_list = StopListProvider(settings.stop_list_path)
    app.state.menu = menu

    app.state.system_prompt = build_system_prompt(menu)
    openai_client = AsyncOpenAI(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        timeout=settings.timeout,
    )
    app.state.client = instructor.from_openai(
        openai_client, mode=instructor.Mode[settings.mode.upper()]
    )

    yield
    await openai_client.close()


app = FastAPI(title="Yapiko order parser", lifespan=lifespan)
app.include_router(router)
