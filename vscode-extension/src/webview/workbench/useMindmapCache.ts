import { useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import { sameMindmapValue } from './mindmapCache';

/** Host refreshes deserialize equal records into new objects. Keep expensive map inputs stable. */
export function useMindmapValue<T>(value: T): T {
  const cached = useRef(value);
  if (!sameMindmapValue(cached.current, value)) cached.current = value;
  return cached.current;
}

const useCommittedEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect;

/** Memoized cards call the latest committed navigation handler without rerendering for its identity. */
export function useMindmapAction<Args extends unknown[]>(action: (...args: Args) => void): (...args: Args) => void {
  const latest = useRef(action);
  useCommittedEffect(() => { latest.current = action; }, [action]);
  return useCallback((...args: Args) => latest.current(...args), []);
}
