# Responsive layout audit

Run from `frontend`:

```powershell
npm run test:e2e:responsive
```

Requires the project's Playwright Chromium browser. The runner starts and stops
an isolated Vite server on localhost:5190. It refuses to reuse an occupied port.

The real React screens, CSS, layouts and dialogs are rendered at 320×568,
390×844, 768×1024, 1024×768, 1366×768, 1920×1080 and 844×390. Checks cover page
width, text clipped inside buttons, dialog bounds immediately after resizing,
and uncaught rendering errors. Evidence goes to `.tmp/responsive-audit` at the
repository root. Set `RESPONSIVE_CASE` to a case-name substring for a focused run.

This is a **layout test with synthetic fixtures**, not operational acceptance.
The test Vite configuration substitutes authentication/context providers and API
functions only inside this isolated server. Fixtures are generated from API
TypeScript declarations with explicit examples for populated tables, products,
customer names and large amounts. External browser requests are blocked. It
neither uses real credentials nor connects to the published API. Empty arrays
remain in some secondary datasets; passing this audit does not establish complete
functional coverage or validate real sales, payments, providers or permissions.

None of this entry point, configuration or mock context is imported by the
production application. The normal Vite build still starts from `index.html`.
The existing unit and boundary suites remain independent and must also pass.
