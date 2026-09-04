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
const permissions = [...new Set(fs.readdirSync(path.join(root, 'src'), { recursive: true }).filter(p => /\.(tsx|ts)$/.test(p)).flatMap(p => [...fs.readFileSync(path.join(root, 'src', p), 'utf8').matchAll(/includes\('([a-z]+\.[a-z.]+)'\)/g)].map(m => m[1])))];
fixtures.fetchEffectiveAccess = { ...fixtures.fetchEffectiveAccess, permissions, capabilities: { kitchen_routing: {}, table_service: {}, receivables: {} } };
const fixtureData = { fixtures, product, tenant, permissions };
fs.writeFileSync(path.join(root, 'e2e/responsive/generated-fixtures.json'), JSON.stringify(fixtureData, null, 2));
const mockApi = Object.keys(fixtures).map(name => `export async function ${name}(...args) { if (window.__fixtures?.['${name}'] !== undefined) return window.__fixtures['${name}']; return fixtures['${name}']; }`).join('\n');
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
