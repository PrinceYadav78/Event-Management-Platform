from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from app.database import engine, Base
from app.models import models
from app.routers import events, students, houses, certificates, auth, dashboard, settings
from app.init_db import init_db

Base.metadata.create_all(bind=engine)

app = FastAPI(title="National Public School - Events Manager")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(events.router)
app.include_router(students.router)
app.include_router(houses.router)
app.include_router(certificates.router)
app.include_router(settings.router)

@app.on_event("startup")
async def startup_event():
    init_db()

@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")