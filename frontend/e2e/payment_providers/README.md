# Payment provider acceptance

Run `npm run test:e2e:providers` from `frontend`, after `bash scripts/verify-local.sh`.
Requires the development API at `http://localhost:8002` with its existing local
authentication mode, Playwright Chromium, and free port 5192. The test does not
change authentication settings.

The isolated Vite entry supplies only tenant, store and access context. The
component, API client and HTTP requests are real. Each run creates a distinct
`provider-ui-*` tenant with test registers, devices and configuration records;
these records remain in the development database for inspection. No payment
transaction is executed. The test sends an authenticated bridge heartbeat to
verify that generated pairing codes work; this is not a hardware certification.

Covers configuration errors and retry keys, provider creation, pairing, bridge
telemetry, matching POS/register/provider selections, TEF and SmartPOS bindings,
pause, revocation, persistence after reload, read-only access, denied access, and
overflow at 360/768/1024/1440px with the management sidebar width reserved.
Screenshots are saved under `frontend/test-results/payment-providers` after the
pairing secret is dismissed.

The backend test `test_payment_provider_navigation.py` separately verifies the
persisted contribution against real effective capabilities and permissions.
Migration reversibility remains a gate of the disposable-database CI job.
