const { spawn } = require('node:child_process');
const path = require('node:path');
const frontend = path.resolve(__dirname, '../..');
const url = 'http://127.0.0.1:5190/e2e/responsive/index.html';
async function run() {
    // Never attach to an unrelated development server or silently reuse its data.
    try {
        await fetch(url, { signal: AbortSignal.timeout(500) });
        throw new Error('Port 5190 is already in use. Stop that server before running the responsive audit.');
    }
    catch (error) {
        if (error.message.includes('already in use'))
            throw error;
    }
    const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--config', 'e2e/responsive/vite.config.mjs'], {
        cwd: frontend, stdio: 'inherit', windowsHide: true,
    });
    try {
        let ready = false;
        for (let attempt = 0; attempt < 60; attempt++) {
            if (server.exitCode !== null)
                throw new Error('The isolated layout server exited before becoming ready.');
            try {
                const response = await fetch(url, { signal: AbortSignal.timeout(500) });
                if (response.ok) {
                    ready = true;
                    break;
                }
            }
            catch { /* Vite is still starting. */ }
            await new Promise(resolve => setTimeout(resolve, 500));
        }
        if (!ready)
            throw new Error('The isolated layout server did not start within 30 seconds.');
        process.exitCode = await new Promise((resolve, reject) => {
            const audit = spawn(process.execPath, ['e2e/responsive/audit.cjs'], {
                cwd: frontend, stdio: 'inherit', windowsHide: true,
            });
            audit.once('error', reject);
            audit.once('exit', code => resolve(code ?? 1));
        });
    }
    finally {
        server.kill();
    }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
