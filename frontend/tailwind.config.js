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
      },
    },
  },
  plugins: [],
}
