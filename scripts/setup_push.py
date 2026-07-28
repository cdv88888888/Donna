#!/usr/bin/env python3
"""Generate a VAPID keypair for phone push notifications.

Run ONCE. Prints two values — set them as the VAPID_PUBLIC_KEY and
VAPID_PRIVATE_KEY deployment secrets. The public key is also handed to the
browser as the applicationServerKey when it subscribes for push.

    python scripts/setup_push.py
"""
import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


key = ec.generate_private_key(ec.SECP256R1())

# Private key: raw 32-byte scalar, base64url (accepted by pywebpush).
priv_int = key.private_numbers().private_value
private_raw = priv_int.to_bytes(32, "big")

# Public key: uncompressed EC point (65 bytes), base64url (applicationServerKey).
public_point = key.public_key().public_bytes(
    serialization.Encoding.X962,
    serialization.PublicFormat.UncompressedPoint,
)

print("Set these as deployment secrets:\n")
print("VAPID_PUBLIC_KEY =", b64u(public_point))
print("VAPID_PRIVATE_KEY =", b64u(private_raw))
print('VAPID_SUBJECT = mailto:you@example.com   # your email')
