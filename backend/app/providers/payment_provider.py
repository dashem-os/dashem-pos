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

class ManualOperatorPaymentProvider(BasePaymentProvider):
    def process_payment(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        method: PaymentMethodEnum,
        amount: Decimal,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str, str]:
        tx_ref = f"MANUAL-{method.value}-{uuid.uuid4().hex[:12].upper()}"
        return True, tx_ref, "Pagamento confirmado manualmente pelo operador."

payment_provider = ManualOperatorPaymentProvider()
