"""Writing a walk's journal to storage: `walk --journal URL` (or PUBKIT_JOURNAL_URL).

The deploy-journal/2 document is uploaded as a file of the tenant `plane`,
then the head services/OWNER/REPO/UNIT moved to it, If-Match the head's
ETag, so two walks never lose one's journal: a move another walk won is
tried once more, on the head it left. The token is PUBKIT_STORAGE_TOKEN; in
GitHub Actions, without it, the job's OIDC token for the storage's audience
(PUBKIT_STORAGE_AUDIENCE, else the URL's host), as board-publish signs in.
A laptop has neither, and writes no journal. A journal that could not be
written is said, in one line, and never fails the walk.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from typing import Any

TENANT = "plane"
# Cloudflare refuses Python's default User-Agent (error 1010).
AGENT = "pubdeploy-journal"


# A copy of pubkit's board_publish.Refused.
class Refused(Exception):
    """Storage's answer to a request it didn't carry out."""

    def __init__(self, status: int, body: bytes):
        self.status = status
        super().__init__(f"storage said {status}: {body.decode('utf-8', 'replace')[:300]}")


# A copy of pubkit's board_publish.oidc_token.
def oidc_token(audience: str) -> str:
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(f"{url}{separator}audience={urllib.parse.quote(audience)}", headers={
        "Authorization": f"Bearer {os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']}"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - GitHub's own address
        return json.load(response)["value"]


class Heads:
    """A storage tenant's files and heads, a head by its path: after pubkit's
    board_publish.Storage."""

    def __init__(self, base: str, tenant: str, token: str):
        self.base, self.tenant, self.token = base.rstrip("/"), tenant, token

    def _send(self, method: str, path: str, data: bytes | None = None,
              headers: dict | None = None) -> tuple[int, bytes, dict]:
        request = urllib.request.Request(
            f"{self.base}/{self.tenant}{path}", data=data, method=method,
            headers={"Authorization": f"Bearer {self.token}", "User-Agent": AGENT, **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - the caller's --journal
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def upload(self, document: bytes) -> str:
        boundary = uuid.uuid4().hex
        form = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="journal.json"\r\n'
                f"Content-Type: application/json\r\n\r\n").encode() + document + f"\r\n--{boundary}--\r\n".encode()
        status, body, _ = self._send("POST", "/files", form,
                                     {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        if status != 200:
            raise Refused(status, body)
        return json.loads(body)["id"]

    def head(self, path: str) -> str | None:
        status, body, headers = self._send("GET", f"/head/{path}")
        if status == 404:
            return None
        if status != 200:
            raise Refused(status, body)
        return headers.get("ETag", "").strip('"') or None

    def point(self, path: str, hash_: str, current: str | None) -> int:
        condition = {"If-Match": f'"{current}"'} if current else {"If-None-Match": "*"}
        status, body, _ = self._send("PUT", f"/head/{path}", json.dumps({"hash": hash_}).encode(),
                                     {"Content-Type": "application/json", **condition})
        if status not in (200, 412):
            raise Refused(status, body)
        return status


def token(url: str, env: Mapping[str, str]) -> str | None:
    if env.get("PUBKIT_STORAGE_TOKEN"):
        return env["PUBKIT_STORAGE_TOKEN"]
    if env.get("ACTIONS_ID_TOKEN_REQUEST_URL") and env.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN"):
        return oidc_token(env.get("PUBKIT_STORAGE_AUDIENCE") or urllib.parse.urlsplit(url).hostname or "")
    return None


def write(url: str, document: dict[str, Any], env: Mapping[str, str], storage: Any = None) -> str:
    """Write the journal; one line saying what was done, or why not."""
    service = document["service"]
    path = f"services/{service['repository'] or 'unknown/unknown'}/{service['unit']}"
    try:
        if storage is None:
            given = token(url, env)
            if given is None:
                return "deploy: no journal written: no storage token here (PUBKIT_STORAGE_TOKEN, or a GitHub Actions job's)"
            storage = Heads(url, TENANT, given)
        new = storage.upload(json.dumps(document, indent=2).encode())
        for _ in range(2):
            if storage.point(path, new, storage.head(path)) == 200:
                return f"deploy: journal {new} written, the head {path} moved to it"
        return f"deploy: journal {new} written, but the head {path} moved under it twice: it was left"
    except Refused as e:
        return f"deploy: no journal written: storage said {e}"
    except (OSError, ValueError, KeyError) as e:
        return f"deploy: no journal written: {type(e).__name__}"
