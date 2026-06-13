from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from database import engine, Base
from models import models
from routers import events, students, houses, certificates, auth, dashboard, settings
from init_db import init_db

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