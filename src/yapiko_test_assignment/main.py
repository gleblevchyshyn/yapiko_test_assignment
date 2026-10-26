from fastapi import FastAPI


from .api import router

app = FastAPI(title="Yapiko order parser")
app.include_router(router)