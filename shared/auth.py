import base64
import hashlib
import hmac
import json
import os
import time
import bcrypt

DEFAULT_SECRET = os.environ.get("NEXUS_JWT_SECRET", "nexuschat_secret_key_change_in_production_2026")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _b64url_decode(data_str: str) -> bytes:
    padding = 4 - (len(data_str) % 4)
    if padding != 4:
        data_str += "=" * padding
    return base64.urlsafe_b64decode(data_str.encode("utf-8"))


def create_jwt_token(payload: dict, secret_key: str = None, expires_in: int = 86400) -> str:
    """Create a signed HS256 JWT token."""
    secret = secret_key or DEFAULT_SECRET
    header = {"alg": "HS256", "typ": "JWT"}
    
    now = int(time.time())
    token_payload = dict(payload)
    token_payload["iat"] = now
    if "exp" not in token_payload:
        token_payload["exp"] = now + expires_in

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(token_payload, separators=(",", ":")).encode("utf-8"))

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def verify_jwt_token(token: str, secret_key: str = None) -> tuple[bool, dict]:
    """Verify a signed HS256 JWT token and return (valid, payload)."""
    if not token or not isinstance(token, str):
        return False, {}

    parts = token.split(".")
    if len(parts) != 3:
        return False, {}

    header_b64, payload_b64, signature_b64 = parts
    secret = secret_key or DEFAULT_SECRET

    try:
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(signature_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return False, {}

        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        exp = payload.get("exp")
        if exp and int(time.time()) > int(exp):
            return False, {}

        return True, payload
    except Exception:
        return False, {}


def normalize_security_answer(answer: str) -> str:
    """Normalize answer string (trimmed and lowercased)."""
    return (answer or "").strip().lower()


def hash_security_answer(answer: str) -> str:
    """Hash normalized security answer using bcrypt."""
    norm = normalize_security_answer(answer)
    if not norm:
        return ""
    return bcrypt.hashpw(norm.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_security_answer(answer: str, stored_hash: str) -> bool:
    """Verify security answer against stored bcrypt hash."""
    if not answer or not stored_hash:
        return False
    norm = normalize_security_answer(answer)
    try:
        stored_bytes = stored_hash.encode("utf-8") if isinstance(stored_hash, str) else stored_hash
        return bcrypt.checkpw(norm.encode("utf-8"), stored_bytes)
    except Exception:
        return False


CONFIG_KEY = "NexusChat_Secure_Config_Key_2026"


def encrypt_config_val(plain_text: str) -> str:
    """Encrypt a config string using XOR cipher + Base64 with 'enc:' prefix."""
    if not plain_text:
        return ""
    key_bytes = CONFIG_KEY.encode("utf-8")
    data_bytes = plain_text.encode("utf-8")
    cipher_bytes = bytes([b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(data_bytes)])
    return "enc:" + base64.b64encode(cipher_bytes).decode("utf-8")


def decrypt_config_val(enc_text: str) -> str:
    """Decrypt an 'enc:' prefixed config string, returning un-encrypted string as fallback."""
    if not enc_text:
        return ""
    if not enc_text.startswith("enc:"):
        return enc_text
    try:
        raw_b64 = enc_text[4:]
        cipher_bytes = base64.b64decode(raw_b64.encode("utf-8"))
        key_bytes = CONFIG_KEY.encode("utf-8")
        plain_bytes = bytes([b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(cipher_bytes)])
        return plain_bytes.decode("utf-8")
    except Exception:
        return enc_text

