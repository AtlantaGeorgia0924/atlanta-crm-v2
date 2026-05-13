/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: {
          50:  '#faf6e8',
          100: '#f3e6b6',
          500: '#D4AF37',
          600: '#b9962f',
          700: '#8f7424',
        },
      },
    },
  },
  plugins: [],
}
