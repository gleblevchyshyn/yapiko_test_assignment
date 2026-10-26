from contextlib import asynccontextmanager
from fastapi import FastAPI


from .api import router
from .config import get_settings
from .menu import load_menu, load_stop_list
from .prompts import build_system_prompt


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    menu = load_menu(settings.menu_path)
    stop_list = load_stop_list(settings.stop_list_path)
    system_prompt = build_system_prompt


app = FastAPI(title="Yapiko order parser")
app.include_router(router)
