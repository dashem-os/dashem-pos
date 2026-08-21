import uuid
import random
from typing import Tuple, Optional, Dict, Any
from abc import ABC, abstractmethod
from app.models.fiscal import FiscalStatusEnum, FiscalDocumentTypeEnum

class BaseFiscalGateway(ABC):
    @abstractmethod
    def issue_document(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        sale_id: uuid.UUID,
        document_type: FiscalDocumentTypeEnum,
        net_total: str,
        simulate_status: Optional[str] = None
    ) -> Tuple[FiscalStatusEnum, Optional[str], Optional[int], Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Returns (status, access_key, doc_number, xml_content, pdf_url, rejection_code, rejection_reason)"""
        pass

    @abstractmethod
    def cancel_document(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        access_key: str,
        reason: str
    ) -> Tuple[bool, Optional[str], str]:
        """Returns (success, cancellation_xml, message)"""
        pass

class FakeFiscalGateway(BaseFiscalGateway):
    def issue_document(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        sale_id: uuid.UUID,
        document_type: FiscalDocumentTypeEnum,
        net_total: str,
        simulate_status: Optional[str] = None
    ) -> Tuple[FiscalStatusEnum, Optional[str], Optional[int], Optional[str], Optional[str], Optional[str], Optional[str]]:
        if simulate_status == "REJECTED":
            return (
                FiscalStatusEnum.REJECTED,
                None,
                None,
                None,
                None,
                "539",
                "Rejeição SEFAZ: Duplicidade de NFC-e com diferença na Chave de Acesso."
            )

        # Generate 44-digit SEFAZ Access Key
        doc_num = random.randint(1000, 99999)
        access_key = f"352608{uuid.uuid4().hex[:32].upper()}{doc_num:06d}"[:44]
        xml_content = f"<NFe xmlns='http://www.portalfiscal.inf.br/nfe'><infNFe Id='NFe{access_key}'><total><vNF>{net_total}</vNF></total></infNFe></NFe>"
        pdf_url = f"https://danfe.dashem.io/v1/{access_key}.pdf"

        if simulate_status == "CONTINGENCY":
            return (
                FiscalStatusEnum.CONTINGENCY,
                access_key,
                doc_num,
                xml_content,
                pdf_url,
                None,
                None
            )

        # Default: AUTHORIZED
        return (
            FiscalStatusEnum.AUTHORIZED,
            access_key,
            doc_num,
            xml_content,
            pdf_url,
            None,
            None
        )

    def cancel_document(
        self,
        tenant_id: uuid.UUID,
        store_id: uuid.UUID,
        access_key: str,
        reason: str
    ) -> Tuple[bool, Optional[str], str]:
        cancel_xml = f"<procEventoNFe><evento><infEvento><chNFe>{access_key}</chNFe><xJust>{reason}</xJust></infEvento></evento></procEventoNFe>"
        return True, cancel_xml, f"Fiscal document '{access_key}' canceled successfully per SEFAZ protocol."

# Global singleton instance
fiscal_gateway = FakeFiscalGateway()
