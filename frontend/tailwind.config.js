/** @type {import('tailwindcss').Config} */

// Design tokens are driven by CSS custom properties declared in src/index.css.
// Values are space-separated RGB channels so Tailwind can apply opacity modifiers
// (e.g. bg-brand/10). The niche identity swaps only the brand channels at runtime
// through the [data-niche] attribute on the root element.
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`

export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Brand identity: swapped per business niche.
        brand: {
          DEFAULT: token('brand'),
          strong: token('brand-strong'),
          soft: token('brand-soft'),
          // Darkened brand for text and icons on light surfaces: the amber identity
          // is unreadable at its fill value, so text never uses `brand` directly.
          ink: token('brand-ink'),
          // Text/icon color that is guaranteed readable on top of `brand`.
          // Never use text-white on a brand surface: the BEAUTY amber needs dark text.
          contrast: token('brand-contrast'),
        },
        dashem: {
          // Surfaces, from the page background up to the most elevated card.
          bg: token('surface-bg'),
          surface: token('surface'),
          'surface-elevated': token('surface-elevated'),
          border: token('border'),
          // Text roles.
          strong: token('text-strong'),
          muted: token('text-muted'),
          // Legacy aliases kept so existing screens inherit the niche accent
          // without a mass rename.
          red: token('brand'),
          'red-light': token('brand-strong'),
        },
        // Situação, não identidade: estes canais não mudam por nicho.
        // `state-*` para texto e preenchimento, `*-soft` para o fundo da faixa
        // e `*-border` para a moldura dela.
        state: {
          success: token('state-success'),
          'success-soft': token('state-success-soft'),
          'success-border': token('state-success-border'),
          'success-strong': token('state-success-strong'),
          'success-on-strong': token('state-success-on-strong'),
          'success-accent': token('state-success-accent'),
          warning: token('state-warning'),
          'warning-soft': token('state-warning-soft'),
          'warning-border': token('state-warning-border'),
          'warning-strong': token('state-warning-strong'),
          'warning-on-strong': token('state-warning-on-strong'),
          'warning-accent': token('state-warning-accent'),
          danger: token('state-danger'),
          'danger-soft': token('state-danger-soft'),
          'danger-border': token('state-danger-border'),
          'danger-strong': token('state-danger-strong'),
          'danger-on-strong': token('state-danger-on-strong'),
          'danger-accent': token('state-danger-accent'),
          info: token('state-info'),
          'info-soft': token('state-info-soft'),
          'info-border': token('state-info-border'),
          'info-strong': token('state-info-strong'),
          'info-on-strong': token('state-info-on-strong'),
          'info-accent': token('state-info-accent'),
        },
      },
    },
  },
  plugins: [],
}
