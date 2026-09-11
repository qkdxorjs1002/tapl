/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/webview/**/*.{html,ts,tsx}'],
  daisyui: {
    themes: [
      {
        tapl: {
          primary: '#0e639c',
          'primary-content': '#ffffff',
          secondary: '#3c3c3c',
          'secondary-content': '#ffffff',
          accent: '#3794ff',
          'accent-content': '#ffffff',
          neutral: '#1e1e1e',
          'neutral-content': '#cccccc',
          'base-100': '#1e1e1e',
          'base-200': '#252526',
          'base-300': '#333333',
          'base-content': '#cccccc',
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
