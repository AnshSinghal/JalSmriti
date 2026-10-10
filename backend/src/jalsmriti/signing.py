"""Digital signatures for dossiers and place reports (AWS KMS, ECDSA P-256 / SHA-256).

The private key never leaves KMS. Anyone can verify a dossier in their own browser: the verify page fetches the
public key and the signed attestation and checks the signature with WebCrypto, then hashes the PDF they drop in.
WebCrypto wants the raw r||s signature, KMS returns DER, so both forms are published.
In the local stack (no KMS) a throwaway key in .local/ is used and the dossier says so.
"""
from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache
from pathlib import Path

from . import config as C


def _der_to_raw(der: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    r, s = decode_dss_signature(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


@lru_cache(maxsize=1)
def _local_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    p = Path(os.environ.get("JALSMRITI_LOCAL_DIR", ".")) / "signing-key.pem"
    if p.exists():
        return serialization.load_pem_private_key(p.read_bytes(), password=None)
    k = ec.generate_private_key(ec.SECP256R1())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    return k


def _local() -> bool:
    return C.LOCAL or not C.KMS_KEY_ID


def sign_digest(digest: bytes) -> dict:
    """Sign a SHA-256 digest. Returns DER and raw (r||s) signatures, base64, plus the key id."""
    if _local():
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        der = _local_key().sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        kid = "local-development-key"
    else:
        import boto3
        r = boto3.client("kms", region_name=C.REGION).sign(KeyId=C.KMS_KEY_ID, Message=digest, MessageType="DIGEST",
                                                            SigningAlgorithm="ECDSA_SHA_256")
        der, kid = r["Signature"], r["KeyId"]
    return {"alg": "ECDSA_P256_SHA256", "keyId": kid, "der": base64.b64encode(der).decode(),
            "raw": base64.b64encode(_der_to_raw(der)).decode()}


@lru_cache(maxsize=1)
def public_key() -> dict:
    """SubjectPublicKeyInfo (DER, base64) and PEM of the signing key."""
    from cryptography.hazmat.primitives import serialization
    if _local():
        pub = _local_key().public_key()
        der = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        kid = "local-development-key"
    else:
        import boto3
        r = boto3.client("kms", region_name=C.REGION).get_public_key(KeyId=C.KMS_KEY_ID)
        der, kid = r["PublicKey"], r["KeyId"]
    pem = "-----BEGIN PUBLIC KEY-----\n" + "\n".join(
        base64.b64encode(der).decode()[i:i + 64] for i in range(0, len(base64.b64encode(der)), 64)) + "\n-----END PUBLIC KEY-----\n"
    return {"keyId": kid, "spki": base64.b64encode(der).decode(), "pem": pem, "alg": "ECDSA_P256_SHA256",
            "fingerprint": hashlib.sha256(der).hexdigest()[:32], "local": _local()}


def verify(digest: bytes, der_b64: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    pub = serialization.load_der_public_key(base64.b64decode(public_key()["spki"]))
    try:
        pub.verify(base64.b64decode(der_b64), digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return True
    except InvalidSignature:
        return False
