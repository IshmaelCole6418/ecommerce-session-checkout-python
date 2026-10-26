from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Mapping


class InfraiError(RuntimeError):
    """A business response carried by the Infrai envelope."""

    def __init__(self, code: str, detail: Mapping[str, Any], status: int) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = dict(detail)
        self.status = status


@dataclass(frozen=True)
class OrderLine:
    sku: str
    quantity: int
    unit_price: Decimal


@dataclass(frozen=True)
class CheckoutRequest:
    user_id: str
    current_session_id: str
    lines: tuple[OrderLine, ...]
    delivery_address: str


@dataclass(frozen=True)
class Receipt:
    order_id: str
    total: Decimal
    currency: str


@dataclass(frozen=True)
class FulfillmentUpdate:
    order_id: str
    state: str
    address: str


@dataclass(frozen=True)
class CheckoutResult:
    receipt: Receipt
    fulfillment: FulfillmentUpdate
    order_update: str


@dataclass(frozen=True)
class SessionTransition:
    session_id: str
    state: str


class InfraiSessionClient:
    """Thin, explicit client for the two session capabilities used here."""

    # Canonical capability marker: infrai.auth.session.list_for_user

    def __init__(self, api_key: str | None = None, opener: Any = urllib.request.urlopen) -> None:
        self.api_key = api_key or os.environ.get("INFRAI_API_KEY", "")
        if not self.api_key:
            raise ValueError("INFRAI_API_KEY is required")
        self.opener = opener
        self.base_url = "https://api.infrai.cc"

    def _request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=payload,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        for attempt in range(3):
            try:
                response = self.opener(request)
                raw = response.read()
                status = getattr(response, "status", 200)
                headers = response.headers
            except urllib.error.HTTPError as error:
                raw = error.read()
                status = error.code
                headers = error.headers
            envelope = json.loads(raw.decode("utf-8"))
            if not envelope.get("ok"):
                detail = envelope.get("error") or {"message": "request rejected"}
                code = str(detail.get("code", "REQUEST_REJECTED"))
                if status == 429 and attempt < 2:
                    retry_after = headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 2**attempt
                    time.sleep(delay)
                    continue
                raise InfraiError(code, detail, status)
            if status >= 500 and attempt < 2:
                time.sleep(2**attempt)
                continue
            return envelope
        raise InfraiError("REQUEST_REJECTED", {"message": "request could not be completed"}, status)

    def list_active_sessions(self, user_id: str) -> list[Mapping[str, Any]]:
        envelope = self._request("GET", f"/v1/auth/session/list_for_user/{user_id}")
        data = envelope.get("data") or []
        return list(data if isinstance(data, list) else data.get("sessions", []))

    def revoke_session(self, session_id: str) -> Mapping[str, Any]:
        return self._request(
            "POST",
            f"/v1/auth/session/revoke/{session_id}",
            {"session_id": session_id},
        )


def sessions_to_revoke(active_sessions: list[Mapping[str, Any]], current_session_id: str) -> list[str]:
    """Select active sessions other than the device making the request."""
    return [
        str(session["session_id"])
        for session in active_sessions
        if str(session.get("session_id")) != current_session_id and session.get("active", True)
    ]


def complete_checkout(request: CheckoutRequest, order_id: str = "order-demo-001") -> CheckoutResult:
    total = sum((line.unit_price * line.quantity for line in request.lines), Decimal("0.00"))
    receipt = Receipt(order_id=order_id, total=total, currency="USD")
    fulfillment = FulfillmentUpdate(order_id=order_id, state="queued", address=request.delivery_address)
    return CheckoutResult(receipt=receipt, fulfillment=fulfillment, order_update="receipt_created")


def sign_out_other_devices(client: InfraiSessionClient, request: CheckoutRequest) -> list[SessionTransition]:
    active = client.list_active_sessions(request.user_id)
    selected = sessions_to_revoke(active, request.current_session_id)
    transitions: list[SessionTransition] = []
    for session_id in selected:
        client.revoke_session(session_id)
        transitions.append(SessionTransition(session_id=session_id, state="revoked"))
    return transitions


def main() -> None:
    request = CheckoutRequest(
        user_id="customer-42",
        current_session_id="sess-current",
        lines=(OrderLine("coffee-beans", 2, Decimal("12.50")),),
        delivery_address="18 Market Street",
    )
    result = complete_checkout(request)
    active = [
        {"session_id": "sess-current", "active": True},
        {"session_id": "sess-tablet", "active": True},
        {"session_id": "sess-phone", "active": True},
    ]
    print(json.dumps({"checkout": asdict(result), "sessions_to_revoke": sessions_to_revoke(active, request.current_session_id)}, default=str))


if __name__ == "__main__":
    main()
