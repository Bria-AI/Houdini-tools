"""HTTP client for Bria API (DCC-agnostic)."""

from __future__ import annotations

import json
import ssl
import time
import uuid
from typing import Any, Dict, Optional, Tuple

from urllib import error as url_error
from urllib import request as url_request

from .auth import build_headers
from .errors import BriaRequestError
from .logging import get_logger

logger = get_logger("bria_core.client")

_FALLBACK_RETRY_STATUS_CODES = {415, 460}


class BriaClient:
    """Stateless API client with retry/fallback encoding support."""

    def __init__(
        self,
        api_endpoint: str,
        api_key: str,
        timeout_s: int = 1200,
        use_bearer: bool = False,
        session: Optional[object] = None,
    ) -> None:
        self.api_endpoint = api_endpoint.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.use_bearer = use_bearer
        self.session = session

    def _join_url(self, suffix: str) -> str:
        base = self.api_endpoint.rstrip("/")
        tail = (suffix or "").strip()
        if not tail:
            return base
        return base + "/" + tail.lstrip("/")

    def _post_with_fallbacks(
        self,
        url: str,
        payload_json: Dict[str, Any],
        proxies: Optional[Dict[str, str]] = None,
        allow_multipart: bool = False,
        image_path: Optional[str] = None,
        mask_path: Optional[str] = None,
    ) -> Tuple["_SimpleResponse", str]:
        headers = build_headers(self.api_key, use_bearer=self.use_bearer)
        headers.setdefault("Accept", "application/json")

        attempts = []

        resp = _request_json(url, payload_json, headers=headers, timeout_s=self.timeout_s, proxies=proxies)
        attempts.append(("json", resp.status_code, resp.request_headers.get("Content-Type")))
        if resp.status_code not in _FALLBACK_RETRY_STATUS_CODES:
            resp._bria_attempts = attempts  # type: ignore[attr-defined]
            return resp, "json"

        # Retry: data-URI base64
        try:
            alt = dict(payload_json or {})
            for key in ("image", "mask"):
                v = alt.get(key)
                if isinstance(v, str) and v and not v.lower().startswith("http") and not v.lower().startswith("data:"):
                    alt[key] = f"data:image/png;base64,{v}"
            resp_alt = _request_json(url, alt, headers=headers, timeout_s=self.timeout_s, proxies=proxies)
            attempts.append(("json-datauri", resp_alt.status_code, resp_alt.request_headers.get("Content-Type")))
            if resp_alt.status_code not in _FALLBACK_RETRY_STATUS_CODES:
                resp_alt._bria_attempts = attempts  # type: ignore[attr-defined]
                return resp_alt, "json-datauri"
        except Exception as exc:
            logger.debug("Bria fallback json-datauri failed: %s", exc, exc_info=True)

        if not allow_multipart:
            resp._bria_attempts = attempts  # type: ignore[attr-defined]
            return resp, "json"

        if not image_path or not mask_path:
            resp._bria_attempts = attempts  # type: ignore[attr-defined]
            return resp, "json"

        # Multipart fallback
        mp_headers = {k: v for k, v in headers.items() if k.lower() not in ("content-type", "content-length")}
        payload_no_images = {k: v for k, v in (payload_json or {}).items() if k not in ("image", "mask")}

        try:
            resp3 = _request_multipart(
                url,
                headers=mp_headers,
                image_path=image_path,
                mask_path=mask_path,
                payload_json=payload_no_images,
                timeout_s=self.timeout_s,
                proxies=proxies,
            )
            attempts.append(("multipart-input", resp3.status_code, resp3.request_headers.get("Content-Type")))
            if resp3.status_code != 422:
                resp3._bria_attempts = attempts  # type: ignore[attr-defined]
                return resp3, "multipart-input"
        except Exception as exc:
            logger.debug("Bria fallback multipart-input failed: %s", exc, exc_info=True)

        resp._bria_attempts = attempts  # type: ignore[attr-defined]
        return resp, "multipart-input"

    def _poll_status(self, status_url: str, headers: Dict[str, str], timeout_s: int = 1200) -> Dict[str, Any]:
        t0 = time.perf_counter()
        delay = 2.0
        while True:
            if time.perf_counter() - t0 > timeout_s:
                raise BriaRequestError(f"Timed out waiting for Bria async result (status_url={status_url})")

            resp = _request_get(status_url, headers=headers, timeout_s=60)
            if resp.status_code < 200 or resp.status_code >= 300:
                raise BriaRequestError(f"Bria status check failed: HTTP {resp.status_code}")
            payload = resp.json()

            status = payload.get("status") if isinstance(payload, dict) else None
            if isinstance(status, str):
                status_l = status.lower()
                if status_l in ("completed", "complete", "succeeded", "success", "done"):
                    return payload
                if status_l in ("failed", "error"):
                    raise BriaRequestError(f"Bria async request failed: {payload}")

            if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
                if payload["result"].get("image_url"):
                    return payload

            time.sleep(delay)

    def post_image_edit(
        self,
        endpoint: str,
        payload_json: Dict[str, Any],
        proxies: Optional[Dict[str, str]] = None,
        allow_multipart: bool = False,
        image_path: Optional[str] = None,
        mask_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = self._join_url(endpoint)
        resp, mode = self._post_with_fallbacks(
            url,
            payload_json=payload_json,
            proxies=proxies,
            allow_multipart=allow_multipart,
            image_path=image_path,
            mask_path=mask_path,
        )

        if not resp.ok:
            sent_ct = None
            try:
                sent_ct = resp.request_headers.get("Content-Type")
            except Exception:
                pass

            attempts_info = ""
            try:
                attempts = getattr(resp, "_bria_attempts", None)
                if attempts:
                    attempts_info = " | attempts=" + "; ".join(f"{m}:{code}:{ct}" for (m, code, ct) in attempts)
            except Exception:
                pass

            mode_info = f" | mode={mode}" if mode else ""
            ct_info = f" | sent_content_type={sent_ct}" if sent_ct else ""
            raise BriaRequestError(
                f"Bria API Error: {resp.status_code} - {resp.text} | url={url}{mode_info}{ct_info}{attempts_info}"
            )

        data = resp.json()
        status_url = None
        if isinstance(data, dict):
            status_url = data.get("status_url") or data.get("statusUrl")

        if status_url:
            headers = build_headers(self.api_key, use_bearer=self.use_bearer)
            return self._poll_status(status_url, headers=headers, timeout_s=self.timeout_s)

        return data


class _SimpleResponse:
    def __init__(self, status_code: int, headers: Dict[str, str], body: bytes, request_headers: Dict[str, str]):
        self.status_code = status_code
        self.headers = headers
        self.body = body
        self.request_headers = request_headers

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def text(self) -> str:
        try:
            return self.body.decode("utf-8", errors="replace")
        except Exception:
            return str(self.body)

    def json(self) -> Any:
        return json.loads(self.text)


def _request_get(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout_s: int = 60,
    proxies: Optional[Dict[str, str]] = None,
) -> _SimpleResponse:
    return _request_bytes("GET", url, headers=headers, data=None, timeout_s=timeout_s, proxies=proxies)


def _request_json(
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout_s: int,
    proxies: Optional[Dict[str, str]] = None,
) -> _SimpleResponse:
    body = json.dumps(payload or {}).encode("utf-8")
    req_headers = dict(headers or {})
    req_headers.setdefault("Content-Type", "application/json")
    return _request_bytes("POST", url, headers=req_headers, data=body, timeout_s=timeout_s, proxies=proxies)


def _request_multipart(
    url: str,
    headers: Dict[str, str],
    image_path: str,
    mask_path: str,
    payload_json: Dict[str, Any],
    timeout_s: int,
    proxies: Optional[Dict[str, str]] = None,
) -> _SimpleResponse:
    boundary = f"----bria-{uuid.uuid4().hex}"
    content_type = f"multipart/form-data; boundary={boundary}"
    body = _encode_multipart(boundary, image_path, mask_path, payload_json)
    req_headers = dict(headers or {})
    req_headers["Content-Type"] = content_type
    return _request_bytes("POST", url, headers=req_headers, data=body, timeout_s=timeout_s, proxies=proxies)


def _encode_multipart(boundary: str, image_path: str, mask_path: str, payload_json: Dict[str, Any]) -> bytes:
    def _file_part(name: str, filename: str, content_type: str, data: bytes) -> bytes:
        lines = [
            f"--{boundary}",
            f"Content-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"",
            f"Content-Type: {content_type}",
            "",
        ]
        # RFC 7578 framing: headers, blank line, body, trailing CRLF.
        return "\r\n".join(lines).encode("utf-8") + b"\r\n" + data + b"\r\n"

    def _json_part(name: str, payload: Dict[str, Any]) -> bytes:
        data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        lines = [
            f"--{boundary}",
            f"Content-Disposition: form-data; name=\"{name}\"",
            "Content-Type: application/json",
            "",
        ]
        return "\r\n".join(lines).encode("utf-8") + b"\r\n" + data + b"\r\n"

    body = b""
    with open(image_path, "rb") as img_f:
        body += _file_part("image", "image.png", "image/png", img_f.read())
    with open(mask_path, "rb") as mask_f:
        body += _file_part("mask", "mask.png", "image/png", mask_f.read())

    body += _json_part("input", payload_json)
    body += f"--{boundary}--\r\n".encode("utf-8")
    return body


def _request_bytes(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]],
    data: Optional[bytes],
    timeout_s: int,
    proxies: Optional[Dict[str, str]] = None,
) -> _SimpleResponse:
    req_headers = dict(headers or {})
    req = url_request.Request(url, data=data, headers=req_headers, method=method)
    opener = _build_opener(proxies)
    try:
        with opener.open(req, timeout=timeout_s) as resp:
            status = resp.getcode()
            resp_headers = {k: v for k, v in resp.headers.items()}
            body = resp.read()
            return _SimpleResponse(status, resp_headers, body, req_headers)
    except url_error.HTTPError as exc:
        body = exc.read() if hasattr(exc, "read") else b""
        resp_headers = {k: v for k, v in getattr(exc, "headers", {}).items()}
        return _SimpleResponse(exc.code or 0, resp_headers, body, req_headers)
    except url_error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise BriaRequestError(_format_network_error(reason, url)) from exc


def _build_opener(proxies: Optional[Dict[str, str]] = None) -> url_request.OpenerDirector:
    handlers = []
    if proxies is not None:
        handlers.append(url_request.ProxyHandler(proxies))
    return url_request.build_opener(*handlers)


def _format_network_error(reason: object, url: str) -> str:
    reason_text = str(reason)
    cert_verify_failed = (
        isinstance(reason, ssl.SSLCertVerificationError)
        or "CERTIFICATE_VERIFY_FAILED" in reason_text
        or "certificate verify failed" in reason_text.lower()
    )
    if cert_verify_failed:
        return (
            "TLS certificate validation failed while connecting to Bria. "
            "This is a local/system certificate trust issue, not an API key validation error. "
            f"Endpoint: {url} | details: {reason_text}"
        )
    return f"Network error while calling Bria endpoint {url}: {reason_text}"
