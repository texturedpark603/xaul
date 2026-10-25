from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import time
import urllib.parse
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Optional

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

CLIENT_ID = "000000004424da1f"
OAUTH_SCOPE = "service::user.auth.xboxlive.com::MBI_SSL"
OAUTH_REDIRECT = "https://login.live.com/oauth20_desktop.srf"
OAUTH_AUTHORIZE_URL = "https://login.live.com/oauth20_authorize.srf"
OAUTH_TOKEN_URL = "https://login.live.com/oauth20_token.srf"

DEVICE_AUTH_URL = "https://device.auth.xboxlive.com/device/authenticate"
USER_AUTH_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_AUTH_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
SISU_AUTH_URL = "https://sisu.xboxlive.com/authorize"

RP_XBOXLIVE = "http://xboxlive.com"
RP_AUTH = "http://auth.xboxlive.com"
RP_EVENTS = "http://events.xboxlive.com"

EVENTS_RP_X5T = "9wLGzMJDNz"

_DATA_DIR = Path.home() / "Documents" / "xaul"
_AUTH_FILE = _DATA_DIR / "auth.json"

_CALLBACK_PORT = 19847

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:108.0) Gecko/20100101 Firefox/108.0",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "en-US",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def gen_ec_key():
    return ec.generate_private_key(ec.SECP256R1())


def proof_key_jwk(private_key):
    pub = private_key.public_key()
    pub_numbers = pub.public_key().public_numbers() if hasattr(pub, "public_key") else pub.public_numbers()

    def b64url(n, length=32):
        raw = n.to_bytes(length, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return {
        "crv": "P-256",
        "alg": "ES256",
        "use": "sig",
        "kty": "EC",
        "x": b64url(pub_numbers.x),
        "y": b64url(pub_numbers.y),
    }


def windows_timestamp():
    unix_ts = int(time.time())
    return (unix_ts + 11_644_473_600) * 10_000_000


def sign_request(private_key, url, token, body_str):
    ts = windows_timestamp()
    parsed = urllib.parse.urlparse(url)
    path_query = parsed.path + ("?" + parsed.query if parsed.query else "")

    policy_version = struct.pack(">I", 1)
    ts_bytes = struct.pack(">Q", ts)
    str_payload = f"POST\x00{path_query}\x00{token}\x00{body_str}\x00".encode("ascii")

    data = bytearray()
    data += policy_version
    data += b"\x00"
    data += ts_bytes
    data += b"\x00"
    data += str_payload

    der_sig = private_key.sign(bytes(data), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_sig)
    raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")

    header = policy_version + ts_bytes + raw_sig
    return base64.b64encode(header).decode()


def post_json(url, payload, extra_headers=None):
    headers = {**COMMON_HEADERS, **(extra_headers or {})}
    r = requests.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def oauth_interactive_login():
    params = {
        "client_id": CLIENT_ID,
        "scope": OAUTH_SCOPE,
        "response_type": "code",
        "redirect_uri": OAUTH_REDIRECT,
        "prompt": "select_account",
    }
    auth_url = OAUTH_AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)

    print(f"\n[auth] Opening browser for Microsoft login...")
    print(f"[auth] If the browser doesn't open, visit:\n  {auth_url}\n")
    print(f"[auth] After logging in, paste the full redirect URL here.")
    print(f"[auth] (It starts with https://login.live.com/oauth20_desktop.srf?code=...)")

    webbrowser.open(auth_url)

    redirect_url = input("\nPaste redirect URL: ").strip()

    parsed = urllib.parse.urlparse(redirect_url)
    params_parsed = urllib.parse.parse_qs(parsed.query)

    code = params_parsed.get("code", [None])[0]
    if not code:
        raise RuntimeError("No authorization code found in redirect URL.")

    token_data = {
        "client_id": CLIENT_ID,
        "scope": OAUTH_SCOPE,
        "code": code,
        "redirect_uri": OAUTH_REDIRECT,
        "grant_type": "authorization_code",
    }
    r = requests.post(
        OAUTH_TOKEN_URL,
        data=token_data,
        headers={
            "User-Agent": COMMON_HEADERS["User-Agent"],
            "Accept-Encoding": "gzip",
            "Accept-Language": "en-US",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def oauth_refresh(refresh_token):
    token_data = {
        "client_id": CLIENT_ID,
        "scope": OAUTH_SCOPE,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "redirect_uri": OAUTH_REDIRECT,
    }
    r = requests.post(
        OAUTH_TOKEN_URL,
        data=token_data,
        headers={
            "User-Agent": COMMON_HEADERS["User-Agent"],
            "Accept-Encoding": "gzip",
            "Accept-Language": "en-US",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def request_device_token(private_key):
    proof_key = proof_key_jwk(private_key)
    body = {
        "Properties": {
            "AuthMethod": "ProofOfPossession",
            "Id": "{" + str(uuid.uuid4()) + "}",
            "DeviceType": "Win32",
            "SerialNumber": "{" + str(uuid.uuid4()) + "}",
            "Version": "0.0.0",
            "ProofKey": proof_key,
        },
        "RelyingParty": RP_AUTH,
        "TokenType": "JWT",
    }
    body_str = json.dumps(body, separators=(",", ":"))
    signature = sign_request(private_key, DEVICE_AUTH_URL, "", body_str)

    headers = {**COMMON_HEADERS, "Signature": signature}
    r = requests.post(DEVICE_AUTH_URL, data=body_str, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()["Token"]


def request_sisu(private_key, access_token, device_token):
    proof_key = proof_key_jwk(private_key)
    body = {
        "AccessToken": "t=" + access_token,
        "AppId": CLIENT_ID,
        "DeviceToken": device_token,
        "Sandbox": "RETAIL",
        "UseModernGamertag": True,
        "SiteName": "user.auth.xboxlive.com",
        "RelyingParty": RP_XBOXLIVE,
        "ProofKey": proof_key,
    }
    body_str = json.dumps(body, separators=(",", ":"))
    signature = sign_request(private_key, SISU_AUTH_URL, "", body_str)

    headers = {**COMMON_HEADERS, "Signature": signature}
    r = requests.post(SISU_AUTH_URL, data=body_str, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def save_session(data):
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _AUTH_FILE.write_text(json.dumps(data, indent=2))


def load_session():
    if _AUTH_FILE.exists():
        try:
            return json.loads(_AUTH_FILE.read_text())
        except Exception:
            return None
    return None


def session_expired(session):
    expires_at = session.get("expires_at", 0)
    return time.time() >= expires_at - 300


def is_events_token(token):
    try:
        semi = token.index(";")
        jwe = token[semi + 1:]
        dot = jwe.index(".")
        header_b64 = jwe[:dot]
        padded = header_b64.replace("-", "+").replace("_", "/")
        pad_needed = (4 - len(padded) % 4) % 4
        padded += "=" * pad_needed
        header_json = base64.b64decode(padded).decode("utf-8", errors="replace")
        return EVENTS_RP_X5T in header_json
    except Exception:
        return False


class XboxAuth:
    def __init__(self):
        self._xauth: Optional[str] = None
        self._xuid: Optional[str] = None
        self._gamertag: Optional[str] = None
        self._session: Optional[dict] = None

    def ensure_authenticated(self):
        self._session = load_session()

        if self._session:
            if session_expired(self._session):
                print("[auth] Session expired — refreshing tokens...")
                try:
                    self._refresh()
                except Exception as exc:
                    print(f"[auth] Refresh failed ({exc}), re-logging in...")
                    self._login()
            else:
                print("[auth] Loaded existing session.")
                self._xauth = self._session["xauth"]
                self._xuid = self._session["xuid"]
                self._gamertag = self._session.get("gamertag", "")
        else:
            self._login()

        return self._xauth, self._xuid, self._gamertag

    def _login(self):
        print("[auth] Starting OAuth login flow...")
        ms_tokens = oauth_interactive_login()

        access_token = ms_tokens["access_token"]
        refresh_token = ms_tokens.get("refresh_token", "")
        expires_in = int(ms_tokens.get("expires_in", 3600))

        print("[auth] Got Microsoft access token. Requesting device token...")
        private_key = gen_ec_key()
        device_token = request_device_token(private_key)

        print("[auth] Requesting SISU authorization...")
        sisu = request_sisu(private_key, access_token, device_token)

        auth_token = sisu["AuthorizationToken"]
        xui_claims = auth_token["DisplayClaims"]["xui"][0]
        xsts_token = auth_token["Token"]
        user_hash = xui_claims["uhs"]
        xuid = xui_claims.get("xid", "")
        gamertag = xui_claims.get("gtg", "")

        xauth = f"XBL3.0 x={user_hash};{xsts_token}"

        session = {
            "xauth": xauth,
            "xuid": xuid,
            "gamertag": gamertag,
            "refresh_token": refresh_token,
            "expires_at": time.time() + expires_in,
        }
        save_session(session)
        self._session = session
        self._xauth = xauth
        self._xuid = xuid
        self._gamertag = gamertag

        print(f"[auth] Logged in as {gamertag} (XUID: {xuid})")

    def _refresh(self):
        refresh_token = self._session.get("refresh_token", "")
        if not refresh_token:
            raise RuntimeError("No refresh token available.")

        ms_tokens = oauth_refresh(refresh_token)
        access_token = ms_tokens["access_token"]
        new_refresh = ms_tokens.get("refresh_token", refresh_token)
        expires_in = int(ms_tokens.get("expires_in", 3600))

        private_key = gen_ec_key()
        device_token = request_device_token(private_key)
        sisu = request_sisu(private_key, access_token, device_token)

        auth_token = sisu["AuthorizationToken"]
        xui_claims = auth_token["DisplayClaims"]["xui"][0]
        xsts_token = auth_token["Token"]
        user_hash = xui_claims["uhs"]
        xuid = xui_claims.get("xid", self._session.get("xuid", ""))
        gamertag = xui_claims.get("gtg", self._session.get("gamertag", ""))

        xauth = f"XBL3.0 x={user_hash};{xsts_token}"

        session = {
            "xauth": xauth,
            "xuid": xuid,
            "gamertag": gamertag,
            "refresh_token": new_refresh,
            "expires_at": time.time() + expires_in,
        }
        save_session(session)
        self._session = session
        self._xauth = xauth
        self._xuid = xuid
        self._gamertag = gamertag
        print(f"[auth] Refreshed session for {gamertag}")

    @property
    def xauth(self):
        return self._xauth

    @property
    def xuid(self):
        return self._xuid

    @property
    def gamertag(self):
        return self._gamertag
