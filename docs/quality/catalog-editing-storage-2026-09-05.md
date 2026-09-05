# Catalog editing and image upload correction

## Confirmed findings

- Homologation lists HAB-01, Hambuguer Artesanal Bacon, at BRL 32.00.
- Homologation has no assortments, so its empty POS projection is expected.
- The screenshot reports NO_SOURCES: no tenant storage namespaces were registered.
- SellableProductDTO discarded the image resolved by the catalog service.
- Provider capacity used SELECT FOR UPDATE, which also applies UPDATE RLS;
  tenants may only SELECT provider measurements, so capacity became unavailable.

## Changes

- Product edit and guarded permanent deletion, separate from archive.
- Product name/SKU/barcode and store price update in the same transaction.
- Deletion preserves media assets and rejects operational history and published links.
- Explicit image clearing and image serialization in the catalog API.
- BRL text input without spinners; deleting zero leaves the field empty.
- Registration, assortment and POS cards open their corresponding workflows.
- Stale list requests cannot overwrite the refreshed catalog.
- Catalog editors can upload product images without needing team administration.
- An idempotent preparation command measures fixed private namespaces through
  the trusted provider adapter. Its separate maintenance transaction does not
  change the caller's tenant scope or return other tenants' media.
- Advisory transaction locking serializes shared provider capacity checks
  without granting tenants UPDATE access to provider measurements.

## Verification

- 102 existing frontend tests and production build passed.
- 49 responsive/interaction checks passed across seven viewport sizes, including
  edit/delete dialogs, progressive BRL entry, clearing zero and assortment shortcut.
- Local isolated PostgreSQL: 267 tests passed in the full run; the remaining
  module-map declaration was corrected, then all 9 module/editing tests passed.
- New API/database tests cover image serialization, price/cost preservation,
  delete/history/isolation, media preservation, automatic measured preparation,
  idempotency and missing provider configuration.

## Deployment acceptance still required

The connected browser exposes the homologation Supervisor session. The Owner
is in a different Chrome profile. Real provider configuration and the physical
file from the original upload have not yet been verified. No customer product
or image was deleted, and no assortment was invented for the customer.
