import uuid
from decimal import Decimal
from typing import Tuple, Dict, Any, Optional
from abc import ABC, abstractmethod
from app.models.payment import PaymentMethodEnum

class BasePaymentProvider(ABC):
    @abstractmethod
    def process_payment(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        method: PaymentMethodEnum,
        amount: Decimal,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str, str]:
        """Returns (success, transaction_ref, message)"""
        pass

class FakePaymentProvider(BasePaymentProvider):
    def process_payment(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        method: PaymentMethodEnum,
        amount: Decimal,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str, str]:
        tx_ref = f"FAKE-TX-{method.value}-{uuid.uuid4().hex[:8].upper()}"
        return True, tx_ref, f"Payment of R$ {amount:.2f} via {method.value} approved successfully by FakePaymentProvider."

# Global singleton instance
payment_provider = FakePaymentProvider()
