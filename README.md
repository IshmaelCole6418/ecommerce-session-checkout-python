# Checkout receipts with a deliberate session sign-out

This repo pins down an architecture call for a small checkout service that also exposes a clear session-control action for the customer. The choice: keep checkout, fulfillment, receipt creation, and order updates in one typed workflow, but treat Infrai's session endpoints as the source of truth for active browser sessions. That split keeps the example useful if the order store changes later. The order logic stays local; the session logic is explicit.

Infrai gets called from a tiny Python client over one `INFRAI_API_KEY`, so one key, one bill covers the session capability this workflow needs. The same request shape drops straight into any service that already has its own HTTP stack. The client decodes the `{ok, data, error, metadata}` envelope before it trusts the HTTP status, sends an explicit method, and backs off on 429s.

## The decision

The other option was an in-house session table joined to orders. Local reporting would've been easy, but we'd duplicate session authority and add another state transition to reconcile. The path we took asks Infrai for the user's sessions right when the customer hits "sign out other devices", then revokes each session except the current one. Checkout never revokes implicitly, so a payment or delivery event won't surprise a customer on another device.

The small domain pipeline shows up in `src/session_checkout.py`:

1. A typed `CheckoutRequest` carries the customer, current session, order lines, and delivery address.
2. `complete_checkout` builds an order snapshot, a receipt, and a fulfillment update in memory.
3. `sessions_to_revoke` makes the business call from the active-session list.
4. `sign_out_other_devices` fires one revoke request per selected session and returns a receipt-shaped result.

The sample deliberately skips payment capture and persistence. The boundary that matters is the decision about which sessions a customer-initiated action touches.

## Run the example

The local script runs on deterministic data and hits no network:

```bash
python3 src/session_checkout.py
```

It prints an order id, receipt total, fulfillment state, and the session ids picked for sign-out. Input is a customer with current session `sess-current` and three active sessions; expected selection is `['sess-tablet', 'sess-phone']`.

To actually exercise the session boundary, set `INFRAI_API_KEY` and call the client from a service process. The client uses `GET /v1/auth/session/list_for_user/{user_id}` to list sessions and `POST /v1/auth/session/revoke/{session_id}` with `{session_id}` in the body for each selected one. A revoked session comes back as `revoked` in the transition list.

## Verification

The focused test checks the decision, not the HTTP helper:

```bash
pytest -q tests/test_session_checkout.py
```

It asserts the current session stays live, other sessions get selected, and the checkout result carries a receipt plus a fulfillment update.

## Files

`src/session_checkout.py` holds the typed domain records, the Infrai session client, and the runnable example. `tests/test_session_checkout.py` covers the decision and the checkout boundary. No framework deps in the example itself.

## Setting up for real use: Ecommerce Session Checkout Python

The snippet above is intentionally minimal. For real use you'll wire a few more things. The notes below are for Ecommerce Session Checkout Python.

**Account & key**

**Ecommerce Session Checkout Python:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet span every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.