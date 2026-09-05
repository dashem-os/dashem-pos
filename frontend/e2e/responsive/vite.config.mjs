import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
const root = process.cwd();
const apiPath = path.join(root, 'src/services/api.ts');
const program = ts.createProgram([apiPath], { target: ts.ScriptTarget.ES2020, skipLibCheck: true });
const checker = program.getTypeChecker();
function sample(type, key = '', depth = 0) {
    if (depth > 9)
        return null;
    if (type.isUnion())
        return sample(type.types.find(t => !(t.flags & (ts.TypeFlags.Undefined | ts.TypeFlags.Null))) || type.types[0], key, depth + 1);
    if (type.isStringLiteral())
        return type.value;
    if (type.flags & ts.TypeFlags.String) {
        if (/_at$|_until$|date|watermark|period_|due_|reserved_for/.test(key))
            return '2026-09-04T12:00:00Z';
        if (/email/.test(key))
            return 'pessoa.com.nome.extenso@example.test';
        if (/name|label|description|reason/.test(key))
            return 'Registro de teste com nome extenso para validar a leitura em telas pequenas';
        return key === 'id' || key.endsWith('_id') ? 'fixture-id' : 'TESTE';
    }
    if (type.flags & ts.TypeFlags.Number)
        return /amount|total|price|revenue|balance/.test(key) ? 1234.56 : 1;
    if (type.flags & ts.TypeFlags.BooleanLike)
        return true;
    if (checker.isArrayType(type))
        return [];
    if (type.flags & ts.TypeFlags.Object) {
        const out = {};
        for (const prop of checker.getPropertiesOfType(type)) {
            if (prop.getName().startsWith('__'))
                continue;
            out[prop.getName()] = sample(checker.getTypeOfSymbolAtLocation(prop, prop.valueDeclaration || prop.declarations?.[0] || apiSource), prop.getName(), depth + 1);
        }
        return out;
    }
    return null;
}
const apiSource = program.getSourceFile(apiPath);
const fixtures = {};
for (const declaration of apiSource.statements) {
    if (!ts.isFunctionDeclaration(declaration) || !declaration.name)
        continue;
    const signature = checker.getSignatureFromDeclaration(declaration);
    const result = checker.getReturnTypeOfSignature(signature);
    const promised = checker.getPromisedTypeOfPromise(result);
    if (promised)
        fixtures[declaration.name.text] = sample(promised);
}
const interfaceSample = name => {
    const decl = apiSource.statements.find(d => d.name?.text === name);
    return sample(checker.getTypeAtLocation(decl));
};
const product = { ...interfaceSample('SellableProduct'), id: 'product-1', product_id: 'product-1', name: 'Produto com nome extenso para teste de responsividade', sku: 'SKU-SEM-ESPACOS-123456789012345678901234567890', item_type: 'PRODUCT', price: 1234.56, unit_price: 1234.56, quantity: 20, is_active: true, available_for_sale: true, is_sellable: true, image_url: null };
const tenant = { ...interfaceSample('PlatformTenantSummary'), id: 'tenant-1', name: 'Empresa com nome extenso para teste de responsividade', status: 'ACTIVE' };
fixtures.fetchPlatformOverview = { tenant_count: 1, active_count: 1, trial_count: 0, lead_count: 0, tenants: [tenant] };
fixtures.fetchPlatformTenantDetail = { ...fixtures.fetchPlatformTenantDetail, tenant, accesses: [], administrators: [] };
fixtures.fetchSellableProducts = { items: [product], total: 1, page: 1, page_size: 25 };
fixtures.fetchProducts = [product];
const assortment = { ...interfaceSample('Assortment'), id: 'assortment-1', status: 'ACTIVE', scopes: [], products: [] };
fixtures.fetchAssortments = { items: [assortment], total: 1 };
fixtures.getAssortment = assortment;
fixtures.fetchCustomers = [{ ...interfaceSample('Customer'), id: 'customer-1' }];
fixtures.fetchCategories = [{ ...interfaceSample('Category'), id: 'category-1', name: 'Categoria de teste', parent_id: null }];
fixtures.fetchServicePlans = [{ ...interfaceSample('ServicePlan'), id: 'plan-1', code: 'TEST', name: 'Plano de teste', is_active: true }];
fixtures.fetchOwnerNiches = [{ ...interfaceSample('OwnerNiche'), key: 'FOOD_SERVICE', name: 'Food Service' }];
fixtures.fetchProductionPoints = [{ ...interfaceSample('ProductionPoint'), id: 'point-1', name: 'Cozinha de teste' }];
fixtures.fetchProductionTickets = [{ ...interfaceSample('ProductionTicketProjection'), point: fixtures.fetchProductionPoints[0], ticket: { ...interfaceSample('ProductionTicketProjection').ticket, id: 'ticket-1', status: 'NEW' }, items: [{ ...interfaceSample('ProductionTicketItem'), product_name_snapshot: product.name, quantity: 2 }] }];
fixtures.fetchServiceTables = [{ ...interfaceSample('ServiceTable'), id: 'table-1', name: 'Mesa com identificação extensa', status: 'AVAILABLE', active_reservation: null }];
fixtures.fetchSaasInvoices = { items: [{ invoice: { ...interfaceSample('SaasInvoice'), id: 'invoice-1', status: 'OPEN', public_number: 'FAT-2026-000001' }, tenant_name: tenant.name }], total: 1 };
fixtures.fetchSaasInvoice = { ...fixtures.fetchSaasInvoice, invoice: fixtures.fetchSaasInvoices.items[0].invoice };
const merchantConnection = { ...interfaceSample('MerchantConnection'), id: 'connection-1', provider_code: 'IFOOD', merchant_external_id: 'MERCHANT-EXTERNO-0000000000001', status: 'CONNECTED', last_error_code: null };
fixtures.fetchMerchantConnections = [merchantConnection];
const channelOffer = { ...interfaceSample('ChannelCatalogOffer'), id: 'offer-1', merchant_connection_id: merchantConnection.id, product_id: product.id, product_name: product.name, product_sku: product.sku, price: 1234.56, available: true, stock_quantity: null, desired_version: 2, published_version: 1, last_publication_status: 'FAILED', provider_code: merchantConnection.provider_code, merchant_external_id: merchantConnection.merchant_external_id, connection_status: 'CONNECTED' };
fixtures.fetchChannelCatalogState = {
    offers: [channelOffer],
    batches: [{ ...interfaceSample('ChannelPublicationBatch'), id: 'batch-1', merchant_connection_id: merchantConnection.id, status: 'PARTIAL', provider_code: merchantConnection.provider_code, merchant_external_id: merchantConnection.merchant_external_id, connection_status: 'CONNECTED', items: [{ ...interfaceSample('ChannelPublicationItem'), id: 'item-1', batch_id: 'batch-1', offer_id: channelOffer.id, product_name: product.name, product_sku: product.sku, status: 'FAILED', attempt_count: 1, provider_result_ref: null, error_code: 'INVALID_CATEGORY', error_message: 'Categoria inexistente no canal, com mensagem extensa o bastante para testar a leitura em telas pequenas' }] }],
    mappings: [{ ...interfaceSample('ChannelCatalogMapping'), id: 'mapping-1', merchant_connection_id: merchantConnection.id, entity_type: 'PRODUCT', internal_id: product.id, internal_name: product.name, external_id: 'EXT-000000000000000001', provider_code: merchantConnection.provider_code, merchant_external_id: merchantConnection.merchant_external_id, connection_status: 'CONNECTED' }],
};
fixtures.fetchMarketplaceSettlements = [{ ...interfaceSample('MarketplaceSettlement'), id: 'settlement-1', merchant_connection_id: merchantConnection.id, provider_document_ref: 'DOC-2026-000001', external_order_id: 'PEDIDO-EXTERNO-0001', order_id: null, status: 'PARTIAL', gross_amount: 1234.56, commission_amount: 234.56, fee_amount: 10, promotion_amount: 0, adjustment_amount: -5, expected_net_amount: 985, paid_amount: 400, provider_code: merchantConnection.provider_code, merchant_external_id: merchantConnection.merchant_external_id, connection_status: 'CONNECTED', payments: [{ ...interfaceSample('MarketplaceSettlementPayment'), id: 'payment-1', settlement_id: 'settlement-1', provider_payment_ref: 'PAY-0001', amount: 400 }] }];
// S25: a live bill with four lines — one settled by Marcelo, one in flight with
// Astra, two still anybody's — so the three payment modes have something real
// to render at every viewport.
const orderItem = (id, name, quantity, price) => ({ ...interfaceSample('OrderItem'), id, order_id: 'order-1', product_id: `product-${id}`, product_name: name, quantity, unit_price: price, status: 'ACTIVE', production_state: 'PENDING', modifier_snapshot: [] });
const tableOrder = { ...interfaceSample('Order'), id: 'order-1', status: 'OPEN', notes: 'Comanda 1', items: [
    orderItem('item-1', 'Hambúrguer Artesanal Bacon', 1, 35), orderItem('item-2', 'Coca-Cola', 1, 10),
    orderItem('item-3', 'Whisky', 1, 40), orderItem('item-4', 'Pizza com nome extenso para leitura', 1, 60),
] };
const liveSession = { ...interfaceSample('TableSession'), id: 'session-1', service_table_id: 'table-1', kind: 'TABLE', status: 'PARTIALLY_PAID', display_label: 'Mesa 01', orders: [tableOrder], events: [], order_count: 1, active_item_count: 4, consolidated_total: 145 };
fixtures.getTableSession = liveSession;
fixtures.openTableSession = liveSession;
fixtures.fetchActiveTableSessions = [{ ...interfaceSample('TableSessionSummary'), id: 'session-1', status: 'PARTIALLY_PAID', display_label: 'Mesa 01', kind: 'TABLE', version: 3 }];
fixtures.fetchServiceTables = [{ ...interfaceSample('ServiceTableProjection'), id: 'table-1', name: 'Mesa 01', status: 'IN_SERVICE', active_session_id: 'session-1', active_session_status: 'PARTIALLY_PAID', active_session_label: 'Mesa 01', active_reservation: null, order_count: 1, item_count: 4, consolidated_total: 145 }];
const minutesAgo = (minutes) => new Date(Date.now() - minutes * 60000).toISOString().replace('Z', '');
const settlementLine = (id, name, price, settled, reserved, settledBy, reservedBy) => ({
    order_item_id: id, order_id: 'order-1', product_name: name, quantity: 1, unit_price: price,
    item_total: price, settled_amount: settled, reserved_amount: reserved,
    available_amount: price - settled - reserved, is_paid: settled >= price,
    settled_by: settledBy, reserved_by: reservedBy,
});
fixtures.openCheckoutNegotiation = {
    ...interfaceSample('CheckoutNegotiation'), id: 'negotiation-1', status: 'PARTIALLY_COVERED',
    table_session_id: 'session-1', subtotal: 145, total_due: 145, confirmed_amount: 35,
    processing_amount: 40, failed_amount: 0, remaining_amount: 110, discount_total: 0,
    surcharge_total: 0, tax_total: 0, orders: [{ id: 'no-1', order_id: 'order-1', amount_snapshot: 145 }],
    intents: [
        { ...interfaceSample('NegotiationPaymentIntent'), id: 'intent-1', method: 'PIX', status: 'CONFIRMED', amount: 35, payer_label: 'Marcelo', awaiting_provider: false, can_cancel: false, can_query_provider: false, reserve_expires_at: null, canceled_at: null, cancel_reason: null },
        // A card that left and never answered: kept, queryable, not cancellable.
        { ...interfaceSample('NegotiationPaymentIntent'), id: 'intent-2', method: 'CREDIT_CARD', status: 'PROCESSING', amount: 40, payer_label: 'Astra', created_at: minutesAgo(6), awaiting_provider: true, provider_status: 'UNKNOWN', can_cancel: false, can_query_provider: true, reserve_expires_at: null, canceled_at: null, cancel_reason: null },
        // A reserve nobody sent: cancellable, and it says how long it has sat.
        { ...interfaceSample('NegotiationPaymentIntent'), id: 'intent-3', method: 'PIX', status: 'PENDING', amount: 10, payer_label: 'Joao', created_at: minutesAgo(9), awaiting_provider: false, can_cancel: true, can_query_provider: false, reserve_expires_at: '2026-09-04T12:03:00Z', canceled_at: null, cancel_reason: null },
    ],
    allocations: [], unassigned_settled_amount: 0, unassigned_reserved_amount: 0,
    divergences: [{ id: 'div-1', payment_intent_id: 'intent-1', kind: 'REFUND_REQUIRES_REVERSAL', intent_status: 'CONFIRMED', provider_status: 'REFUNDED', amount: 35, detail: 'Estorno no provider sobre parcela confirmada; baixa financeira exige fluxo de estorno.', created_at: '2026-09-04T12:00:00Z' }],
    item_settlements: [
        settlementLine('item-1', 'Hambúrguer Artesanal Bacon', 35, 35, 0, ['Marcelo'], []),
        settlementLine('item-2', 'Coca-Cola', 10, 0, 0, [], []),
        settlementLine('item-3', 'Whisky', 40, 0, 40, [], ['Astra']),
        settlementLine('item-4', 'Pizza com nome extenso para leitura', 60, 0, 0, [], []),
    ],
};
const permissions = [...new Set(fs.readdirSync(path.join(root, 'src'), { recursive: true }).filter(p => /\.(tsx|ts)$/.test(p)).flatMap(p => [...fs.readFileSync(path.join(root, 'src', p), 'utf8').matchAll(/includes\('([a-z]+\.[a-z.]+)'\)/g)].map(m => m[1])))];
fixtures.fetchEffectiveAccess = { ...fixtures.fetchEffectiveAccess, permissions, capabilities: { kitchen_routing: {}, table_service: {}, receivables: {} } };
const fixtureData = { fixtures, product, tenant, permissions };
fs.writeFileSync(path.join(root, 'e2e/responsive/generated-fixtures.json'), JSON.stringify(fixtureData, null, 2));
const mockApi = Object.keys(fixtures).map(name => `export async function ${name}(...args) { if (window.__handlers?.['${name}']) return window.__handlers['${name}'](...args); if (window.__fixtures?.['${name}'] !== undefined) return window.__fixtures['${name}']; return fixtures['${name}']; }`).join('\n');
export default defineConfig({
    plugins: [react(), {
            name: 'responsive-test-fixtures', enforce: 'pre',
            resolveId(source) {
                if (/\/services\/api$/.test(source))
                    return '\0responsive-api';
                if (/\/(?:context\/(?:AuthContext|PosContext)|components\/context\/Operational(?:Context|Session)Gate)$/.test(source))
                    return path.join(root, 'e2e/responsive/contexts.tsx');
                return null;
            },
            load(id) { if (id === '\0responsive-api')
                return `const fixtures = ${JSON.stringify(fixtures)};\n${mockApi}\nexport const API_BASE_URL = ''; export function setApiAccessTokenProvider() {}`; },
        }],
    server: { host: '127.0.0.1', port: 5190, strictPort: true },
});
