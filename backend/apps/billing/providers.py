"""Payment provider boundary. No live Ghana or card integration is registered."""

from __future__ import annotations

from apps.billing.models import Payment, PaymentStatus


class PaymentProviderError(Exception):
    def __init__(self, message: str, code: str = "not_configured"):
        super().__init__(message)
        self.code = code


class PaymentProvider:
    code = "manual"

    def start_checkout(self, *, organization, subscription, amount_minor: int, currency: str) -> Payment:
        raise PaymentProviderError("No live payment provider is configured.", "not_configured")

    def handle_webhook(self, payload: dict) -> Payment | None:
        raise PaymentProviderError("No live payment provider is configured.", "not_configured")


class ManualPaymentProvider(PaymentProvider):
    """Staff can record status later. This class does not contact a payment network."""

    code = "manual"

    def start_checkout(self, *, organization, subscription, amount_minor: int, currency: str) -> Payment:
        raise PaymentProviderError("Manual checkout is not automatic.", "not_configured")


def get_provider(code: str = "manual") -> PaymentProvider:
    if code == "manual":
        return ManualPaymentProvider()
    raise PaymentProviderError(f"Unknown payment provider '{code}'.", "unknown_provider")


def record_payment_status(*, payment: Payment, status: str, actor_user=None) -> Payment:
    if status not in PaymentStatus.values:
        raise PaymentProviderError("Unknown payment status.", "invalid_status")
    old = {"status": payment.status, "provider": payment.provider, "provider_reference": payment.provider_reference}
    payment.status = status
    payment.save(update_fields=["status", "updated_at"])
    from apps.billing.services import record_payment_status_change

    record_payment_status_change(
        organization=payment.organization,
        actor_user=actor_user,
        old_snapshot=old,
        new_snapshot={"status": payment.status, "provider": payment.provider, "provider_reference": payment.provider_reference},
    )
    return payment
