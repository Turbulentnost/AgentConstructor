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


def _add_dept_keys(mapping: dict[str, str], *, user_id: str, login: str, display_name: str, dept: str) -> None:
    dept = (dept or "").strip()
    if not dept:
        return
    for key in (user_id, login, display_name):
        normalized = " ".join((key or "").strip().split()).lower()
        if normalized and normalized not in mapping:
            mapping[normalized] = dept


def _department_map_from_rows(rows: list[Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in rows:
        # Формат A: MapKey + Department
        key = str(getattr(row, "MapKey", "") or "").strip().lower()
        dept = str(getattr(row, "Department", "") or "").strip()
        if key and dept:
            mapping[key] = dept
            continue
        # Формат B: UserId/Login/DisplayName + Department (join к v8users)
        _add_dept_keys(
            mapping,
            user_id=str(getattr(row, "UserId", "") or ""),
            login=str(getattr(row, "Login", "") or ""),
            display_name=str(getattr(row, "DisplayName", "") or ""),
            dept=str(getattr(row, "Department", "") or ""),
        )
    return mapping


def _load_department_map_via_ib_users_catalog(conn: Any) -> tuple[dict[str, str], str]:
    """Подразделение через Справочник.Пользователи: v8users.ID → подразделение.

    В SQL 1С имена вида _ReferenceNNN / _FldXXXX. Для erp_pm (и типичных УТ/ERP):
    - справочник пользователей содержит binary-поле с ID из v8users;
    - RRef-поле указывает на справочник подразделений (_Description).
    """
    v8 = ensure_v8users(conn)
    users_count_row = fetchone(conn, f"SELECT COUNT(*) AS Cnt FROM {v8}")
    users_count = int(getattr(users_count_row, "Cnt", 0) or 0)
    if users_count <= 0:
        return {}, ""

    # Быстрый путь для известной конфигурации erp_pm.
    known_sql = f"""
        SELECT
            CONVERT(varchar(64), u.ID, 2) AS UserId,
            CAST(u.Name AS nvarchar(128)) AS Login,
            CAST(u.Descr AS nvarchar(256)) AS DisplayName,
            CAST(d.[_Description] AS nvarchar(400)) AS Department
        FROM {v8} u
        INNER JOIN dbo.[_Reference366] uc ON uc.[_Fld11001] = u.ID
        INNER JOIN dbo.[_Reference513] d ON d.[_IDRRef] = uc.[_Fld10996RRef]
        WHERE d.[_Description] IS NOT NULL
          AND LEN(LTRIM(RTRIM(CAST(d.[_Description] AS nvarchar(400))))) > 1
    """
    try:
        rows = fetchall(conn, known_sql)
        mapping = _department_map_from_rows(rows)
        if len(mapping) >= max(10, users_count // 5):
            return mapping, "ib_users_catalog:erp_pm(_Reference366/_Reference513)"
    except Exception as exc:
        logger.info("Known erp_pm department SQL failed: %s", exc)

    # Автопоиск: таблица пользователей ИБ по числу совпадений binary-поля с v8users.ID.
    candidates = fetchall(
        conn,
        """
        SELECT c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS c
        WHERE c.TABLE_NAME LIKE '_Reference%'
          AND c.TABLE_NAME NOT LIKE '%X%'
          AND c.DATA_TYPE = 'binary'
          AND c.CHARACTER_MAXIMUM_LENGTH = 16
          AND c.COLUMN_NAME NOT IN ('_IDRRef', '_PredefinedID', '_ParentIDRRef', '_OwnerIDRRef')
          AND EXISTS (
              SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS d
              WHERE d.TABLE_SCHEMA = c.TABLE_SCHEMA
                AND d.TABLE_NAME = c.TABLE_NAME
                AND d.COLUMN_NAME = '_Description'
          )
        ORDER BY c.TABLE_NAME
        """,
    )
    best_user_table = None
    best_ib_col = None
    best_hits = 0
    for schema, table, col in candidates:
        try:
            row = fetchone(
                conn,
                f"""
                SELECT COUNT(*) AS Cnt
                FROM {v8} u
                INNER JOIN [{schema}].[{table}] uc
                  ON uc.[{col}] = u.ID
                """,
            )
        except Exception:
            continue
        hits = int(getattr(row, "Cnt", 0) or 0)
        if hits > best_hits:
            best_hits = hits
            best_user_table = (schema, table)
            best_ib_col = col
            if hits >= int(users_count * 0.8):
                break
    if not best_user_table or not best_ib_col or best_hits < max(10, users_count // 5):
        return {}, ""

    schema, user_table = best_user_table
    rref_cols = fetchall(
        conn,
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
          AND DATA_TYPE = 'binary'
          AND CHARACTER_MAXIMUM_LENGTH = 16
          AND COLUMN_NAME LIKE '%RRef'
          AND COLUMN_NAME NOT IN ('_IDRRef', '_PredefinedID', '_ParentIDRRef', '_OwnerIDRRef')
        """,
        (schema, user_table),
    )
    dept_tables = fetchall(
        conn,
        """
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
          AND TABLE_NAME LIKE '_Reference%'
          AND TABLE_NAME NOT LIKE '%X%'
          AND EXISTS (
              SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS c
              WHERE c.TABLE_SCHEMA = TABLES.TABLE_SCHEMA
                AND c.TABLE_NAME = TABLES.TABLE_NAME
                AND c.COLUMN_NAME = '_Description'
          )
        """,
    )

    best_mapping: dict[str, str] = {}
    best_note = ""
    best_score = -1
    markers = ("отдел", "служб", "цех", "управлен", "сектор", "участ", "директ")
    for rref in rref_cols:
        rref_col = rref.COLUMN_NAME
        for dept_schema, dept_table in dept_tables:
            sql = f"""
                SELECT
                    CONVERT(varchar(64), u.ID, 2) AS UserId,
                    CAST(u.Name AS nvarchar(128)) AS Login,
                    CAST(u.Descr AS nvarchar(256)) AS DisplayName,
                    CAST(d.[_Description] AS nvarchar(400)) AS Department
                FROM {v8} u
                INNER JOIN [{schema}].[{user_table}] uc
                  ON uc.[{best_ib_col}] = u.ID
                INNER JOIN [{dept_schema}].[{dept_table}] d
                  ON d.[_IDRRef] = uc.[{rref_col}]
                WHERE d.[_Description] IS NOT NULL
                  AND LEN(LTRIM(RTRIM(CAST(d.[_Description] AS nvarchar(400))))) > 1
            """
            try:
                rows = fetchall(conn, sql)
            except Exception:
                continue
            user_keys = {
                str(getattr(r, "UserId", "") or "").strip().lower()
                for r in rows
                if str(getattr(r, "Department", "") or "").strip()
            }
            if len(user_keys) < max(10, users_count // 10):
                continue
            dept_names = [
                str(getattr(r, "Department", "") or "")
                for r in rows[:100]
                if str(getattr(r, "Department", "") or "").strip()
            ]
            marker_hits = sum(
                1 for name in dept_names if any(m in name.casefold() for m in markers)
            )
            score = len(user_keys) * 10 + marker_hits
            if score <= best_score:
                continue
            best_score = score
            best_mapping = _department_map_from_rows(rows)
            best_note = (
                f"ib_users_catalog:{user_table}.{best_ib_col}"
                f"->{dept_table} via {rref_col} ({len(user_keys)} users)"
            )
            if len(user_keys) >= int(users_count * 0.7) and marker_hits >= 5:
                return best_mapping, best_note

    return best_mapping, best_note


def load_department_map(conn: Any, explicit_sql: str = "") -> dict[str, str]:
    """Построить map login/name/id → подразделение.

    Порядок:
    1) explicit_sql (MapKey/Department или UserId/Login/DisplayName/Department);
    2) join Справочник.Пользователи (v8users.ID) → справочник подразделений;
    3) устаревший best-effort по именам колонок (обычно пусто в SQL 1С).
    """
    if explicit_sql.strip():
        rows = fetchall(conn, explicit_sql)
        mapping = _department_map_from_rows(rows)
        if mapping:
            return mapping

    mapping, note = _load_department_map_via_ib_users_catalog(conn)
    if mapping:
        logger.info("Departments loaded via %s (%s keys)", note, len(mapping))
        return mapping

    mapping = {}
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
        login_key = " ".join(user.login.split()).lower()
        name_key = " ".join(user.display_name.split()).lower()
        dept = (
            dept_map.get(login_key)
            or dept_map.get(name_key)
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
