from decimal import Decimal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.session_checkout import CheckoutRequest, OrderLine, complete_checkout, sessions_to_revoke


def test_checkout_keeps_current_device_and_prepares_order_outputs() -> None:
    request = CheckoutRequest(
        user_id="customer-42",
        current_session_id="sess-current",
        lines=(OrderLine("coffee-beans", 2, Decimal("12.50")),),
        delivery_address="18 Market Street",
    )

    selected = sessions_to_revoke(
        [
            {"session_id": "sess-current", "active": True},
            {"session_id": "sess-tablet", "active": True},
            {"session_id": "sess-old", "active": False},
        ],
        request.current_session_id,
    )
    result = complete_checkout(request)

    assert selected == ["sess-tablet"]
    assert result.receipt.total == Decimal("25.00")
    assert result.fulfillment.state == "queued"
    assert result.order_update == "receipt_created"
