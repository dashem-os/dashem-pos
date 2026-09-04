const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const modules = ['overview', 'sales', 'tables', 'channels', 'cash', 'receivables', 'products', 'assortments', 'categories', 'inventory', 'customers', 'team', 'devices', 'subscription'];
const cases = [...modules.map(module => ({ name: `manage-${module}`, screen: 'manage', module })), ...['owner', 'pos', 'operate', 'login', 'password', 'mfa', 'kds', 'tables'].map(screen => ({ name: screen, screen })), { name: 'pos-closed', screen: 'pos', closed: '1' }];
const click = name => async (page) => page.getByRole('button', { name, exact: true }).click();
const owner = name => async (page) => { await click('Abrir menu')(page); await click(name)(page); };
const tenant = async (page) => { await owner('Organizações')(page); await click('Abrir')(page); await page.getByRole('button', { name: 'Cadastro', exact: true }).waitFor(); };
for (const name of ['Organizações', 'Planos comerciais', 'Financeiro SaaS', 'Operações do Control', 'Saúde da plataforma'])
    cases.push({ name: `owner-${name}`, screen: 'owner', steps: [owner(name)] });
for (const tab of ['Resumo contratual', 'Cadastro', 'Conta de cobrança', 'Contrato', 'Administrador inicial'])
    cases.push({ name: `tenant-${tab}`, screen: 'owner', steps: [tenant, click(tab)] });
for (const tab of ['Recebimentos e Cobranças', 'Base Contratual', 'Projeção Financeira Reconstruível'])
    cases.push({ name: `finance-${tab}`, screen: 'owner', steps: [owner('Financeiro SaaS'), click(tab)] });
for (const action of ['Receber', 'Anular'])
    cases.push({ name: `finance-modal-${action}`, screen: 'owner', steps: [owner('Financeiro SaaS'), click(action)], modal: true });
cases.push({ name: 'finance-detail', screen: 'owner', steps: [owner('Financeiro SaaS'), page => page.getByTitle('Ver detalhes').click()], modal: true });
cases.push({ name: 'owner-new', screen: 'owner', steps: [owner('Organizações'), click('Novo cliente')], modal: true });
cases.push({ name: 'owner-plan-form', screen: 'owner', steps: [owner('Planos comerciais'), click('Novo plano')] });
cases.push({ name: 'owner-pause', screen: 'owner', steps: [tenant, click('Pausar')], modal: true });
for (const [module, name] of [['products', 'Cadastrar Novo Produto'], ['products', 'Ajustar'], ['assortments', 'Novo Sortimento'], ['assortments', 'Produtos (1)'], ['customers', 'Novo cliente'], ['team', 'Conceder acesso'], ['devices', 'Novo dispositivo'], ['devices', 'Nova regra'], ['tables', 'Nova mesa'], ['tables', 'Nova reserva'], ['categories', 'Nova categoria']])
    cases.push({ name: `dialog-${module}-${name}`, screen: 'manage', module, steps: [click(name)], modal: true });
cases.push({ name: 'team-new-employee', screen: 'manage', module: 'team', steps: [click('Conceder acesso'), click('Novo cadastro')], modal: true });
cases.push({ name: 'operate-activation', screen: 'operate', steps: [click('Primeiro acesso / novo PIN')] });
for (const name of ['Ver Itens', 'RECEBER'])
    cases.push({ name: `pos-${name}`, screen: 'pos', steps: [click(name)], modal: true });
cases.push({ name: 'tables-tab', screen: 'tables', steps: [click('Comanda individual')], modal: true });
for (const tab of ['Plano e cobrança', 'Modelos de negócio', 'Capabilities', 'Limites'])
    cases.push({ name: `contract-editor-${tab}`, screen: 'owner', steps: [tenant, click('Contrato'), click('Editar contrato'), click(tab)] });
const sizes = [[320, 568], [390, 844], [768, 1024], [1024, 768], [1366, 768], [1920, 1080], [844, 390]];
const out = path.resolve('../.tmp/responsive-audit');
fs.mkdirSync(out, { recursive: true });
(async () => { const browser = await chromium.launch({ headless: true }); const page = await browser.newPage(); await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort()); const errors = []; page.on('pageerror', e => errors.push(e.message)); const results = []; for (const c of cases.filter(c => !process.env.RESPONSIVE_CASE || c.name.includes(process.env.RESPONSIVE_CASE))) {
    errors.length = 0;
    await page.setViewportSize({ width: 390, height: 844 });
    try {
        await page.goto('http://127.0.0.1:5190/e2e/responsive/index.html?' + new URLSearchParams({ screen: c.screen, ...(c.module ? { module: c.module } : {}), ...(c.closed ? { closed: c.closed } : {}) }));
        await page.waitForTimeout(400);
        for (const step of c.steps || []) {
            await step(page);
            await page.waitForTimeout(100);
        }
        assert.deepEqual(errors, []);
        assert.equal(await page.locator('[data-error]').count(), 0);
        for (const [width, height] of sizes) {
            await page.setViewportSize({ width, height });
            await page.waitForTimeout(40);
            const measurement = await page.evaluate(() => { const visible = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'; }; return { scroll: document.documentElement.scrollWidth, clippedControls: [...document.querySelectorAll('button')].filter(e => visible(e) && !e.closest('thead') && getComputedStyle(e).overflow === 'visible' && e.scrollHeight > e.clientHeight + 3).map(e => e.textContent.trim().slice(0, 70)), dialogs: [...document.querySelectorAll('.responsive-dialog,[role="dialog"]')].filter(visible).map(e => { const r = e.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, width: r.width, scroll: e.scrollHeight, client: e.clientHeight }; }) }; });
            const failures = [];
            if (measurement.scroll > width + 1)
                failures.push(`page width ${measurement.scroll}`);
            if (measurement.clippedControls.length)
                failures.push(`clipped controls: ${measurement.clippedControls.join(' | ')}`);
            for (const d of measurement.dialogs)
                if (d.top < -1 || d.bottom > height + 1)
                    failures.push('dialog outside viewport');
            const name = c.name.replace(/[^a-z0-9]/gi, '-');
            if (failures.length || width === 390 && ['owner', 'pos', 'dialog-products-Cadastrar Novo Produto', 'tenant-Contrato'].includes(c.name))
                await page.screenshot({ path: path.join(out, `${name}-${width}x${height}.png`), fullPage: true });
            results.push({ case: c.name, width, height, failures });
        }
        console.log(`CHECKED ${c.name}`);
    }
    catch (e) {
        results.push({ case: c.name, failures: [String(e).slice(0, 500)] });
        console.log(`FAILED ${c.name}: ${String(e).slice(0, 250)}`);
    }
} fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify(results, null, 2)); const failed = results.filter(r => r.failures.length); console.log(JSON.stringify({ checks: results.length, failed }, null, 2)); await browser.close(); process.exitCode = failed.length ? 1 : 0; })();
