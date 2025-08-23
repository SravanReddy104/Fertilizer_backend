from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from typing import Any, Dict
from app.core.logging import logger


class AppError(Exception):
    status_code: int = 500

    def __init__(self, message: str, *, status_code: int | None = None, extra: Dict[str, Any] | None = None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        self.extra = extra or {}

    @property
    def message(self) -> str:
        return str(self)


class NotFoundError(AppError):
    status_code = 404


class BadRequestError(AppError):
    status_code = 400


class DatabaseError(AppError):
    status_code = 500


def register_exception_handlers(app: FastAPI):
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        # Log structured app errors at warning level
        logger.warning(
            "AppError | type=%s status=%s path=%s message=%s extra=%s",
            exc.__class__.__name__,
            getattr(exc, "status_code", 500),
            request.url.path,
            exc.message,
            getattr(exc, "extra", {}),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "message": exc.message,
                    "type": exc.__class__.__name__,
                    "extra": exc.extra,
                }
            },
        )

    # Optional: fallback for unexpected exceptions
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # Log full traceback for unexpected errors
        logger.exception("Unhandled exception at %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": "Internal server error",
                    "type": "InternalServerError",
                }
            },
        )
