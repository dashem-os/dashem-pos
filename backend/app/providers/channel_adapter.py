from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings


@dataclass(frozen=True)
class NormalizedExternalItem:
    product_id: str
    quantity: str
    modifier_ids: tuple[str, ...]
    notes: str | None


@dataclass(frozen=True)
class NormalizedExternalOrder:
    external_order_id: str
    fulfillment: str
    notes: str | None
    customer_name: str | None
    payment_origin: str | None
    items: tuple[NormalizedExternalItem, ...]


class ChannelAdapter(Protocol):
    version: str
    def validate_connection(self, merchant_external_id: str, credentials_ref: str | None) -> tuple[bool, str | None]: ...
    def normalize(self, payload: dict) -> NormalizedExternalOrder: ...


class ContractTestChannelAdapter:
    version = "test-1.0"

    def validate_connection(self, merchant_external_id: str, credentials_ref: str | None) -> tuple[bool, str | None]:
        return bool(merchant_external_id and credentials_ref), None if credentials_ref else "MISSING_CREDENTIAL_REFERENCE"

    def normalize(self, payload: dict) -> NormalizedExternalOrder:
        external_id = str(payload.get("external_order_id") or "").strip()
        raw_items = payload.get("items")
        if not external_id or not isinstance(raw_items, list) or not raw_items:
            raise ValueError("external_order_id e items são obrigatórios.")
        items = []
        for raw in raw_items:
            if not isinstance(raw, dict) or not raw.get("product_id") or float(raw.get("quantity", 0)) <= 0:
                raise ValueError("Item externo inválido.")
            items.append(NormalizedExternalItem(
                product_id=str(raw["product_id"]), quantity=str(raw["quantity"]),
                modifier_ids=tuple(str(item) for item in raw.get("modifier_ids", [])),
                notes=str(raw["notes"]) if raw.get("notes") else None,
            ))
        fulfillment = str(payload.get("fulfillment") or "DELIVERY").upper()
        if fulfillment not in {"DELIVERY", "TAKEAWAY", "COUNTER"}:
            raise ValueError("Fulfillment externo não suportado.")
        payment = payload.get("payment") if isinstance(payload.get("payment"), dict) else {}
        payment_origin = "MARKETPLACE" if payment.get("status") == "PAID_ONLINE" else None
        return NormalizedExternalOrder(
            external_order_id=external_id, fulfillment=fulfillment,
            notes=str(payload["notes"]) if payload.get("notes") else None,
            customer_name=str(payload["customer_name"]) if payload.get("customer_name") else None,
            payment_origin=payment_origin, items=tuple(items),
        )


class UnavailableExternalAdapter:
    version = "1.0.0"
    def validate_connection(self, merchant_external_id: str, credentials_ref: str | None) -> tuple[bool, str | None]:
        return False, "EXTERNAL_VALIDATION_UNAVAILABLE"
    def normalize(self, payload: dict) -> NormalizedExternalOrder:
        raise ValueError("Canal ainda não homologado/configurado.")


def resolve_channel_adapter(provider_code: str) -> ChannelAdapter:
    if provider_code == "CONTRACT_TEST":
        if settings.ENVIRONMENT.lower() != "test":
            raise LookupError("Adapter de contrato indisponível fora de testes.")
        return ContractTestChannelAdapter()
    return UnavailableExternalAdapter()
