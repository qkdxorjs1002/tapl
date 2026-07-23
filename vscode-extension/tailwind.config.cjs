/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/webview/**/*.{html,ts,tsx}'],
  daisyui: {
    themes: [
      {
        tapl: {
          primary: '#0066ff',
          'primary-content': '#ffffff',
          secondary: '#293145',
          'secondary-content': '#ffffff',
          accent: '#00e5ff',
          'accent-content': '#07111f',
          neutral: '#1e1e1e',
          'neutral-content': '#f8fafc',
          'base-100': '#1e1e1e',
          'base-200': '#242733',
          'base-300': '#303544',
          'base-content': '#f1f5f9',
          info: '#38bdf8',
          success: '#5fd38d',
          warning: '#f4c95d',
          error: '#ff6b7a'
        }
      }
    ]
  },
  plugins: [require('daisyui')]
};
