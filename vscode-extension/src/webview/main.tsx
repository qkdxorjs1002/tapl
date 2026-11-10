import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles.css';
import './workbench/workbench.css';
import './workbench/reading.css';
import './workbench/secondary.css';
import './workbench/interactions.css';

createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
