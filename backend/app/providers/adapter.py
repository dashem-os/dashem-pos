from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol
import uuid

from app.core.config import settings
from app.models.provider import ProviderTransactionStatusEnum


@dataclass(frozen=True)
class ProviderRequest:
    transaction_id: uuid.UUID
    amount: Decimal
    method: str
    correlation_id: str
    external_transaction_id: str | None = None
    test_outcome: str | None = None


@dataclass(frozen=True)
class ProviderResult:
    status: ProviderTransactionStatusEnum
    external_transaction_id: str | None = None
    nsu: str | None = None
    authorization_code: str | None = None
    acquirer: str | None = None
    card_brand: str | None = None
    failure_code: str | None = None
    failure_reason: str | None = None
    sanitized_payload: dict = field(default_factory=dict)


class PaymentProviderAdapter(Protocol):
    version: str

    def start(self, request: ProviderRequest) -> ProviderResult: ...
    def query(self, request: ProviderRequest) -> ProviderResult: ...
    def cancel(self, request: ProviderRequest) -> ProviderResult: ...
    def refund(self, request: ProviderRequest) -> ProviderResult: ...


class BridgeQueuedAdapter:
    """Production-safe bridge contract: queues work and never assumes approval."""

    version = "1.0.0"

    def start(self, request: ProviderRequest) -> ProviderResult:
        return ProviderResult(
            status=ProviderTransactionStatusEnum.PROCESSING,
            external_transaction_id=request.external_transaction_id or f"bridge-{request.transaction_id}",
            sanitized_payload={"bridge_command": "START", "correlation_id": request.correlation_id},
        )

    def query(self, request: ProviderRequest) -> ProviderResult:
        return ProviderResult(
            status=ProviderTransactionStatusEnum.UNKNOWN,
            external_transaction_id=request.external_transaction_id,
            failure_code="AWAITING_BRIDGE_RECONCILIATION",
            failure_reason="Resultado ainda não informado pelo bridge.",
        )

    def cancel(self, request: ProviderRequest) -> ProviderResult:
        return ProviderResult(status=ProviderTransactionStatusEnum.PROCESSING, external_transaction_id=request.external_transaction_id)

    def refund(self, request: ProviderRequest) -> ProviderResult:
        return ProviderResult(status=ProviderTransactionStatusEnum.PROCESSING, external_transaction_id=request.external_transaction_id)


class ContractTestAdapter:
    """Deterministic adapter available exclusively under ENVIRONMENT=test."""

    version = "test-1.0"

    def _result(self, request: ProviderRequest) -> ProviderResult:
        outcome = (request.test_outcome or "CONFIRMED").upper()
        status = ProviderTransactionStatusEnum(outcome)
        external_id = request.external_transaction_id or f"test-{request.transaction_id}"
        if status == ProviderTransactionStatusEnum.CONFIRMED:
            return ProviderResult(
                status=status, external_transaction_id=external_id,
                nsu=f"NSU{str(request.transaction_id.int)[-8:]}", authorization_code="TST123",
                acquirer="CONTRACT_TEST", card_brand="TEST",
                sanitized_payload={"contract_fixture": True},
            )
        return ProviderResult(
            status=status, external_transaction_id=external_id,
            failure_code="TEST_OUTCOME" if status == ProviderTransactionStatusEnum.FAILED else None,
            failure_reason="Resultado controlado pelo teste." if status == ProviderTransactionStatusEnum.FAILED else None,
            sanitized_payload={"contract_fixture": True},
        )

    def start(self, request: ProviderRequest) -> ProviderResult: return self._result(request)
    def query(self, request: ProviderRequest) -> ProviderResult: return self._result(request)
    def cancel(self, request: ProviderRequest) -> ProviderResult: return ProviderResult(status=ProviderTransactionStatusEnum.CANCELED, external_transaction_id=request.external_transaction_id)
    def refund(self, request: ProviderRequest) -> ProviderResult: return ProviderResult(status=ProviderTransactionStatusEnum.REFUNDED, external_transaction_id=request.external_transaction_id)


def resolve_adapter(provider_code: str) -> PaymentProviderAdapter:
    if provider_code == "CONTRACT_TEST":
        if settings.ENVIRONMENT.lower() != "test":
            raise LookupError("Test provider is unavailable outside the test environment.")
        return ContractTestAdapter()
    return BridgeQueuedAdapter()
