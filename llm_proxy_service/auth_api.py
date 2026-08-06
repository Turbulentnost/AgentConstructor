"""API аутентификации и профиля пользователя."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from llm_proxy_service.avatar_processing import make_circular_avatar
from llm_proxy_service.config import AuthConfig, OneCConfig, ProxyConfig
from llm_proxy_service.db import get_session
from llm_proxy_service.minio_storage import AgentImageStorage, MinioStorageError
from llm_proxy_service.models_user import UserEntity
from llm_proxy_service.onec.password import verify_password
from llm_proxy_service.onec.sql import OneCSqlConfig, connect, find_user_by_login
from llm_proxy_service.sync_users import get_sync_status, sync_users_from_onec

logger = logging.getLogger("llm_proxy.auth")

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


class ProfilePatch(BaseModel):
    email: str | None = None
    display_name: str | None = None
    department: str | None = None

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return value
        text = value.strip()
        if "@" not in text or "." not in text.split("@")[-1]:
            raise ValueError("Некорректный email")
        return text


def _proxy_config(request: Request) -> ProxyConfig:
    return request.app.state.proxy_config


def _auth_config(request: Request) -> AuthConfig:
    auth = _proxy_config(request).auth
    if auth is None or not auth.database_url:
        raise HTTPException(status_code=503, detail="Auth/database is not configured")
    return auth


def _user_to_dict(user: UserEntity, *, has_avatar: bool = False) -> dict[str, Any]:
    return {
        "onec_uid": user.onec_uid,
        "login": user.login,
        "display_name": user.display_name,
        "department": user.department,
        "email": user.email,
        "has_avatar": has_avatar or bool(user.avatar_object_key),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "synced_at": user.synced_at.isoformat() if user.synced_at else None,
    }


def _issue_token(auth: AuthConfig, user: UserEntity) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.onec_uid,
        "login": user.login,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=auth.jwt_ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, auth.jwt_secret, algorithm="HS256")


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> UserEntity:
    """Dependency: текущий пользователь из Bearer JWT."""
    auth = _auth_config(request)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Требуется Authorization: Bearer <token>")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, auth.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Недействительный токен") from exc
    uid = str(payload.get("sub") or "")
    if not uid:
        raise HTTPException(status_code=401, detail="Токен без subject")
    session = get_session()
    try:
        user = session.get(UserEntity, uid)
        if user is None:
            raise HTTPException(status_code=401, detail="Пользователь не найден")
        # Detach for use outside session
        session.expunge(user)
        return user
    finally:
        session.close()


def _fetch_password_data(
    *,
    login: str,
    onec: OneCConfig | None,
    local: UserEntity | None,
) -> tuple[bytes, OneCUserSnapshot | None]:
    """Взять Data из локальной БД или live из 1С."""
    if local is not None and local.password_data:
        return local.password_data, None
    if onec is None:
        raise HTTPException(status_code=503, detail="1C SQL is not configured")
    sql_cfg = OneCSqlConfig(
        server=onec.server,
        database=onec.database,
        trusted=onec.trusted,
        user=onec.user,
        password=onec.password,
        driver=onec.driver,
        port=onec.port,
    )
    try:
        conn = connect(sql_cfg)
    except Exception as exc:
        logger.exception("1C SQL connect failed during login")
        raise HTTPException(
            status_code=503,
            detail=_format_onec_connect_error(exc),
        ) from exc
    try:
        row = find_user_by_login(conn, login)
    except Exception as exc:
        logger.exception("1C SQL lookup failed during login")
        raise HTTPException(
            status_code=503,
            detail=f"Ошибка поиска пользователя в 1С: {exc}",
        ) from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if row is None or not row.password_data:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    return row.password_data, OneCUserSnapshot(
        onec_uid=row.user_id,
        login=row.login,
        display_name=row.display_name,
        department=row.department,
        password_data=row.password_data,
        email=row.email,
    )


class OneCUserSnapshot:
    """Снимок пользователя из 1С для первого логина."""

    def __init__(
        self,
        *,
        onec_uid: str,
        login: str,
        display_name: str,
        department: str,
        password_data: bytes,
        email: str = "",
    ) -> None:
        self.onec_uid = onec_uid
        self.login = login
        self.display_name = display_name
        self.department = department
        self.password_data = password_data
        self.email = email


def _normalize_login(value: str) -> str:
    """Сжать пробелы в логине/ФИО для устойчивого поиска."""
    return " ".join((value or "").strip().split())


def _format_onec_connect_error(exc: Exception) -> str:
    """Человекочитаемая ошибка подключения к SQL Server 1С."""
    text = str(exc)
    if "18456" in text or "Login failed" in text or "ошибка входа" in text.casefold():
        return (
            "SQL Server 1С доступен, но отклонил Windows-вход текущей учётной записи. "
            "Либо выдайте этой учёдке доступ в SSMS, либо в llm_proxy_service/.env "
            "укажите TrustedConnection=no и DB_USER/DB_PASSWORD (SQL-логин с правами "
            f"db_datareader на erp_pm). Детали: {exc}"
        )
    return (
        "Нет доступа к SQL Server 1С. Проверьте DB_SERVER/DB_PORT/ODBC_DRIVER и сеть "
        f"(порт 1433). Детали: {exc}"
    )


def _user_directory_item(user: UserEntity) -> dict[str, str]:
    """Публичная карточка пользователя для экрана входа (без секретов)."""
    return {
        "login": user.login or "",
        "display_name": user.display_name or user.login or "",
        "department": user.department or "",
    }


@router.get("/v1/auth/users")
async def list_users_directory(
    request: Request,
    q: str = "",
    limit: int = 500,
) -> dict[str, Any]:
    """Список пользователей для экрана входа (логин/ФИО/отдел, без паролей).

    Источник — локальная БД после sync из 1С. Если локально пусто — один раз
    пробуем синхронизировать из 1С (если настроено).
    """
    _auth_config(request)
    needle = _normalize_login(q).casefold()
    max_items = max(1, min(int(limit or 500), 2000))

    def _query_local() -> list[UserEntity]:
        session = get_session()
        try:
            stmt = select(UserEntity).order_by(
                func.lower(UserEntity.display_name),
                func.lower(UserEntity.login),
            )
            rows = [
                row
                for row in session.scalars(stmt).all()
                if not (row.onec_uid or "").startswith("BOOTSTRAP-")
            ]
            if needle:
                rows = [
                    row
                    for row in rows
                    if needle in (row.login or "").casefold()
                    or needle in (row.display_name or "").casefold()
                    or needle in (row.department or "").casefold()
                ]
            return rows[:max_items]
        finally:
            session.close()

    rows = _query_local()
    warning = ""
    # Если каталог пуст — один раз тянем из 1С (не хардкод): это тот же sync, что и nightly.
    if not rows:
        onec = _proxy_config(request).onec
        if onec is not None:
            try:
                sync_users_from_onec(onec)
                rows = _query_local()
            except Exception as exc:
                logger.warning("User directory sync failed: %s", exc)
                warning = _format_onec_connect_error(exc)
        if not rows and not warning:
            status = get_sync_status()
            if status.get("ok") is False and status.get("error"):
                warning = str(status["error"])

    return {
        "users": [_user_directory_item(row) for row in rows],
        "total": len(rows),
        "query": q,
        "warning": warning,
        "sync": get_sync_status(),
    }


@router.post("/v1/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    """Проверить пароль по хэшу 1С и выдать JWT; при первом входе создать запись."""
    auth = _auth_config(request)
    onec = _proxy_config(request).onec
    needle = _normalize_login(body.login)
    session = get_session()
    try:
        local = session.scalar(
            select(UserEntity).where(
                (func.lower(UserEntity.login) == needle.casefold())
                | (func.lower(UserEntity.display_name) == needle.casefold())
            )
        )
        if local is None:
            # Фамилия / фрагмент ФИО / частичный логин.
            local = session.scalar(
                select(UserEntity).where(
                    UserEntity.display_name.ilike(f"%{needle}%")
                    | UserEntity.login.ilike(f"%{needle}%")
                )
            )
        password_data, snapshot = _fetch_password_data(
            login=needle,
            onec=onec,
            local=local,
        )
        if not verify_password(password_data, body.password):
            raise HTTPException(status_code=401, detail="Неверный логин или пароль")

        now = datetime.now(timezone.utc)
        if local is None:
            if snapshot is None:
                # Пароль совпал по local? не должно случиться без local
                raise HTTPException(status_code=401, detail="Неверный логин или пароль")
            local = UserEntity(
                onec_uid=snapshot.onec_uid,
                login=snapshot.login,
                display_name=snapshot.display_name or snapshot.login,
                department=snapshot.department or "",
                password_data=snapshot.password_data,
                email=snapshot.email or "",
                created_at=now,
                updated_at=now,
                last_login_at=now,
                synced_at=now,
            )
            session.add(local)
        else:
            local.password_data = password_data or local.password_data
            local.last_login_at = now
            local.updated_at = now
            if snapshot is not None:
                local.display_name = snapshot.display_name or local.display_name
                if snapshot.department:
                    local.department = snapshot.department

        session.commit()
        session.refresh(local)
        token = _issue_token(auth, local)
        return LoginResponse(access_token=token, user=_user_to_dict(local))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unhandled login error")
        raise HTTPException(
            status_code=503,
            detail=f"Сервис входа временно недоступен: {exc}",
        ) from exc
    finally:
        session.close()


@router.get("/v1/auth/me")
async def me(user: UserEntity = Depends(get_current_user)) -> dict[str, Any]:
    """Вернуть профиль текущего пользователя."""
    return _user_to_dict(user)


@router.patch("/v1/auth/me")
async def patch_me(
    body: ProfilePatch,
    request: Request,
    user: UserEntity = Depends(get_current_user),
) -> dict[str, Any]:
    """Обновить только email. ФИО/подразделение менять нельзя."""
    if body.display_name is not None or body.department is not None:
        raise HTTPException(
            status_code=422,
            detail="ФИО и подразделение задаются из 1С и недоступны для изменения",
        )
    if body.email is None:
        raise HTTPException(status_code=422, detail="Нет полей для обновления")
    session = get_session()
    try:
        entity = session.get(UserEntity, user.onec_uid)
        if entity is None:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        entity.email = str(body.email)
        entity.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(entity)
        return _user_to_dict(entity)
    finally:
        session.close()


@router.post("/v1/auth/me/avatar")
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    user: UserEntity = Depends(get_current_user),
) -> dict[str, Any]:
    """Загрузить аватарку: center-crop + круг → MinIO."""
    storage: AgentImageStorage | None = getattr(request.app.state, "agent_image_storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="MinIO недоступен")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Пустой файл")
    try:
        circular = make_circular_avatar(raw)
        stored = storage.put_user_avatar(user.onec_uid, circular)
    except (MinioStorageError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session = get_session()
    try:
        entity = session.get(UserEntity, user.onec_uid)
        if entity is None:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        entity.avatar_object_key = stored.object_key
        entity.updated_at = datetime.now(timezone.utc)
        session.commit()
        return {"ok": True, "object_key": stored.object_key, "user": _user_to_dict(entity, has_avatar=True)}
    finally:
        session.close()


@router.get("/v1/auth/me/avatar")
async def get_avatar(
    request: Request,
    user: UserEntity = Depends(get_current_user),
) -> Response:
    """Отдать PNG-аватарку текущего пользователя."""
    storage: AgentImageStorage | None = getattr(request.app.state, "agent_image_storage", None)
    if storage is None:
        raise HTTPException(status_code=503, detail="MinIO недоступен")
    found = storage.get_user_avatar(user.onec_uid, user.avatar_object_key)
    if found is None:
        raise HTTPException(status_code=404, detail="Аватарка не найдена")
    payload, content_type = found
    return Response(content=payload, media_type=content_type)


@router.post("/v1/admin/users/sync")
async def admin_sync(
    request: Request,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    """Принудительная синхронизация пользователей из 1С."""
    auth = _auth_config(request)
    onec = _proxy_config(request).onec
    if not auth.admin_token:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN не задан")
    if not x_admin_token or x_admin_token != auth.admin_token:
        raise HTTPException(status_code=401, detail="Неверный admin token")
    if onec is None:
        raise HTTPException(status_code=503, detail="1C SQL is not configured")
    result = sync_users_from_onec(onec)
    return {
        "ok": True,
        "fetched": result.fetched,
        "created": result.created,
        "updated": result.updated,
        "notes": list(result.notes),
    }
