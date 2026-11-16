import hmac
import os
import time
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing_extensions import Annotated

from database import create_connection_pool


class LedgerError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


class BalanceRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
    amount: int = Field(..., strict=True, gt=0, le=1_000_000_000)


def _is_retryable_db_error(exc: Exception) -> bool:
    sqlstate = getattr(exc, "sqlstate", None)
    return sqlstate in {"40001", "40P01", "55P03"}


def _invalid_request_response() -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": "invalid_request", "message": "malformed JSON or invalid input"},
    )


def require_auth(request: Request) -> None:
    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        raise LedgerError(401, "unauthorized", "missing Authorization header")

    parts = auth_header.strip().split(None, 1)
    if len(parts) != 2:
        raise LedgerError(401, "unauthorized", "invalid Authorization scheme")

    scheme, token = parts
    if scheme.lower() != "bearer" or not token.strip():
        raise LedgerError(401, "unauthorized", "invalid Authorization scheme")

    token = token.strip()
    expected = os.getenv("API_TOKEN", "")
    if not hmac.compare_digest(token, expected):
        raise LedgerError(401, "unauthorized", "invalid bearer token")


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pool = create_connection_pool()
        pool.open()
        try:
            pool.wait()
            app.state.db_pool = pool
            yield
        finally:
            pool.close()

    app = FastAPI(lifespan=lifespan)

    @app.exception_handler(LedgerError)
    async def ledger_error_handler(_request: Request, exc: LedgerError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "message": exc.message})

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return _invalid_request_response()

    @app.middleware("http")
    async def ensure_auth(request: Request, call_next):
        if request.url.path in {"/credit", "/debit", "/balance"} or request.url.path.startswith("/balance/"):
            try:
                require_auth(request)
            except LedgerError as exc:
                return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "message": exc.message})
        return await call_next(request)

    @app.post("/credit")
    def credit(payload: BalanceRequest, request: Request) -> dict[str, Any]:
        with request.app.state.db_pool.connection() as conn:
            for attempt in range(5):
                try:
                    with conn.transaction():
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO user_balances (user_id, balance) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING",
                                (payload.user_id,),
                            )
                            cur.execute(
                                "SELECT balance FROM user_balances WHERE user_id = %s FOR UPDATE",
                                (payload.user_id,),
                            )
                            balance = cur.fetchone()[0]
                            next_balance = balance + payload.amount
                            cur.execute(
                                "INSERT INTO ledger (user_id, entry_type, amount, created_at) VALUES (%s, 'credit', %s, NOW())",
                                (payload.user_id, payload.amount),
                            )
                            cur.execute(
                                "UPDATE user_balances SET balance = %s WHERE user_id = %s",
                                (next_balance, payload.user_id),
                            )
                    return {"user_id": payload.user_id, "balance": next_balance}
                except psycopg.Error as exc:
                    if not _is_retryable_db_error(exc) or attempt == 4:
                        raise
                    time.sleep(min(0.01 * (2**attempt), 0.1))

        raise RuntimeError("credit transaction failed after retries")

    @app.post("/debit")
    def debit(payload: BalanceRequest, request: Request) -> dict[str, Any]:
        with request.app.state.db_pool.connection() as conn:
            for attempt in range(5):
                try:
                    with conn.transaction():
                        with conn.cursor() as cur:
                            cur.execute(
                                "SELECT balance FROM user_balances WHERE user_id = %s FOR UPDATE",
                                (payload.user_id,),
                            )
                            row = cur.fetchone()
                            if row is None:
                                raise LedgerError(404, "user_not_found", "user does not exist")
                            balance = row[0]
                            if balance < payload.amount:
                                raise LedgerError(409, "insufficient_funds", "debit would reduce balance below zero")
                            next_balance = balance - payload.amount
                            cur.execute(
                                "INSERT INTO ledger (user_id, entry_type, amount, created_at) VALUES (%s, 'debit', %s, NOW())",
                                (payload.user_id, payload.amount),
                            )
                            cur.execute(
                                "UPDATE user_balances SET balance = %s WHERE user_id = %s",
                                (next_balance, payload.user_id),
                            )
                    return {"user_id": payload.user_id, "balance": next_balance}
                except psycopg.Error as exc:
                    if not _is_retryable_db_error(exc) or attempt == 4:
                        raise
                    time.sleep(min(0.01 * (2**attempt), 0.1))
                except LedgerError:
                    raise

        raise RuntimeError("debit transaction failed after retries")

    @app.get("/balance/{user_id}")
    def get_balance(user_id: Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")], request: Request) -> dict[str, Any]:
        with request.app.state.db_pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SELECT balance FROM user_balances WHERE user_id = %s", (user_id,))
                    row = cur.fetchone()
                    if row is None:
                        raise LedgerError(404, "user_not_found", "user does not exist")
                    return {"user_id": user_id, "balance": row[0]}

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        if exc.status_code == 401:
            code = "unauthorized"
            message = "missing or invalid bearer token"
            status_code = 401
        elif exc.status_code == 404:
            code = "user_not_found"
            message = "user does not exist"
            status_code = 404
        elif exc.status_code == 409:
            code = "insufficient_funds"
            message = "debit would reduce balance below zero"
            status_code = 409
        elif exc.status_code == 422:
            code = "invalid_request"
            message = "malformed JSON or invalid input"
            status_code = 400
        else:
            code = "invalid_request"
            message = exc.detail if isinstance(exc.detail, str) else "invalid request"
            status_code = 400 if exc.status_code == 422 else exc.status_code
        return JSONResponse(status_code=status_code, content={"error": code, "message": message})

    return app
