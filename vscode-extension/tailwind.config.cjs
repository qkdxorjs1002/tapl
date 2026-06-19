/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/webview/**/*.{html,ts,tsx}'],
  daisyui: {
    themes: [
      {
        tapl: {
          primary: '#0e639c',
          'primary-content': '#ffffff',
          secondary: '#3a3d41',
          'secondary-content': '#ffffff',
          accent: '#007acc',
          neutral: '#252526',
          'base-100': '#1e1e1e',
          'base-200': '#252526',
          'base-300': '#2d2d30',
          'base-content': '#d4d4d4',
          info: '#3794ff',
          success: '#89d185',
          warning: '#cca700',
          error: '#f48771'
        }
      }
    ]
  },
  plugins: [require('daisyui')]
};
