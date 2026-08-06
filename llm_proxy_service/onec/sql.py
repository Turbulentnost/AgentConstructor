"""Read-only доступ к SQL Server базе 1С (erp_pm)."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("llm_proxy.onec.sql")

FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|EXEC|EXECUTE|GRANT|REVOKE|BACKUP|RESTORE)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OneCSqlConfig:
    """Параметры подключения к SQL Server 1С."""

    server: str
    database: str
    trusted: bool = True
    user: str = ""
    password: str = ""
    driver: str = "ODBC Driver 18 for SQL Server"
    port: int | None = None


_MODERN_DRIVER_PREFIXES = ("ODBC Driver", "ODBC Driver for SQL Server")


def resolve_odbc_driver(preferred: str = "") -> str:
    """Выбрать лучший установленный ODBC-драйвер SQL Server."""
    try:
        import pyodbc
    except ImportError as exc:
        raise RuntimeError("Установите pyodbc: pip install pyodbc") from exc
    installed = list(pyodbc.drivers())
    candidates = [
        preferred.strip(),
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
        "SQL Server",
    ]
    for name in candidates:
        if name and name in installed:
            return name
    raise RuntimeError(
        "Не найден ODBC-драйвер SQL Server. Установите "
        "«ODBC Driver 18 for SQL Server» (winget: Microsoft.msodbcsql.18)."
    )


def _is_modern_driver(driver: str) -> bool:
    return driver.strip().casefold().startswith("odbc driver")


@dataclass
class OneCUserRow:
    """Пользователь из v8users (+ опциональное подразделение/email)."""

    user_id: str
    login: str
    display_name: str
    os_name: str
    password_data: bytes
    email: str = ""
    department: str = ""


@dataclass
class OneCExportResult:
    """Результат выгрузки пользователей из 1С."""

    users: list[OneCUserRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def assert_select_only(sql: str) -> str:
    """Разрешить только SELECT/WITH/SET."""
    stripped = sql.strip().lstrip("(")
    upper = stripped.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH") or upper.startswith("SET ")):
        raise ValueError(f"Only SELECT/WITH/SET allowed, got: {sql[:80]!r}")
    if upper.startswith("SET "):
        return sql
    if FORBIDDEN_SQL.search(sql):
        raise ValueError(f"Forbidden SQL keyword detected: {sql[:120]!r}")
    return sql


def build_connection_string(cfg: OneCSqlConfig) -> str:
    """Собрать ODBC connection string под современный или legacy-драйвер."""
    driver = resolve_odbc_driver(cfg.driver)
    server = cfg.server.strip()
    if cfg.port and "," not in server and "\\" not in server:
        server = f"{server},{int(cfg.port)}"
    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={cfg.database}",
        "Connection Timeout=15",
    ]
    # Encrypt / TrustServerCertificate / ApplicationIntent — только у ODBC 13+.
    # Legacy «SQL Server» отвечает «Недопустимый атрибут строки соединения».
    if _is_modern_driver(driver):
        parts.extend(
            [
                "Encrypt=no",
                "TrustServerCertificate=yes",
                "ApplicationIntent=ReadOnly",
            ]
        )
    if cfg.trusted:
        parts.append("Trusted_Connection=yes")
    else:
        if not cfg.user:
            raise ValueError("DB_USER is required when TrustedConnection=no")
        parts.append(f"UID={cfg.user}")
        parts.append(f"PWD={cfg.password}")
    return ";".join(parts)


def _windows_credential_targets(cfg: OneCSqlConfig) -> list[str]:
    """Цели для cmdkey (хост и хост:порт), чтобы SSPI подхватил чужую учётку."""
    host = cfg.server.strip().split("\\")[0].split(",")[0].strip()
    if not host:
        return []
    targets = [host]
    port = cfg.port
    if port is None and "," in cfg.server:
        maybe_port = cfg.server.split(",", 1)[1].strip()
        if maybe_port.isdigit():
            port = int(maybe_port)
    if port:
        targets.append(f"{host}:{int(port)}")
    return targets


def ensure_windows_network_credentials(cfg: OneCSqlConfig) -> None:
    """Если TrustedConnection + DB_USER/DB_PASSWORD — положить их в Credential Manager.

    SQL Server не принимает доменную учётку как SQL-login (UID/PWD). Нужен
    Trusted_Connection=yes от имени сохранённых сетевых credentials (cmdkey),
    иначе остаётся текущий Windows-пользователь процесса.
    """
    if not cfg.trusted or not (cfg.user or "").strip() or cfg.password is None:
        return
    if not (cfg.password or cfg.user):
        return
    user = cfg.user.strip()
    # Часто передают короткий login без домена — для этого хоста домен TURBO-DON.
    if "\\" not in user and "@" not in user:
        user = f"TURBO-DON\\{user}"
    for target in _windows_credential_targets(cfg):
        try:
            subprocess.run(
                ["cmdkey", f"/delete:{target}"],
                check=False,
                capture_output=True,
                text=True,
            )
            completed = subprocess.run(
                [
                    "cmdkey",
                    f"/add:{target}",
                    f"/user:{user}",
                    f"/pass:{cfg.password}",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                logger.warning(
                    "cmdkey /add:%s failed rc=%s stderr=%s",
                    target,
                    completed.returncode,
                    (completed.stderr or "").strip()[:300],
                )
            else:
                logger.info("Windows credentials stored for SQL target %s as %s", target, user)
        except OSError as exc:
            logger.warning("cmdkey unavailable: %s", exc)
            return


def connect(cfg: OneCSqlConfig) -> Any:
    """Открыть read-only соединение."""
    try:
        import pyodbc
    except ImportError as exc:
        raise RuntimeError("Установите pyodbc: pip install pyodbc") from exc
    ensure_windows_network_credentials(cfg)
    conn = pyodbc.connect(build_connection_string(cfg), autocommit=True)
    cursor = conn.cursor()
    cursor.execute(assert_select_only("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"))
    cursor.execute(assert_select_only("SET NOCOUNT ON"))
    cursor.close()
    return conn


def fetchall(conn: Any, sql: str, params: tuple | list = ()) -> list[Any]:
    """Выполнить SELECT и вернуть все строки."""
    sql = assert_select_only(sql)
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        if cursor.description is None:
            return []
        return cursor.fetchall()
    finally:
        cursor.close()


def fetchone(conn: Any, sql: str, params: tuple | list = ()) -> Any | None:
    """Выполнить SELECT и вернуть первую строку."""
    rows = fetchall(conn, sql, params)
    return rows[0] if rows else None


def ensure_v8users(conn: Any) -> str:
    """Вернуть qualified имя таблицы v8users."""
    row = fetchone(
        conn,
        """
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
          AND LOWER(TABLE_NAME) = 'v8users'
        """,
    )
    if not row:
        raise RuntimeError("Table v8users not found — is this a 1C SQL Server IB?")
    return f"[{row.TABLE_SCHEMA}].[{row.TABLE_NAME}]"


def load_users(conn: Any, table: str | None = None) -> list[OneCUserRow]:
    """Загрузить пользователей из v8users."""
    table = table or ensure_v8users(conn)
    sql = f"""
        SELECT
            CONVERT(varchar(64), ID, 2) AS UserId,
            CAST(Name AS nvarchar(128)) AS Login,
            CAST(Descr AS nvarchar(256)) AS DisplayName,
            CAST(ISNULL(OSName, N'') AS nvarchar(256)) AS OSName,
            Data AS PasswordData
        FROM {table}
        ORDER BY Name
    """
    rows = fetchall(conn, sql)
    users: list[OneCUserRow] = []
    for row in rows:
        raw = getattr(row, "PasswordData", None)
        password_data = bytes(raw) if raw is not None else b""
        users.append(
            OneCUserRow(
                user_id=(row.UserId or "").strip(),
                login=(row.Login or "").strip(),
                display_name=(row.DisplayName or "").strip(),
                os_name=(row.OSName or "").strip(),
                password_data=password_data,
            )
        )
    return users


def find_user_by_login(conn: Any, login: str) -> OneCUserRow | None:
    """Найти пользователя по логину или ФИО (Descr), без учёта регистра/пробелов."""
    table = ensure_v8users(conn)
    sql = f"""
        SELECT TOP 1
            CONVERT(varchar(64), ID, 2) AS UserId,
            CAST(Name AS nvarchar(128)) AS Login,
            CAST(Descr AS nvarchar(256)) AS DisplayName,
            CAST(ISNULL(OSName, N'') AS nvarchar(256)) AS OSName,
            Data AS PasswordData
        FROM {table}
        WHERE Name = ?
           OR Descr = ?
           OR LOWER(LTRIM(RTRIM(Name))) = LOWER(?)
           OR LOWER(LTRIM(RTRIM(Descr))) = LOWER(?)
           OR Name LIKE ?
           OR Descr LIKE ?
        ORDER BY
            CASE
                WHEN Name = ? THEN 0
                WHEN Descr = ? THEN 1
                WHEN LOWER(LTRIM(RTRIM(Name))) = LOWER(?) THEN 2
                WHEN LOWER(LTRIM(RTRIM(Descr))) = LOWER(?) THEN 3
                ELSE 4
            END
    """
    needle = " ".join(login.strip().split())
    like = f"%{needle}%"
    row = fetchone(
        conn,
        sql,
        (
            needle,
            needle,
            needle,
            needle,
            like,
            like,
            needle,
            needle,
            needle,
            needle,
        ),
    )
    if not row:
        return None
    raw = getattr(row, "PasswordData", None)
    return OneCUserRow(
        user_id=(row.UserId or "").strip(),
        login=(row.Login or "").strip(),
        display_name=(row.DisplayName or "").strip(),
        os_name=(row.OSName or "").strip(),
        password_data=bytes(raw) if raw is not None else b"",
    )


def load_department_map(conn: Any, explicit_sql: str = "") -> dict[str, str]:
    """Построить map login/name/id → подразделение.

    Если задан explicit_sql — выполнить его (должен вернуть MapKey, Department).
    Иначе — best-effort поиск по колонкам с 'подразд' / 'department'.
    """
    mapping: dict[str, str] = {}
    if explicit_sql.strip():
        rows = fetchall(conn, explicit_sql)
        for row in rows:
            key = str(getattr(row, "MapKey", "") or "").strip().lower()
            dept = str(getattr(row, "Department", "") or "").strip()
            if key and dept:
                mapping[key] = dept
        return mapping

    try:
        cols = fetchall(
            conn,
            """
            SELECT TOP 40 TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE (
                    COLUMN_NAME LIKE N'%Подразд%'
                 OR LOWER(COLUMN_NAME) LIKE '%department%'
                 OR LOWER(COLUMN_NAME) LIKE '%подразд%'
            )
              AND DATA_TYPE IN ('nvarchar', 'varchar', 'nchar', 'char')
            ORDER BY TABLE_NAME
            """,
        )
    except Exception:
        return mapping

    for schema, table, col in cols[:12]:
        key_cols = fetchall(
            conn,
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
              AND (
                    LOWER(COLUMN_NAME) IN ('_description', 'description', 'name', '_code', 'code')
                 OR LOWER(COLUMN_NAME) LIKE '%descr%'
              )
            """,
            (schema, table),
        )
        if not key_cols:
            continue
        key_col = key_cols[0].COLUMN_NAME
        sql = f"""
            SELECT TOP 500
                CAST([{key_col}] AS nvarchar(400)) AS MapKey,
                CAST([{col}] AS nvarchar(400)) AS Department
            FROM [{schema}].[{table}]
            WHERE [{col}] IS NOT NULL AND LEN(CAST([{col}] AS nvarchar(400))) > 1
        """
        try:
            rows = fetchall(conn, sql)
        except Exception:
            continue
        for row in rows:
            key = str(getattr(row, "MapKey", "") or "").strip().lower()
            dept = str(getattr(row, "Department", "") or "").strip()
            if key and dept and key not in mapping:
                mapping[key] = dept
        if mapping:
            break
    return mapping


def attach_departments(users: list[OneCUserRow], dept_map: dict[str, str]) -> int:
    """Проставить department из map; вернуть число совпадений."""
    matched = 0
    for user in users:
        dept = (
            dept_map.get(user.login.lower())
            or dept_map.get(user.display_name.lower())
            or dept_map.get(user.user_id.lower())
        )
        if dept:
            user.department = dept
            matched += 1
    return matched


def export_users(cfg: OneCSqlConfig, *, department_sql: str = "") -> OneCExportResult:
    """Выгрузить пользователей 1С (read-only)."""
    result = OneCExportResult()
    conn = connect(cfg)
    try:
        users = load_users(conn)
        result.users = users
        dept_map = load_department_map(conn, department_sql)
        if dept_map:
            matched = attach_departments(users, dept_map)
            result.notes.append(f"Department matched for {matched}/{len(users)} users")
        else:
            result.notes.append("Department source not found; left empty")
        return result
    finally:
        conn.close()
