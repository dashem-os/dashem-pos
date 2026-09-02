/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        dashem: {
          magenta: '#e11d48',
          'magenta-dark': '#be123c',
          'magenta-light': '#f43f5e',
          red: '#e11d48',
          'red-dark': '#be123c',
          'red-light': '#f43f5e',
          bg: '#0b1220',
          surface: '#172238',
          'surface-elevated': '#22314d',
          border: '#435473',
          muted: '#bdc9d9'
        },
        pdv: {
          bg: '#f8fafc',
          card: '#ffffff',
          border: '#e2e8f0',
          hover: '#f1f5f9',
          text: '#0f172a',
          muted: '#64748b'
        }
      }
    },
  },
  plugins: [],
}
