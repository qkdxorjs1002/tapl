import { useEffect, useLayoutEffect } from 'react';

// The Viewer is client-rendered; static render tests do not have a layout phase.
export const useBrowserLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect;
