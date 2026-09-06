import hashlib
import logging
import hmac
import base64
import secrets
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.core.context import TenantContext, resolve_actor, scope_tenant_query
from app.core.tenancy import set_tenant_db_context
from app.models.negotiation import (
    PaymentIntent, PaymentIntentStatusEnum, PaymentIntentRefundStatusEnum,
    SettlementDivergenceKindEnum,
)
from app.models.identity import OperationalSession, OperationalSessionStatusEnum, RoleEnum, Register
from app.models.payment import PaymentMethodEnum
from app.models.device import OperationalDevice, OperationalDeviceStatusEnum, OperationalDeviceTypeEnum
from app.models.provider import (
    BridgeTerminalStatusEnum, PaymentProviderConfiguration,
    PaymentDeviceBinding, PaymentDeviceBindingStatusEnum, PaymentDeviceExecutionModeEnum,
    ProviderConfigurationStatusEnum, ProviderTransaction,
    ProviderTransactionEvent, ProviderTransactionStatusEnum, TefBridgeTerminal,
)
from app.providers.adapter import ProviderRequest, ProviderResult, resolve_adapter
from app.services import negotiation_service, payment_audit_service, reliability_service


logger = logging.getLogger("dashem_pos.provider")
CARD_METHODS = {PaymentMethodEnum.CREDIT_CARD, PaymentMethodEnum.DEBIT_CARD}
RECONCILABLE = {
    ProviderTransactionStatusEnum.CREATED,
    ProviderTransactionStatusEnum.PROCESSING,
    ProviderTransactionStatusEnum.UNKNOWN,
}


def _actor(context: TenantContext, actor_id: Optional[uuid.UUID]) -> uuid.UUID:
    return resolve_actor(context, actor_id)


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _event(session: Session, transaction: ProviderTransaction, actor_id: uuid.UUID, event_type: str, payload: dict) -> None:
    session.add(ProviderTransactionEvent(
        tenant_id=transaction.tenant_id, provider_transaction_id=transaction.id,
        event_type=event_type, actor_id=actor_id, payload=payload,
    ))
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=transaction.tenant_id, store_id=transaction.store_id,
        actor_id=actor_id, action=event_type, target=f"PROVIDER-TRANSACTION-{transaction.id}",
        audit_payload=payload, aggregate_type="provider_transaction",
        aggregate_id=str(transaction.id), event_type=event_type,
        outbox_payload={"provider_transaction_id": str(transaction.id), **payload},
        correlation_id=transaction.correlation_id,
    )


def configure_provider(
    session: Session, context: TenantContext, *, store_id: uuid.UUID,
    provider_code: str, credentials_ref: Optional[str], timeout_seconds: int,
    actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> PaymentProviderConfiguration:
    if context.store_id and context.store_id != store_id:
        raise HTTPException(status_code=403, detail="Configuração fora da unidade ativa.")
    code = provider_code.strip().upper()
    if code == "CONTRACT_TEST" and settings.ENVIRONMENT.lower() != "test":
        raise HTTPException(status_code=422, detail="Provider de contrato existe somente em testes automatizados.")
    if code != "CONTRACT_TEST" and not credentials_ref:
        raise HTTPException(status_code=422, detail="Informe a referência segura das credenciais homologadas.")
    actor = _actor(context, actor_id)
    payload = {"store_id": str(store_id), "provider_code": code, "credentials_ref": credentials_ref, "timeout_seconds": timeout_seconds}
    cached, _, body = reliability_service.check_idempotency(
        session, context.tenant_id, actor, "provider.configure", idempotency_key, payload,
    )
    if cached and body:
        return session.get(PaymentProviderConfiguration, uuid.UUID(body["configuration_id"]))
    configuration = session.exec(select(PaymentProviderConfiguration).where(
        PaymentProviderConfiguration.tenant_id == context.tenant_id,
        PaymentProviderConfiguration.store_id == store_id,
        PaymentProviderConfiguration.provider_code == code,
    ).with_for_update()).first()
    if not configuration:
        configuration = PaymentProviderConfiguration(
            tenant_id=context.tenant_id, store_id=store_id, provider_code=code,
            configured_by=actor,
        )
        session.add(configuration)
    configuration.credentials_ref = credentials_ref
    configuration.timeout_seconds = timeout_seconds
    configuration.status = ProviderConfigurationStatusEnum.ACTIVE
    configuration.updated_at = datetime.utcnow()
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=store_id,
        actor_id=actor, action="payment.provider.configured",
        target=f"PAYMENT-PROVIDER-{configuration.id}",
        audit_payload={"provider_code": code, "credentials_present": bool(credentials_ref)},
        aggregate_type="payment_provider_configuration", aggregate_id=str(configuration.id),
        event_type="payment.provider.configured",
        outbox_payload={"provider_code": code, "status": configuration.status.value},
    )
    session.commit(); session.refresh(configuration)
    reliability_service.save_idempotency_record(
        session, context.tenant_id, actor, "provider.configure", idempotency_key,
        payload, 200, {"configuration_id": str(configuration.id)},
    )
    session.commit()
    return configuration


def list_configurations(session: Session, context: TenantContext) -> list[PaymentProviderConfiguration]:
    return list(session.exec(scope_tenant_query(
        select(PaymentProviderConfiguration).order_by(PaymentProviderConfiguration.provider_code),
        PaymentProviderConfiguration, context,
    )).all())


def list_payment_device_bindings(
    session: Session, context: TenantContext, register_id: Optional[uuid.UUID] = None,
) -> list[PaymentDeviceBinding]:
    query = select(PaymentDeviceBinding).order_by(PaymentDeviceBinding.created_at.desc())
    if register_id:
        query = query.where(PaymentDeviceBinding.register_id == register_id)
    return list(session.exec(scope_tenant_query(query, PaymentDeviceBinding, context)).all())


def bind_payment_device(
    session: Session, context: TenantContext, *, store_id: uuid.UUID, register_id: uuid.UUID,
    operational_device_id: uuid.UUID, provider_configuration_id: uuid.UUID,
    execution_mode: PaymentDeviceExecutionModeEnum, tef_bridge_terminal_id: Optional[uuid.UUID],
    external_device_reference: Optional[str], actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> PaymentDeviceBinding:
    """Create the only permitted route between a POS and card execution."""
    if context.store_id and context.store_id != store_id:
        raise HTTPException(status_code=403, detail="Vínculo fora da unidade ativa.")
    actor = _actor(context, actor_id)
    device = session.exec(select(OperationalDevice).where(
        OperationalDevice.id == operational_device_id,
        OperationalDevice.tenant_id == context.tenant_id,
        OperationalDevice.store_id == store_id,
    ).with_for_update()).first()
    register = session.exec(select(Register).where(
        Register.id == register_id, Register.tenant_id == context.tenant_id,
        Register.store_id == store_id, Register.is_active.is_(True),
    )).first()
    configuration = session.exec(select(PaymentProviderConfiguration).where(
        PaymentProviderConfiguration.id == provider_configuration_id,
        PaymentProviderConfiguration.tenant_id == context.tenant_id,
        PaymentProviderConfiguration.store_id == store_id,
        PaymentProviderConfiguration.status == ProviderConfigurationStatusEnum.ACTIVE,
    )).first()
    if not device or not register or not configuration:
        raise HTTPException(status_code=404, detail="POS, caixa ou provider não pertencem à unidade ativa.")
    if (
        device.device_type != OperationalDeviceTypeEnum.POS
        or device.status != OperationalDeviceStatusEnum.ACTIVE
        or device.register_id != register.id
    ):
        raise HTTPException(status_code=422, detail="O vínculo de pagamento exige um POS ativo ligado ao mesmo caixa.")

    external_reference = (external_device_reference or "").strip() or None
    terminal: Optional[TefBridgeTerminal] = None
    if execution_mode == PaymentDeviceExecutionModeEnum.TEF_BRIDGE:
        if not tef_bridge_terminal_id:
            raise HTTPException(status_code=422, detail="TEF Bridge exige um bridge pareado ao caixa.")
        terminal = session.exec(select(TefBridgeTerminal).where(
            TefBridgeTerminal.id == tef_bridge_terminal_id,
            TefBridgeTerminal.tenant_id == context.tenant_id,
            TefBridgeTerminal.store_id == store_id,
            TefBridgeTerminal.register_id == register.id,
            TefBridgeTerminal.provider_configuration_id == configuration.id,
        )).first()
        if not terminal:
            raise HTTPException(status_code=409, detail="Bridge TEF não corresponde ao provider, POS e caixa informados.")
        if external_reference:
            raise HTTPException(status_code=422, detail="TEF Bridge não aceita uma referência externa de SmartPOS.")
    else:
        if tef_bridge_terminal_id:
            raise HTTPException(status_code=422, detail="SmartPOS não pode reutilizar o bridge TEF.")
        if not external_reference:
            raise HTTPException(status_code=422, detail="Informe a referência de pareamento real do SmartPOS.")

    payload = {
        "store_id": str(store_id), "register_id": str(register_id),
        "operational_device_id": str(operational_device_id),
        "provider_configuration_id": str(provider_configuration_id),
        "execution_mode": execution_mode.value,
        "tef_bridge_terminal_id": str(tef_bridge_terminal_id) if tef_bridge_terminal_id else None,
        "external_device_reference": external_reference,
    }
    cached, _, body = reliability_service.check_idempotency(
        session, context.tenant_id, actor, "provider.device_binding.create", idempotency_key, payload,
    )
    if cached and body:
        existing = session.get(PaymentDeviceBinding, uuid.UUID(body["payment_device_binding_id"]))
        if existing and existing.tenant_id == context.tenant_id:
            return existing
        raise HTTPException(status_code=409, detail="O vínculo anterior não está mais disponível.")
    binding = session.exec(select(PaymentDeviceBinding).where(
        PaymentDeviceBinding.tenant_id == context.tenant_id,
        PaymentDeviceBinding.operational_device_id == device.id,
    ).with_for_update()).first()
    if binding:
        if binding.status == PaymentDeviceBindingStatusEnum.REVOKED:
            raise HTTPException(status_code=409, detail="Vínculo revogado não pode ser reutilizado; crie novo pareamento.")
        binding.register_id = register.id
        binding.provider_configuration_id = configuration.id
        binding.tef_bridge_terminal_id = terminal.id if terminal else None
        binding.execution_mode = execution_mode
        binding.external_device_reference = external_reference
        binding.status = PaymentDeviceBindingStatusEnum.ACTIVE
        binding.paused_reason = None
        binding.updated_at = datetime.utcnow()
    else:
        binding = PaymentDeviceBinding(
            tenant_id=context.tenant_id, store_id=store_id, register_id=register.id,
            operational_device_id=device.id, provider_configuration_id=configuration.id,
            tef_bridge_terminal_id=terminal.id if terminal else None,
            execution_mode=execution_mode, external_device_reference=external_reference,
            configured_by=actor,
        )
        session.add(binding)
        session.flush()
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=store_id, actor_id=actor,
        action="payment.device_binding.configured", target=f"PAYMENT-DEVICE-BINDING-{binding.id}",
        audit_payload={**payload, "binding_id": str(binding.id)},
        aggregate_type="payment_device_binding", aggregate_id=str(binding.id),
        event_type="payment.device_binding.configured",
        outbox_payload={"payment_device_binding_id": str(binding.id), "execution_mode": execution_mode.value},
    )
    session.commit(); session.refresh(binding)
    reliability_service.save_idempotency_record(
        session, context.tenant_id, actor, "provider.device_binding.create", idempotency_key,
        payload, 200, {"payment_device_binding_id": str(binding.id)},
    )
    session.commit()
    return binding


def update_payment_device_binding(
    session: Session, context: TenantContext, binding_id: uuid.UUID, *,
    status: PaymentDeviceBindingStatusEnum, reason: str, actor_id: Optional[uuid.UUID],
) -> PaymentDeviceBinding:
    binding = session.exec(scope_tenant_query(select(PaymentDeviceBinding).where(
        PaymentDeviceBinding.id == binding_id,
    ), PaymentDeviceBinding, context).with_for_update()).first()
    if not binding:
        raise HTTPException(status_code=404, detail="Vínculo de pagamento não encontrado.")
    actor = _actor(context, actor_id)
    if binding.status == PaymentDeviceBindingStatusEnum.REVOKED and status != PaymentDeviceBindingStatusEnum.REVOKED:
        raise HTTPException(status_code=409, detail="Vínculo revogado não pode ser reativado; faça um novo pareamento.")
    binding.status = status
    binding.paused_reason = reason.strip()[:500] if status != PaymentDeviceBindingStatusEnum.ACTIVE else None
    binding.updated_at = datetime.utcnow()
    reliability_service.write_audit_and_outbox(
        session=session, tenant_id=context.tenant_id, store_id=binding.store_id, actor_id=actor,
        action="payment.device_binding.updated", target=f"PAYMENT-DEVICE-BINDING-{binding.id}",
        audit_payload={"status": status.value, "reason": reason.strip()},
        aggregate_type="payment_device_binding", aggregate_id=str(binding.id),
        event_type="payment.device_binding.updated",
        outbox_payload={"payment_device_binding_id": str(binding.id), "status": status.value},
    )
    session.commit(); session.refresh(binding)
    return binding


def _resolve_execution_binding(
    session: Session, context: TenantContext, *, payment_device_binding_id: uuid.UUID,
    store_id: uuid.UUID,
) -> tuple[PaymentDeviceBinding, PaymentProviderConfiguration, OperationalDevice, Optional[TefBridgeTerminal]]:
    binding = session.exec(scope_tenant_query(select(PaymentDeviceBinding).where(
        PaymentDeviceBinding.id == payment_device_binding_id,
        PaymentDeviceBinding.store_id == store_id,
        PaymentDeviceBinding.status == PaymentDeviceBindingStatusEnum.ACTIVE,
    ), PaymentDeviceBinding, context).with_for_update()).first()
    if not binding:
        raise HTTPException(status_code=409, detail="Nenhum vínculo de pagamento ativo atende esta unidade.")
    device = session.exec(select(OperationalDevice).where(
        OperationalDevice.id == binding.operational_device_id,
        OperationalDevice.tenant_id == context.tenant_id,
        OperationalDevice.store_id == store_id,
        OperationalDevice.register_id == binding.register_id,
        OperationalDevice.device_type == OperationalDeviceTypeEnum.POS,
        OperationalDevice.status == OperationalDeviceStatusEnum.ACTIVE,
    )).first()
    configuration = session.exec(select(PaymentProviderConfiguration).where(
        PaymentProviderConfiguration.id == binding.provider_configuration_id,
        PaymentProviderConfiguration.tenant_id == context.tenant_id,
        PaymentProviderConfiguration.store_id == store_id,
        PaymentProviderConfiguration.status == ProviderConfigurationStatusEnum.ACTIVE,
    )).first()
    if not device or not configuration:
        raise HTTPException(status_code=409, detail="O vínculo de pagamento perdeu seu POS ou provider ativo.")
    if context.auth_provider == "operational" or context.role in {
        RoleEnum.SUPERVISOR, RoleEnum.CASHIER, RoleEnum.OPERATOR,
    }:
        if not context.operational_session_id or not context.device_id or not context.register_id:
            raise HTTPException(status_code=403, detail="Pagamento físico exige um turno operacional persistido.")
        authority = session.get(OperationalSession, context.operational_session_id)
        if (
            not authority or authority.status != OperationalSessionStatusEnum.ACTIVE
            or authority.tenant_id != context.tenant_id or authority.store_id != store_id
            or authority.user_id != context.user_id or authority.device_id != device.id
            or authority.register_id != binding.register_id
            or context.device_id != device.id or context.register_id != binding.register_id
        ):
            raise HTTPException(
                status_code=403,
                detail="O turno operacional não pertence ao POS e caixa vinculados ao pagamento.",
            )
    if binding.execution_mode == PaymentDeviceExecutionModeEnum.SMARTPOS:
        raise HTTPException(
            status_code=409,
            detail="SmartPOS está vinculado, mas não possui adapter homologado para execução. Use outro meio ou conclua a homologação.",
        )
    terminal = session.exec(select(TefBridgeTerminal).where(
        TefBridgeTerminal.id == binding.tef_bridge_terminal_id,
        TefBridgeTerminal.tenant_id == context.tenant_id,
        TefBridgeTerminal.store_id == store_id,
        TefBridgeTerminal.register_id == binding.register_id,
        TefBridgeTerminal.provider_configuration_id == configuration.id,
    )).first()
    if not terminal:
        raise HTTPException(status_code=409, detail="O vínculo TEF não possui bridge válido para este POS e caixa.")
    if terminal.status != BridgeTerminalStatusEnum.ONLINE:
        raise HTTPException(status_code=503, detail="Bridge TEF offline; os demais meios continuam disponíveis.")
    return binding, configuration, device, terminal


def pair_terminal(
    session: Session, context: TenantContext, *, store_id: uuid.UUID,
    register_id: uuid.UUID, provider_configuration_id: uuid.UUID,
    terminal_code: str, actor_id: Optional[uuid.UUID], idempotency_key: str,
) -> tuple[TefBridgeTerminal, str]:
    if context.store_id and context.store_id != store_id:
        raise HTTPException(status_code=403, detail="Terminal fora da unidade ativa.")
    register = session.exec(select(Register).where(
        Register.id == register_id, Register.tenant_id == context.tenant_id,
        Register.store_id == store_id, Register.is_active.is_(True),
    )).first()
    configuration = session.exec(select(PaymentProviderConfiguration).where(
        PaymentProviderConfiguration.id == provider_configuration_id,
        PaymentProviderConfiguration.tenant_id == context.tenant_id,
        PaymentProviderConfiguration.store_id == store_id,
        PaymentProviderConfiguration.status == ProviderConfigurationStatusEnum.ACTIVE,
    )).first()
    if not register or not configuration:
        raise HTTPException(status_code=404, detail="Caixa ou configuração de provider não encontrados.")
    actor = _actor(context, actor_id)
    payload = {
        "store_id": str(store_id), "register_id": str(register_id),
        "provider_configuration_id": str(provider_configuration_id), "terminal_code": terminal_code,
    }
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"bridge-pair:{context.tenant_id}:{idempotency_key}".encode("utf-8"), hashlib.sha256,
    ).digest()
    secret = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    cached, _, body = reliability_service.check_idempotency(
        session, context.tenant_id, actor, "provider.bridge.pair", idempotency_key, payload,
    )
    if cached and body:
        terminal = session.get(TefBridgeTerminal, uuid.UUID(body["terminal_id"]))
        if not terminal:
            raise HTTPException(status_code=409, detail="Resultado anterior do pareamento não está mais disponível.")
        return terminal, secret
    terminal = session.exec(select(TefBridgeTerminal).where(
        TefBridgeTerminal.tenant_id == context.tenant_id,
        TefBridgeTerminal.store_id == store_id,
        TefBridgeTerminal.register_id == register_id,
    ).with_for_update()).first()
    if not terminal:
        terminal = TefBridgeTerminal(
            tenant_id=context.tenant_id, store_id=store_id, register_id=register_id,
            provider_configuration_id=configuration.id, terminal_code=terminal_code,
            pairing_secret_hash=_hash_secret(secret), paired_by=actor,
        )
        session.add(terminal)
    else:
        terminal.provider_configuration_id = configuration.id
        terminal.terminal_code = terminal_code
        terminal.pairing_secret_hash = _hash_secret(secret)
        terminal.status = BridgeTerminalStatusEnum.UNPAIRED
        terminal.paired_by = actor
        terminal.updated_at = datetime.utcnow()
    session.commit(); session.refresh(terminal)
    reliability_service.save_idempotency_record(
        session, context.tenant_id, actor, "provider.bridge.pair", idempotency_key,
        payload, 200, {"terminal_id": str(terminal.id)},
    )
    session.commit()
    return terminal, secret


def _terminal_by_secret(session: Session, terminal_id: uuid.UUID, pairing_secret: str) -> TefBridgeTerminal:
    terminal = session.exec(select(TefBridgeTerminal).where(TefBridgeTerminal.id == terminal_id).with_for_update()).first()
    if not terminal or not secrets.compare_digest(terminal.pairing_secret_hash, _hash_secret(pairing_secret)):
        raise HTTPException(status_code=401, detail="Credencial local do bridge inválida.")
    return terminal


def heartbeat_terminal(
    session: Session, terminal_id: uuid.UUID, *, pairing_secret: str,
    tenant_id: uuid.UUID, store_id: uuid.UUID,
    bridge_version: str, protocol_version: str, last_error_code: Optional[str],
    last_error_message: Optional[str],
) -> TefBridgeTerminal:
    set_tenant_db_context(session, tenant_id, store_id, None)
    terminal = _terminal_by_secret(session, terminal_id, pairing_secret)
    if terminal.tenant_id != tenant_id or terminal.store_id != store_id:
        raise HTTPException(status_code=401, detail="Contexto do bridge inválido.")
    if protocol_version != terminal.protocol_version:
        terminal.status = BridgeTerminalStatusEnum.DEGRADED
        terminal.last_error_code = "PROTOCOL_VERSION_MISMATCH"
        terminal.last_error_message = "Versão de protocolo incompatível."
    else:
        terminal.status = BridgeTerminalStatusEnum.ONLINE
        terminal.last_error_code = last_error_code
        terminal.last_error_message = (last_error_message or "")[:300] or None
    terminal.bridge_version = bridge_version[:40]
    terminal.last_heartbeat_at = datetime.utcnow()
    terminal.updated_at = datetime.utcnow()
    session.commit(); session.refresh(terminal)
    return terminal


def list_terminals(session: Session, context: TenantContext, register_id: Optional[uuid.UUID] = None) -> list[TefBridgeTerminal]:
    query = select(TefBridgeTerminal)
    if register_id:
        query = query.where(TefBridgeTerminal.register_id == register_id)
    terminals = list(session.exec(scope_tenant_query(query, TefBridgeTerminal, context)).all())
    stale_before = datetime.utcnow() - timedelta(seconds=90)
    changed = False
    for terminal in terminals:
        if terminal.status == BridgeTerminalStatusEnum.ONLINE and (
            not terminal.last_heartbeat_at or terminal.last_heartbeat_at < stale_before
        ):
            terminal.status = BridgeTerminalStatusEnum.OFFLINE
            changed = True
    if changed:
        session.commit()
    return terminals


def _apply_result(
    session: Session, context: TenantContext, transaction: ProviderTransaction,
    result: ProviderResult, actor_id: uuid.UUID,
) -> dict:
    # A late or out-of-order answer must never walk the transaction backwards.
    # The bridge can repeat itself, and a queued UNKNOWN can arrive after the
    # acquirer already said CONFIRMED; applying it would reopen a closed charge
    # and, with it, the parcel's reserve.
    previous_status = transaction.status
    if previous_status in negotiation_service.TERMINAL_PROVIDER:
        # Repeating an answer changes nothing, and a confirmed charge may still
        # be refunded — that is the story moving forward, not backwards.
        allowed = (
            result.status == previous_status
            or (previous_status == ProviderTransactionStatusEnum.CONFIRMED
                and result.status == ProviderTransactionStatusEnum.REFUNDED)
        )
        # A confirmation contradicting an earlier terminal answer is not a
        # regression: it means the money went through after we were told it had
        # not. The transaction still does not move, but the fact is classified
        # by what happened to the money, and the parcel logic below sees it.
        contradiction = (
            result.status == ProviderTransactionStatusEnum.CONFIRMED
            and previous_status != ProviderTransactionStatusEnum.CONFIRMED
        )
        if not allowed and not contradiction:
            intent = session.exec(select(PaymentIntent).where(
                PaymentIntent.id == transaction.payment_intent_id,
                PaymentIntent.tenant_id == context.tenant_id,
            )).first()
            if intent is not None:
                negotiation_service.record_divergence(
                    session, intent, kind=SettlementDivergenceKindEnum.STATE_REGRESSION_REFUSED,
                    provider_status=result.status.value, transaction_id=transaction.id,
                    detail=(
                        f"Resposta {result.status.value} chegou depois de {previous_status.value}; "
                        "a transação não retrocede."
                    ),
                )
            transaction.last_queried_at = datetime.utcnow()
            session.commit()
            return {
                "transaction": transaction,
                "negotiation": negotiation_service.projection(
                    session, context, intent.negotiation_id, validate=False,
                ) if intent is not None else {},
            }
    if previous_status in negotiation_service.TERMINAL_PROVIDER and result.status != previous_status and result.status != ProviderTransactionStatusEnum.REFUNDED:
        # Contradiction: keep the transaction where it is and let the parcel
        # logic below record what the money did.
        transaction.last_queried_at = datetime.utcnow()
    else:
        transaction.status = result.status
    transaction.external_transaction_id = result.external_transaction_id
    transaction.nsu = result.nsu
    transaction.authorization_code = result.authorization_code
    transaction.acquirer = result.acquirer
    transaction.card_brand = result.card_brand
    transaction.sanitized_payload = result.sanitized_payload
    transaction.failure_code = result.failure_code
    transaction.failure_reason = result.failure_reason
    transaction.updated_at = datetime.utcnow()
    transaction.last_queried_at = datetime.utcnow()
    if result.status in {
        ProviderTransactionStatusEnum.CONFIRMED, ProviderTransactionStatusEnum.FAILED,
        ProviderTransactionStatusEnum.CANCELED, ProviderTransactionStatusEnum.REFUNDED,
    }:
        transaction.completed_at = datetime.utcnow()
    intent = session.exec(select(PaymentIntent).where(
        PaymentIntent.id == transaction.payment_intent_id,
        PaymentIntent.tenant_id == context.tenant_id,
    ).with_for_update()).first()
    if not intent:
        raise HTTPException(status_code=404, detail="Parcela vinculada não encontrada.")
    if result.status in {ProviderTransactionStatusEnum.PROCESSING, ProviderTransactionStatusEnum.UNKNOWN}:
        intent.status = PaymentIntentStatusEnum.PROCESSING
        intent.updated_at = datetime.utcnow()
    _event(session, transaction, actor_id, "payment.provider.result", {
        "status": result.status.value, "payment_intent_id": str(intent.id),
        "external_transaction_id": result.external_transaction_id,
        "failure_code": result.failure_code,
    })
    payment_audit_service.record_execution_result(
        session, context, transaction=transaction, intent=intent, actor_id=actor_id,
        outcome=result.status,
        payload={
            "external_transaction_id": result.external_transaction_id,
            "failure_code": result.failure_code,
        },
    )
    session.commit()
    # What the provider said, applied to the parcel — or written down when it
    # can no longer be applied. Before S25.1 only CONFIRMED and FAILED had a
    # destination; CANCELED and REFUNDED fell through and left the reserve held
    # forever, and a result arriving after the parcel closed was simply lost.
    divergence = None
    if result.status == ProviderTransactionStatusEnum.CONFIRMED:
        if intent.status == PaymentIntentStatusEnum.CONFIRMED:
            negotiation = negotiation_service.projection(session, context, intent.negotiation_id, validate=False)
        elif intent.status in negotiation_service.OPEN_INTENTS:
            negotiation = negotiation_service.confirm_intent(
                session, context, intent.id, actor_id=actor_id,
                idempotency_key=f"provider-confirm-{transaction.id}", external=True,
            )
        else:
            # The money went through after the parcel was cancelled or failed.
            # Confirming now could charge a line somebody else has since paid;
            # discarding would lose a real payment. It waits for a person.
            divergence = negotiation_service.record_divergence(
                session, intent, kind=SettlementDivergenceKindEnum.LATE_CONFIRMATION,
                provider_status=result.status.value, transaction_id=transaction.id,
                detail="Provider confirmou depois de a parcela ter sido encerrada.",
            )
            negotiation = negotiation_service.projection(session, context, intent.negotiation_id, validate=False)
    elif result.status == ProviderTransactionStatusEnum.FAILED:
        if intent.status in negotiation_service.OPEN_INTENTS:
            negotiation = negotiation_service.fail_intent(
                session, context, intent.id, failure_code=result.failure_code or "PROVIDER_FAILED",
                reason=result.failure_reason or "Provider recusou a transação.", actor_id=actor_id,
                idempotency_key=f"provider-fail-{transaction.id}", external=True,
            )
        else:
            if intent.status == PaymentIntentStatusEnum.CONFIRMED:
                divergence = negotiation_service.record_divergence(
                    session, intent, kind=SettlementDivergenceKindEnum.LATE_FAILURE,
                    provider_status=result.status.value, transaction_id=transaction.id,
                    detail="Provider recusou uma transação cuja parcela já estava confirmada.",
                )
            negotiation = negotiation_service.projection(session, context, intent.negotiation_id, validate=False)
    elif result.status == ProviderTransactionStatusEnum.CANCELED:
        if intent.status in negotiation_service.OPEN_INTENTS:
            negotiation = negotiation_service.cancel_intent(
                session, context, intent.id,
                reason=result.failure_reason or "Cobrança cancelada no provider.",
                actor_id=actor_id, idempotency_key=f"provider-cancel-{transaction.id}",
                external=True, external_status=result.status.value,
            )
        else:
            if intent.status == PaymentIntentStatusEnum.CONFIRMED:
                # Money was taken and then cancelled outside. Releasing the
                # reserve here would silently undo a settled payment.
                divergence = negotiation_service.record_divergence(
                    session, intent, kind=SettlementDivergenceKindEnum.EXTERNAL_CANCEL_AFTER_CONFIRM,
                    provider_status=result.status.value, transaction_id=transaction.id,
                    detail="Cancelamento externo sobre parcela já confirmada; exige estorno.",
                )
            negotiation = negotiation_service.projection(session, context, intent.negotiation_id, validate=False)
    elif result.status == ProviderTransactionStatusEnum.REFUNDED:
        # A refund is never a cancelled reserve. Money left the customer and came
        # back at the acquirer, which is a movement, not an absence of one.
        #
        # Where the capture never reached this bill the line has to become
        # payable again — but closing it as *cancelled* would assert nothing was
        # ever sent, which is false. It is closed as failed, which is what it is:
        # an attempt that produced no payment here. The reversal itself is
        # recorded so it stays visible.
        declared = result.refunded_amount
        if declared is not None:
            transaction.refunded_amount = Decimal(declared)
        if intent.status in negotiation_service.OPEN_INTENTS:
            # The second review refused this one twice, and it was right both
            # times. Closing the parcel as cancelled claimed nothing was sent;
            # closing it as failed released the whole reserve on the strength of
            # a word — and a refund can be partial.
            #
            # ADR-030 changed exactly one thing: the contract now carries the
            # reversed amount. A reserve is all or nothing — it holds a whole
            # line of the bill — so only a reversal proven to be *integral*
            # closes the parcel. Anything less, or anything unquantified, is
            # held and written down, as before.
            integral = declared is not None and Decimal(declared) >= Decimal(intent.amount)
            if integral:
                negotiation_service.record_divergence(
                    session, intent, kind=SettlementDivergenceKindEnum.REFUND_WITHOUT_CAPTURE,
                    provider_status=result.status.value, transaction_id=transaction.id,
                    detail=(
                        f"Estorno integral de {declared} no provider sobre parcela ainda aberta; "
                        "nenhuma captura chegou a esta conta e a linha volta a ficar disponível."
                    ),
                )
                negotiation = negotiation_service.fail_intent(
                    session, context, intent.id, failure_code="REFUND_WITHOUT_CAPTURE",
                    reason="Estorno integral no provider antes de qualquer captura nesta conta.",
                    actor_id=actor_id, idempotency_key=f"provider-refund-{transaction.id}",
                    external=True,
                )
            else:
                divergence = negotiation_service.record_divergence(
                    session, intent, kind=SettlementDivergenceKindEnum.REFUND_WITHOUT_CAPTURE,
                    provider_status=result.status.value, transaction_id=transaction.id,
                    detail=(
                        "Estorno no provider sobre parcela ainda aberta. Sem evidência de reversão "
                        "integral, o saldo do item permanece reservado até conciliação."
                    ),
                )
                negotiation = negotiation_service.projection(session, context, intent.negotiation_id, validate=False)
        elif negotiation_service.settle_provider_reversal(
            session, context, intent, transaction=transaction,
            declared=declared, actor_id=actor_id,
        ):
            # O valor voltou e foi provado: o estorno tem onde pousar (ADR-030).
            negotiation = negotiation_service.projection(session, context, intent.negotiation_id, validate=False)
        else:
            divergence = negotiation_service.record_divergence(
                session, intent, kind=SettlementDivergenceKindEnum.REFUND_REQUIRES_REVERSAL,
                provider_status=result.status.value, transaction_id=transaction.id,
                detail=(
                    "Estorno no provider sobre parcela confirmada, sem valor revertido declarado; "
                    "baixa financeira exige valor comprovado."
                ),
            )
            negotiation = negotiation_service.projection(session, context, intent.negotiation_id, validate=False)
    else:
        negotiation = negotiation_service.projection(session, context, intent.negotiation_id, validate=False)
    if divergence is not None:
        session.commit()
    terminal = session.get(TefBridgeTerminal, transaction.bridge_terminal_id) if transaction.bridge_terminal_id else None
    if terminal:
        terminal.last_operation_at = datetime.utcnow()
        terminal.last_error_code = result.failure_code
        terminal.last_error_message = result.failure_reason
        session.commit()
    session.refresh(transaction)
    return {"transaction": transaction, "negotiation": negotiation}


def execute_transaction(
    session: Session, context: TenantContext, *, payment_intent_id: uuid.UUID,
    payment_device_binding_id: uuid.UUID,
    actor_id: Optional[uuid.UUID], idempotency_key: str,
    correlation_id: Optional[str], test_outcome: Optional[str],
) -> dict:
    actor = _actor(context, actor_id)
    intent = session.exec(scope_tenant_query(select(PaymentIntent).where(
        PaymentIntent.id == payment_intent_id,
    ).with_for_update(), PaymentIntent, context)).first()
    if not intent or intent.method not in CARD_METHODS:
        raise HTTPException(status_code=422, detail="TEF exige uma parcela de cartão válida.")
    binding, configuration, device, terminal = _resolve_execution_binding(
        session, context, payment_device_binding_id=payment_device_binding_id,
        store_id=intent.store_id,
    )
    payload = {
        "payment_intent_id": str(payment_intent_id),
        "payment_device_binding_id": str(binding.id), "actor_id": str(actor),
    }
    request_hash = reliability_service.compute_request_hash(payload)
    existing = session.exec(select(ProviderTransaction).where(
        ProviderTransaction.tenant_id == context.tenant_id,
        ProviderTransaction.idempotency_key == idempotency_key,
    )).first()
    if existing:
        if existing.request_hash != request_hash:
            raise HTTPException(status_code=409, detail="Idempotency-Key reutilizada com payload diferente.")
        return reconcile_transaction(session, context, existing.id, actor_id=actor, test_outcome=test_outcome)
    previous = session.exec(select(ProviderTransaction).where(
        ProviderTransaction.tenant_id == context.tenant_id,
        ProviderTransaction.payment_intent_id == payment_intent_id,
        ProviderTransaction.status.in_(list(RECONCILABLE)),
    ).order_by(ProviderTransaction.created_at.desc())).first()
    if previous:
        return reconcile_transaction(session, context, previous.id, actor_id=actor, test_outcome=test_outcome)
    # Only here, after the idempotent replay and the in-flight reconciliation,
    # does a *new* charge get considered — so retries and queries keep working
    # while a closed parcel can never be sent to a card machine again.
    if intent.status not in negotiation_service.OPEN_INTENTS:
        raise HTTPException(status_code=409, detail={
            "code": "INTENT_NOT_EXECUTABLE",
            "message": "Parcela cancelada, expirada ou já concluída não pode gerar nova cobrança.",
            "payment_intent_id": str(intent.id), "intent_status": intent.status.value,
        })
    settled = session.exec(select(ProviderTransaction).where(
        ProviderTransaction.tenant_id == context.tenant_id,
        ProviderTransaction.payment_intent_id == intent.id,
        ProviderTransaction.status.in_([
            ProviderTransactionStatusEnum.CONFIRMED, ProviderTransactionStatusEnum.REFUNDED,
        ]),
    )).first()
    if settled is not None:
        raise HTTPException(status_code=409, detail={
            "code": "CHARGE_ALREADY_SETTLED",
            "message": "Esta parcela já possui cobrança concluída no provider; consulte em vez de cobrar de novo.",
            "provider_transaction_id": str(settled.id), "provider_status": settled.status.value,
        })
    try:
        adapter = resolve_adapter(configuration.provider_code)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    transaction = ProviderTransaction(
        tenant_id=context.tenant_id, store_id=intent.store_id,
        payment_intent_id=intent.id, payment_device_binding_id=binding.id,
        provider_configuration_id=configuration.id,
        bridge_terminal_id=terminal.id, provider_code=configuration.provider_code,
        adapter_version=adapter.version, correlation_id=correlation_id or str(uuid.uuid4()),
        idempotency_key=idempotency_key, request_hash=request_hash, created_by=actor,
    )
    session.add(transaction); session.flush()
    # It is leaving now, so the abandonment clock stops: from here the answer
    # comes from reconciliation, never from a timeout.
    intent.reserve_expires_at = None
    payment_audit_service.record_request_and_approval(
        session, context, transaction=transaction, intent=intent,
        binding=binding, device=device, actor_id=actor,
    )
    _event(session, transaction, actor, "payment.provider.started", {
        "payment_intent_id": str(intent.id), "provider_code": configuration.provider_code,
        "amount": str(intent.amount), "terminal_id": str(terminal.id),
    })
    session.commit(); session.refresh(transaction)
    result = adapter.start(ProviderRequest(
        transaction_id=transaction.id, amount=Decimal(intent.amount), method=intent.method.value,
        correlation_id=transaction.correlation_id, test_outcome=test_outcome,
    ))
    return _apply_result(session, context, transaction, result, actor)


def reconcile_transaction(
    session: Session, context: TenantContext, transaction_id: uuid.UUID, *,
    actor_id: Optional[uuid.UUID], test_outcome: Optional[str] = None,
) -> dict:
    actor = _actor(context, actor_id)
    transaction = session.exec(scope_tenant_query(select(ProviderTransaction).where(
        ProviderTransaction.id == transaction_id,
    ).with_for_update(), ProviderTransaction, context)).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transação do provider não encontrada.")
    if transaction.status not in RECONCILABLE:
        intent = session.get(PaymentIntent, transaction.payment_intent_id)
        return {"transaction": transaction, "negotiation": negotiation_service.projection(session, context, intent.negotiation_id, validate=False)}
    adapter = resolve_adapter(transaction.provider_code)
    intent = session.get(PaymentIntent, transaction.payment_intent_id)
    result = adapter.query(ProviderRequest(
        transaction_id=transaction.id, amount=Decimal(intent.amount), method=intent.method.value,
        correlation_id=transaction.correlation_id,
        external_transaction_id=transaction.external_transaction_id,
        test_outcome=test_outcome,
    ))
    return _apply_result(session, context, transaction, result, actor)


def report_bridge_result(
    session: Session, terminal_id: uuid.UUID, transaction_id: uuid.UUID, *,
    pairing_secret: str, tenant_id: uuid.UUID, store_id: uuid.UUID,
    status_value: ProviderTransactionStatusEnum,
    external_transaction_id: Optional[str], nsu: Optional[str], authorization_code: Optional[str],
    acquirer: Optional[str], card_brand: Optional[str], failure_code: Optional[str], failure_reason: Optional[str],
    refunded_amount: Optional[Decimal] = None,
) -> dict:
    set_tenant_db_context(session, tenant_id, store_id, None)
    terminal = _terminal_by_secret(session, terminal_id, pairing_secret)
    if terminal.tenant_id != tenant_id or terminal.store_id != store_id:
        raise HTTPException(status_code=401, detail="Contexto do bridge inválido.")
    transaction = session.exec(select(ProviderTransaction).where(
        ProviderTransaction.id == transaction_id,
        ProviderTransaction.tenant_id == terminal.tenant_id,
        ProviderTransaction.store_id == terminal.store_id,
        ProviderTransaction.bridge_terminal_id == terminal.id,
    ).with_for_update()).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Comando não pertence a este bridge.")
    # O bridge autenticado pelo segredo de pareamento é o principal sistêmico
    # desta callback. O usuário que o pareou não deve receber autoria por uma
    # operação posterior executada pelo dispositivo.
    context = TenantContext(
        tenant_id=tenant_id,
        store_id=store_id,
        user_id=terminal.id,
        auth_subject=f"service:tef-bridge:{terminal.id}",
    )
    return _apply_result(session, context, transaction, ProviderResult(
        status=status_value,
        external_transaction_id=external_transaction_id or transaction.external_transaction_id,
        nsu=nsu, authorization_code=authorization_code, acquirer=acquirer,
        card_brand=card_brand, failure_code=failure_code,
        failure_reason=(failure_reason or "")[:300] or None,
        refunded_amount=refunded_amount,
        sanitized_payload={"reported_by_bridge": True, "protocol_version": terminal.protocol_version},
    ), terminal.id)


def request_reversal(
    session: Session, context: TenantContext, transaction: ProviderTransaction,
    refund, *, actor_id: uuid.UUID,
) -> None:
    """Pedir ao adquirente que devolva o dinheiro desta cobranca (ADR-030).

    Nao abre uma segunda transacao: a reversao anda sobre a cobranca que existe,
    que e como o proprio contrato do adapter foi desenhado — `refund` recebe o
    identificador externo da transacao original. `CONFIRMED -> REFUNDED` ja era
    a unica passagem terminal permitida em `_apply_result`.

    O que esta funcao nao faz e liberar saldo. Enquanto o adquirente nao
    declarar a quantia revertida, o estorno segue pendente e a conta nao muda.
    """
    intent = session.get(PaymentIntent, transaction.payment_intent_id)
    try:
        adapter = resolve_adapter(transaction.provider_code)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _event(session, transaction, actor_id, "payment.provider.refund_requested", {
        "payment_intent_id": str(transaction.payment_intent_id),
        "payment_intent_refund_id": str(refund.id), "amount": str(refund.amount),
    })
    result = adapter.refund(ProviderRequest(
        transaction_id=transaction.id, amount=Decimal(refund.amount),
        method=intent.method.value if intent else "CREDIT_CARD",
        correlation_id=transaction.correlation_id,
        external_transaction_id=transaction.external_transaction_id,
    ))
    if result.status == ProviderTransactionStatusEnum.REFUNDED and result.refunded_amount is not None:
        # O adquirente respondeu na hora e disse quanto reverteu.
        declared = Decimal(result.refunded_amount)
        transaction.refunded_amount = declared
        transaction.status = ProviderTransactionStatusEnum.REFUNDED
        transaction.updated_at = datetime.utcnow()
        negotiation_service.mark_refund_reverted(
            session, refund, reverted=min(declared, Decimal(refund.amount)), actor=actor_id,
        )
    elif result.status == ProviderTransactionStatusEnum.FAILED:
        # Recusado: o estorno nao fica segurando dinheiro que ninguem devolveu.
        refund.status = PaymentIntentRefundStatusEnum.FAILED
        refund.failure_code = result.failure_code or "PROVIDER_REFUSED_REFUND"
        refund.failure_reason = result.failure_reason or "Provider recusou o estorno."
        refund.updated_at = datetime.utcnow()
    session.flush()


def assert_executable_binding(
    session: Session, context: TenantContext, *, payment_device_binding_id: uuid.UUID,
    store_id: uuid.UUID, method: PaymentMethodEnum,
) -> None:
    """Prove the device can execute before anybody reserves a line of the bill.

    The chain is the one ADR-022 already revalidates at execution: tenant, unit,
    register, POS, provider configuration, execution mode and — for TEF — the
    bridge paired to that register. What S25.1 adds is *when* it is asked. The
    screen used to create the parcel first and discover the bridge was offline
    afterwards, and the reserve it left behind held an item nobody could pay.
    """
    if method not in CARD_METHODS:
        raise HTTPException(status_code=422, detail="Execução por dispositivo exige parcela de cartão.")
    # `_resolve_execution_binding` is the chain ADR-022 already validates, offline
    # bridge included. Nothing is re-checked here: what changes is *when* it is
    # asked, which is before a line of the bill is held.
    _resolve_execution_binding(
        session, context, payment_device_binding_id=payment_device_binding_id, store_id=store_id,
    )


def recover_unapplied_results(session: Session, limit: int = 50) -> list[uuid.UUID]:
    """Finish applying provider answers whose parcel never heard them.

    `_apply_result` persists the transaction and only then touches the parcel,
    so a crash between the two commits leaves a CONFIRMED charge beside an open
    parcel. Nothing is re-asked of the provider here: the answer is already on
    the row, and this replays it.
    """
    recovered = []
    for transaction in negotiation_service.unapplied_results(session, limit=limit):
        # Authorship is the principal that started the charge, not an invented
        # one: the sweep finishes that person's operation (ADR-020).
        context = TenantContext(
            tenant_id=transaction.tenant_id, store_id=transaction.store_id,
            user_id=transaction.created_by,
        )
        result = ProviderResult(
            status=transaction.status,
            external_transaction_id=transaction.external_transaction_id,
            nsu=transaction.nsu, authorization_code=transaction.authorization_code,
            acquirer=transaction.acquirer, card_brand=transaction.card_brand,
            failure_code=transaction.failure_code, failure_reason=transaction.failure_reason,
            sanitized_payload=transaction.sanitized_payload,
        )
        try:
            _apply_result(session, context, transaction, result, transaction.created_by)
        except Exception:
            # One row that cannot be replayed — a broken audit chain, a scope
            # that no longer resolves — must not stop the queue behind it. Once
            # the filter moved into the query the sweep began seeing the real
            # backlog, and the oldest rows are exactly the ones most likely to
            # be damaged. It is skipped, logged, and left for a person.
            session.rollback()
            logger.warning(
                "Could not replay provider result transaction=%s status=%s",
                transaction.id, transaction.status.value, exc_info=True,
            )
            continue
        recovered.append(transaction.id)
    return recovered


def recover_transaction(session: Session, context: TenantContext, transaction_id: uuid.UUID) -> dict:
    """Replay one persisted answer onto its parcel, without asking again."""
    transaction = session.exec(scope_tenant_query(select(ProviderTransaction).where(
        ProviderTransaction.id == transaction_id,
    ).with_for_update(), ProviderTransaction, context)).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transação do provider não encontrada.")
    result = ProviderResult(
        status=transaction.status, external_transaction_id=transaction.external_transaction_id,
        nsu=transaction.nsu, authorization_code=transaction.authorization_code,
        acquirer=transaction.acquirer, card_brand=transaction.card_brand,
        failure_code=transaction.failure_code, failure_reason=transaction.failure_reason,
        sanitized_payload=transaction.sanitized_payload,
    )
    # The author of the replay is whoever is consulting: they are finishing the
    # operation, and `resolve_actor` refuses any claim that is not theirs.
    return _apply_result(session, context, transaction, result, resolve_actor(context))["negotiation"]
