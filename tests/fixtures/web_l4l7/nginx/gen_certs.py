#!/usr/bin/env python3
"""
Mint a CA-signed cert pair into /etc/nginx/certs/ AND publish the CA
public cert into /shared/ so the client container can trust it.

Why a real CA chain instead of self-signed leaves?
    A naked self-signed leaf trips curl at depth=0 BEFORE the validity
    period is checked (OpenSSL error 18, X509_V_ERR_DEPTH_ZERO_SELF_SIGNED_CERT).
    The pcap then captures a generic bad_certificate alert instead of
    the certificate_expired (alert code 45) that the profile is
    designed to recognize. With a CA chain + --cacert, curl validates
    the chain successfully and only THEN notices the leaf is expired,
    producing the alert we actually want to teach the LLM about.

Files written:
    /etc/nginx/certs/ca.crt        # root CA, valid 10 years
    /etc/nginx/certs/ca.key
    /etc/nginx/certs/server.crt    # CN=server.local, valid (now-1d, now+30d)
    /etc/nginx/certs/server.key
    /etc/nginx/certs/expired.crt   # CN=tls-broken.local, EXPIRED 2020
    /etc/nginx/certs/expired.key
    /shared/ca.crt                 # bind-mounted into client container
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


CERT_DIR = Path("/etc/nginx/certs")
SHARED_DIR = Path("/shared")


def _make_keypair() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _serialize_key(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _build_ca(now: datetime) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = _make_keypair()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TraceWeaver Test CA")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=True, crl_sign=True,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _build_leaf(
    *,
    common_name: str,
    not_before: datetime,
    not_after: datetime,
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    leaf_key = _make_keypair()
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    san = x509.SubjectAlternativeName([x509.DNSName(common_name)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(san, critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    return leaf_key, cert


def _write(stem: Path, key: rsa.RSAPrivateKey, cert: x509.Certificate) -> None:
    stem.parent.mkdir(parents=True, exist_ok=True)
    (stem.parent / (stem.name + ".key")).write_bytes(_serialize_key(key))
    (stem.parent / (stem.name + ".crt")).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    os.chmod(stem.parent / (stem.name + ".key"), 0o600)


def main() -> None:
    now = datetime.now(timezone.utc)

    ca_key, ca_cert = _build_ca(now)
    _write(CERT_DIR / "ca", ca_key, ca_cert)

    server_key, server_cert = _build_leaf(
        common_name="server.local",
        not_before=now - timedelta(days=1),
        not_after=now + timedelta(days=30),
        ca_key=ca_key, ca_cert=ca_cert,
    )
    _write(CERT_DIR / "server", server_key, server_cert)

    expired_key, expired_cert = _build_leaf(
        common_name="tls-broken.local",
        not_before=datetime(2020, 1, 1, tzinfo=timezone.utc),
        not_after=datetime(2020, 2, 1, tzinfo=timezone.utc),
        ca_key=ca_key, ca_cert=ca_cert,
    )
    _write(CERT_DIR / "expired", expired_key, expired_cert)

    # Publish CA public cert into the shared volume so the client can
    # use --cacert. We deliberately do NOT publish the CA private key.
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    (SHARED_DIR / "ca.crt").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    print(f"[gen_certs] CA + server + expired written under {CERT_DIR}/", flush=True)
    print(f"[gen_certs] CA cert published at {SHARED_DIR}/ca.crt", flush=True)


if __name__ == "__main__":
    main()
