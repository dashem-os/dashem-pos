# Responsive audit — 2026-08-21

Surfaces: public login, Dashem Control and tenant Management.

The real React surfaces were rendered in the browser at:

- 390 × 844;
- 768 × 1024;
- 1024 × 768;
- 1366 × 768;
- 1920 × 1080.

## Results

- Login: no horizontal overflow; fields and primary/social actions retain
  48-pixel touch targets. The password-recovery switch now has a 44-pixel
  minimum target.
- Dashem Control: compact header at phone width, labelled icon actions, mobile
  drawer with logout, stacked metrics and contained horizontal scrolling for
  the dense organization table.
- Tenant Management: mobile drawer added with every management destination,
  explicit PDV transition and logout; tablet horizontal and desktop retain the
  persistent sidebar; dashboard cards reflow without overlap.
- 1024 × 768 remains desktop/navigation-sidebar mode by design; 768 × 1024 and
  390 × 844 use the mobile navigation surface.

The audit route used to render protected surfaces was local and temporary. It
was removed before build and is not part of the application or deployment.

## Follow-up gate

Every new operational screen must be checked at the same five viewports. Dense
tables may use contained horizontal scrolling initially, but high-frequency
mobile workflows should receive task-oriented card/list presentations rather
than shrinking desktop tables.
