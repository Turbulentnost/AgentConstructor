"""Тесты проверки пароля 1С (v8users.Data)."""

from __future__ import annotations

from llm_proxy_service.onec.password import (
    decode_password_structure,
    encode_password_data,
    sha1_base64,
    verify_password,
    verify_password_details,
)


def _encode_data(structure: str, key: bytes = b"\x11\x22\x33\x44") -> bytes:
    """Собрать блок Data как в PasswordChanger1C EncodePasswordStructure."""
    key_size = len(key)
    payload = structure.encode("utf-8")
    out = bytearray(1 + key_size + len(payload))
    out[0] = key_size
    out[1 : 1 + key_size] = key
    for index, value in enumerate(payload):
        out[1 + key_size + index] = value ^ key[index % key_size]
    return bytes(out)


def test_sha1_base64_known_vector() -> None:
    # SHA1("password") base64
    assert sha1_base64("password") == "W6ph5Mm5Pz8GgiULbPgzG37mj9g="


def test_verify_password_match_plain_and_upper() -> None:
    password = "md641236"
    plain = sha1_base64(password)
    upper = sha1_base64(password.upper())
    structure = f'{{guid,1,1,"{plain},{upper}",0}}'
    data = _encode_data(structure)

    key_size, _, decoded = decode_password_structure(data)
    assert key_size == 4
    assert plain in decoded

    details = verify_password_details(data, password)
    assert details["match"] is True
    assert details["match_plain"] is True
    assert verify_password(data, password) is True
    assert verify_password(data, "wrong-password") is False


def test_verify_password_rejects_garbage() -> None:
    assert verify_password(b"", "x") is False
    assert verify_password(b"\x01\xff", "x") is False


def test_encode_password_data_roundtrip() -> None:
    data = encode_password_data("md641236")
    assert verify_password(data, "md641236") is True
    assert verify_password(data, "wrong") is False


def test_verify_modern_quoted_hash_fields() -> None:
    """Современный erp_pm: хэши лежат отдельными quoted-полями, не 'a,b'."""
    password = "md641236"
    plain = sha1_base64(password)
    upper = sha1_base64(password.upper())
    empty = "2jmj7l5rSw0yVb/vlWAYkK/YBwk="
    structure = (
        '{guid,"User","",0,\r\n'
        f'{{0}},1,0,1,"",0,0,"",20251222084541,2,"{empty}","{plain}",0,"",0,0,0,""'
        f',"{upper}"}}'
    )
    key = b"\x11\x22\x33\x44"
    payload = structure.encode("utf-8")
    out = bytearray(1 + len(key) + len(payload))
    out[0] = len(key)
    out[1 : 1 + len(key)] = key
    for index, value in enumerate(payload):
        out[1 + len(key) + index] = value ^ key[index % len(key)]

    assert verify_password(bytes(out), password) is True
    assert verify_password(bytes(out), "wrong") is False
