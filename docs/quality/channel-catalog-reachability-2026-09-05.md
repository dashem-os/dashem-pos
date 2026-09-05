# S13 — the marketplace window gets its handles

Date: 5 September 2026 · scope: `channel-catalog` reachable from the product

## What was true before

`ChannelHubWorkspace` loaded offers and settlements and showed three counters
each. Of the eight `/channel-catalog` routes, the API client had the two `GET`.
A shopkeeper could see that a publication was partial and that a settlement was
short, and could do nothing about either.

## Decisions

- **Five writes reach the screen, one does not.** Mapping, offer, publication
  batch, settlement and settlement payment are things the shopkeeper decides.
  `POST /publications/{batch_id}/results` is the adapter reporting what the
  channel answered; a button for it would let a person sign the marketplace's
  word, and every batch would read green with the channel never called. It stays
  in the reachability baseline with the reason written next to it, alongside
  `POST /channels/orders/{order_id}/outbound`, which belongs to the worker.
- **The projection resolves names on the server.** Offers, batch items and
  mappings carry product name and SKU; offers, batches, mappings and settlements
  carry the connection's provider and merchant; settlements carry their
  payments. No row renders an identifier, and the browser never joins two lists
  to find a name — which is how a screen ends up showing the wrong one.
- **A product the tenant no longer has resolves to nothing, not to a guess.**
  The row says so instead of inventing a name.
- **One batch, one merchant.** The panel works on a selected channel and clears
  the selection when it changes, because a batch carries exactly one connection.
- **The expected net is the server's.** The import dialog shows the arithmetic
  as a typing check and says whose number is authoritative.
- **A competence day is a day.** `new Date('2026-09-04')` reads as midnight UTC
  and shows the day before west of Greenwich, so the parts are reordered as text.

## Verification

- `test_s13_channel_catalog_reconciliation.py`: the original contract test plus a
  new one over the enriched projection — named offers, named batch items with the
  channel's error code, named mappings, settlement with its payments, and a
  neighbouring tenant whose catalogue and settlements come back empty on exactly
  the shape where a join could leak.
- `test_frontend_api_contract.py`: the six client-reachable channel routes are
  now contracted, so a rename fails here instead of at runtime.
- `test_surface_reachability.py`: five routes left the unreachable baseline. The
  gate refused to let them stay once they became reachable — that refusal is what
  told us the work had landed.
- Responsive audit: 518 checks green across seven viewport sizes, including the
  four new dialogs, the publish button that stays dead until a row is chosen, and
  the competence day.
- `scripts/verify-local.sh`: 249 + 21 backend tests, frontend types, 102 tests
  and build, all green.

## Corrected in the local gate itself

`test_surface_reachability.py` reads `frontend/src`, and the script ran it in the
backend container, which mounts only `backend/`. It failed there on
`FileNotFoundError` — a red that said nothing about the product. It moved to the
step that mounts the whole repository, next to the other two tests that read
outside the backend.

## Not delivered, and not pretended

No adapter is homologated, so a published batch stays `PENDING`. The screen says
that in words rather than showing an empty success. Channel certification remains
an external gate and is untouched by this work.
