from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.routers import auth, documents, questions, answers

app = FastAPI(
    title="Document Intelligence & Question Extraction Service",
    description="Upload PDFs/images of exam material, extract structured questions and answer keys asynchronously.",
    version="1.0.0",
)

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(questions.router)
app.include_router(answers.router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}
