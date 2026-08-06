"""Проверка пароля 1С по полю v8users.Data.

Формат Data (как в PasswordChanger1C):
  byte0     = длина ключа N
  byte1..N  = ключ
  byteN+1.. = payload XOR (ключ циклически)

После XOR получается UTF-8 строка внутренней структуры 1С. Хэши пароля —
Base64(SHA-1):
  - старый формат: одна строка \"plain,UPPER\";
  - современный erp_pm: отдельные поля \"plain\",\"UPPER\" (и другие Base64 рядом).
"""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any

# Старый формат PasswordChanger1C: "base64plain,base64upper" в одном литерале.
_HASH_PAIR_RE = re.compile(
    r"([A-Za-z0-9+/]{20,}={0,2}),([A-Za-z0-9+/]{20,}={0,2})"
)
# Современный формат: соседние quoted Base64(SHA-1), 28 символов (20 байт digest).
_QUOTED_HASH_RE = re.compile(r'"([A-Za-z0-9+/]{27}={0,2})"')
_EMPTY_SHA1_B64 = "2jmj7l5rSw0yVb/vlWAYkK/YBwk="


def decode_password_structure(data: bytes) -> tuple[int, bytes, str]:
    """Декодировать Data → (key_size, key_bytes, utf8_structure)."""
    if not data:
        raise ValueError("Пустой блок Data")
    key_size = int(data[0])
    if key_size <= 0 or key_size >= len(data):
        raise ValueError(f"Некорректный размер ключа: {key_size}")
    key = data[1 : key_size + 1]
    payload = data[key_size + 1 :]
    decoded = bytearray(len(payload))
    for index, value in enumerate(payload):
        decoded[index] = value ^ key[index % key_size]
    return key_size, bytes(key), bytes(decoded).decode("utf-8", errors="replace")


def sha1_base64(text: str) -> str:
    """SHA-1(UTF-8) → Base64, как EncryptStringSHA1 в 1С."""
    digest = hashlib.sha1(text.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_password_data(password: str, *, key: bytes | None = None) -> bytes:
    """Собрать блок v8users.Data для пароля (как EncodePasswordStructure в 1С).

    Используется в unit-тестах. В проде password_data приходит только из sync 1С.
    """
    secret = key if key is not None else b"\x11\x22\x33\x44"
    if not secret:
        raise ValueError("Ключ XOR не должен быть пустым")
    plain = sha1_base64(password)
    upper = sha1_base64(password.upper())
    structure = f'{{guid,1,1,"{plain},{upper}",0}}'
    key_size = len(secret)
    payload = structure.encode("utf-8")
    out = bytearray(1 + key_size + len(payload))
    out[0] = key_size
    out[1 : 1 + key_size] = secret
    for index, value in enumerate(payload):
        out[1 + key_size + index] = value ^ secret[index % key_size]
    return bytes(out)


def extract_stored_hashes(structure: str) -> tuple[str, str]:
    """Извлечь пару Base64-хэшей (plain, UPPER) из структуры."""
    match = _HASH_PAIR_RE.search(structure)
    if match:
        return match.group(1), match.group(2)

    quoted = _QUOTED_HASH_RE.findall(structure)
    # Отбрасываем SHA1("") — часто соседствует с реальным хэшем пароля.
    meaningful = [item for item in quoted if item != _EMPTY_SHA1_B64]
    if len(meaningful) >= 2:
        return meaningful[0], meaningful[1]
    if len(meaningful) == 1:
        return meaningful[0], meaningful[0]
    if len(quoted) >= 2:
        return quoted[0], quoted[1]
    raise ValueError("В структуре Data не найдена пара Base64(SHA-1) хэшей")


def verify_password_details(data: bytes, password: str) -> dict[str, Any]:
    """Подробный результат проверки пароля против v8users.Data."""
    key_size, _key, structure = decode_password_structure(data)
    expected = sha1_base64(password)
    expected_upper = sha1_base64(password.upper())

    # Надёжный путь для современных больших Data: хэш встречается как отдельное поле.
    contained_plain = expected in structure
    contained_upper = expected_upper in structure
    pass_hash = ""
    pass_hash_upper = ""
    try:
        pass_hash, pass_hash_upper = extract_stored_hashes(structure)
    except ValueError:
        pass

    match_plain = contained_plain or expected in {pass_hash, pass_hash_upper}
    match_upper = contained_upper or expected_upper in {pass_hash, pass_hash_upper}
    match = match_plain or match_upper
    return {
        "key_size": key_size,
        "structure_len": len(structure),
        "structure_preview": structure[:500],
        "pass_hash": pass_hash,
        "pass_hash_upper": pass_hash_upper,
        "expected": expected,
        "expected_upper": expected_upper,
        "match_plain": match_plain,
        "match_upper": match_upper,
        "match": match,
    }


def verify_password(data: bytes, password: str) -> bool:
    """True, если пароль совпадает с хэшем в Data."""
    try:
        return bool(verify_password_details(data, password)["match"])
    except (ValueError, UnicodeError):
        return False
