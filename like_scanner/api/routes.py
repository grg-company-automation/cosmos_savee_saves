from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
import logging

# DI dependencies
from .dependencies import get_savee_driver, get_cosmos_driver
# assuming schemas.py and models.py are in the same package
from . import schemas
from like_scanner.core import models
# Import the functions and classes for authentication and parsing
# adjust the import to the actual module
from like_scanner.infra.drivers.savee_driver import perform_savee_login
from like_scanner.infra.drivers.cosmos_driver import perform_cosmos_login

# Configure logger for this module
logger = logging.getLogger("like_scanner.routes")
logger.setLevel(logging.INFO)
# Ensure the logger has a handler with the desired format (▶)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s ▶ %(levelname)s ▶ %(message)s"))
    logger.addHandler(handler)

# Initialize API router
router = APIRouter()

# ── Auth Routes ──


@router.get("/health", response_class=JSONResponse)
async def health():
    """Health check endpoint."""
    # Simply return a positive health status
    return JSONResponse(content={"status": "ok"})


@router.post("/parse-savee-auth", response_class=JSONResponse)
def parse_savee_auth(savee_driver=Depends(get_savee_driver)):
    """
    Авторизация на Savee через magic-link из настроек.
    """
    try:
        logger.info("▶ Starting Savee authentication…")
        if not perform_savee_login(savee_driver):
            raise RuntimeError("Savee login failed")
        logger.info("▶ Savee authentication successful.")
        return JSONResponse(content={"status": "success"})
    except Exception as exc:
        logger.error("Savee authentication failed: %s", exc, exc_info=True)
        raise HTTPException(500, str(exc))


@router.post("/parse-cosmos-auth", response_class=JSONResponse)
def parse_cosmos_auth(cosmos_driver=Depends(get_cosmos_driver)):
    """
    Авторизация на Cosmos (email/пароль из .env).
    """
    try:
        logger.info("▶ Starting Cosmos authentication…")
        if not perform_cosmos_login(cosmos_driver):
            raise RuntimeError("Cosmos login failed")
        logger.info("▶ Cosmos authentication successful.")
        return JSONResponse(content={"status": "success"})
    except Exception as exc:
        logger.error("Cosmos authentication failed: %s", exc, exc_info=True)
        raise HTTPException(500, str(exc))

# ── Parse Routes ──


@router.post("/parse-savee-continue", response_class=JSONResponse)
def parse_savee_continue(
    request: schemas.SaveeContinueRequest,
    savee_driver=Depends(get_savee_driver),
):
    """
    Продолжить парсинг Savee с указанного индекса.
    """
    try:
        logger.info("▶ Continuing Savee parsing operation…")
        session_tracker = models.SessionTracker(
            driver=savee_driver,
            next_index=request.next_index,
        )
        scan_result: models.ScanResult = session_tracker.continue_parse()
        return JSONResponse(content=scan_result.dict())
    except Exception as exc:
        logger.error("Error during Savee parse continuation: %s",
                     exc, exc_info=True)
        raise HTTPException(500, str(exc))


@router.post("/parse-cosmos-continue", response_class=JSONResponse)
def parse_cosmos_continue(
    request: schemas.CosmosContinueRequest,
    cosmos_driver=Depends(get_cosmos_driver),
):
    """
    Продолжить парсинг Cosmos с указанного индекса.
    """
    try:
        logger.info("▶ Continuing Cosmos parsing operation…")
        session_tracker = models.SessionTracker(
            driver=cosmos_driver,
            next_index=request.next_index,
        )
        scan_result: models.ScanResult = session_tracker.continue_parse()
        return JSONResponse(content=scan_result.dict())
    except Exception as exc:
        logger.error("Error during Cosmos parse continuation: %s",
                     exc, exc_info=True)
        raise HTTPException(500, str(exc))
