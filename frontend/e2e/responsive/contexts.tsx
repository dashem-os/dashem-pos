import React, { useState } from 'react';
import data from './generated-fixtures.json';
const noop = async () => null;
const auth = { configured: true, loading: false, session: { user: { email: 'test@example.test' } }, terminalToken: 'test-only', signIn: noop, signOut: noop, requestPasswordReset: noop, updatePassword: noop, listTotpFactors: async () => ({ factors: [{ id: 'factor-1', factor_type: 'totp', status: 'verified' }], error: null }), enrollTotp: noop, clearTerminalAuthorization: noop, activateOperationalSession: noop };
export const useAuth = () => auth;
export const AuthProvider = ({ children }) => children;
const modules = ['overview', 'sales', 'tables', 'channels', 'cash', 'receivables', 'products', 'assortments', 'categories', 'inventory', 'customers', 'team', 'devices', 'subscription'];
const base = { tenant: data.tenant, store: { id: 'store-1', name: 'Unidade com nome extenso para teste' }, register: { id: 'register-1', name: 'Caixa de teste' }, permissions: data.permissions, products: [data.product], categories: data.fixtures.fetchCategories, prices: { 'product-1': 1234.56 }, balances: { 'product-1': 20 }, salesHistory: [], activities: ['FOOD_SERVICE', 'RETAIL'], activeActivity: 'FOOD_SERVICE', capabilities: { kitchen_routing: {}, table_service: {}, receivables: {} }, contributions: modules.map(id => ({ surface: 'MANAGEMENT_NAV', implementation_key: id, label: id, group_key: 'GESTÃO' })), operatorId: 'operator-1', operatorName: 'Colaborador de teste com nome extenso', operatorRole: 'SUPERVISOR', connectionState: 'ONLINE', operationMode: 'COUNTER', accessMode: 'MANAGEMENT', homologation: false, confirmedPayments: [], fiscalDoc: null, health: {}, loading: false, actionLoading: false, cashSession: { id: 'cash-1', status: 'OPEN', opening_balance: 100 }, currentSale: { id: 'sale-1', status: 'DRAFT', gross_total: 1234.56, net_total: 1234.56, discount_total: 0, items: [{ id: 'item-1', product_name: data.product.name, sku: data.product.sku, product_id: 'product-1', quantity: 1, unit_price: 1234.56, gross_total: 1234.56, net_total: 1234.56 }] } };
const Context = React.createContext(null);
export function PosProvider({ children }) {
    const [state, setState] = useState({ ...base, ...(new URLSearchParams(location.search).has('closed') ? { cashSession: null } : {}) });
    const actions = Object.fromEntries(['showToast', 'startNewSale', 'addItemToCart', 'updateItemQuantity', 'removeItemFromCart', 'applyDiscount', 'cancelCurrentSale', 'processPayment', 'issueFiscal', 'openCash', 'closeCash', 'addCashMovement', 'createNewProduct', 'adjustStock', 'refreshData'].map(k => [k, noop]));
    for (const [name, key] of [['Payment', 'Payment'], ['Discount', 'Discount'], ['Cancel', 'Cancel'], ['Quantity', 'Quantity'], ['Fiscal', 'Fiscal']]) {
        actions[`open${name}Modal`] = () => setState(s => ({ ...s, [`is${key}ModalOpen`]: true }));
        actions[`close${name}Modal`] = () => setState(s => ({ ...s, [`is${key}ModalOpen`]: false }));
    }
    return <Context.Provider value={{ ...state, ...actions, setOperationMode: value => setState(s => ({ ...s, operationMode: value })), setActiveActivity: value => setState(s => ({ ...s, activeActivity: value })) }}>{children}</Context.Provider>;
}
export const usePos = () => React.useContext(Context);
export const OperationalContextGate = ({ children }) => children({ tenantId: 'tenant-1', storeId: 'store-1', registerId: 'register-1' });
export const OperationalSessionGate = OperationalContextGate;
