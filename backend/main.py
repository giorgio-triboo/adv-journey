from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os

app = FastAPI(title="Cepu Lavorazioni System")

# Mount Static Files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates Configuration
templates = Jinja2Templates(directory="templates")

@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse("base.html", {"request": request, "title": "Home"})

@app.get("/health")
async def health_check():
    return {"status": "ok"}
