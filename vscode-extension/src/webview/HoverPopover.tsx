import { ReactNode, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const OPEN_DELAY_MS = 500;
const CLOSE_DELAY_MS = 180;
const VIEWPORT_MARGIN = 8;
const POINTER_GAP = 12;

export function HoverPopover({ label, children, content }: {
  label: string;
  children: ReactNode;
  content: ReactNode;
}): JSX.Element {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const openTimer = useRef<ReturnType<typeof setTimeout>>();
  const closeTimer = useRef<ReturnType<typeof setTimeout>>();
  const pointerInside = useRef(false);
  const restoringFocus = useRef(false);
  const anchor = useRef({ x: 0, y: 0, aboveY: 0 });
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ left: 0, top: 0 });

  function clearTimers(): void {
    clearTimeout(openTimer.current);
    clearTimeout(closeTimer.current);
  }

  function contains(target: EventTarget | null): boolean {
    return target instanceof Node && Boolean(trigger.current?.contains(target) || panel.current?.contains(target));
  }

  function dismiss(): void {
    clearTimers();
    pointerInside.current = false;
    setOpen(false);
  }

  function openFromKeyboard(): void {
    clearTimers();
    const rect = trigger.current?.getBoundingClientRect();
    if (rect) {
      anchor.current = { x: rect.left, y: rect.bottom, aboveY: rect.top };
    }
    setOpen(true);
  }

  function scheduleClose(): void {
    clearTimers();
    closeTimer.current = setTimeout(() => {
      if (!pointerInside.current && !contains(document.activeElement)) {
        setOpen(false);
      }
    }, CLOSE_DELAY_MS);
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key !== 'Escape') {
        return;
      }
      if (panel.current?.contains(document.activeElement)) {
        restoringFocus.current = true;
        trigger.current?.focus({ preventScroll: true });
        restoringFocus.current = false;
      }
      dismiss();
    }
    function onPointerDown(event: PointerEvent): void {
      if (!contains(event.target)) {
        dismiss();
      }
    }
    function onScroll(event: Event): void {
      if (!(event.target instanceof Node && panel.current?.contains(event.target))) {
        dismiss();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', dismiss);
    window.addEventListener('blur', dismiss);
    return () => {
      clearTimers();
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', dismiss);
      window.removeEventListener('blur', dismiss);
    };
  }, []);

  useLayoutEffect(() => {
    if (!open || !panel.current) {
      return;
    }
    const rect = panel.current.getBoundingClientRect();
    const { x, y, aboveY } = anchor.current;
    const below = y + POINTER_GAP;
    const top = below + rect.height <= window.innerHeight - VIEWPORT_MARGIN
      ? below
      : aboveY - rect.height - POINTER_GAP;
    const next = {
      left: Math.max(VIEWPORT_MARGIN, Math.min(x, window.innerWidth - rect.width - VIEWPORT_MARGIN)),
      top: Math.max(VIEWPORT_MARGIN, Math.min(top, window.innerHeight - rect.height - VIEWPORT_MARGIN))
    };
    setPosition((current) => current.left === next.left && current.top === next.top ? current : next);
  }, [open, content]);

  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="tapl-custom-summary"
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onPointerEnter={(event) => {
          if (event.pointerType === 'touch') {
            return;
          }
          pointerInside.current = true;
          clearTimers();
          anchor.current = { x: event.clientX, y: event.clientY, aboveY: event.clientY };
          openTimer.current = setTimeout(() => setOpen(true), OPEN_DELAY_MS);
        }}
        onPointerMove={(event) => {
          if (!open) {
            anchor.current = { x: event.clientX, y: event.clientY, aboveY: event.clientY };
          }
        }}
        onPointerLeave={() => {
          pointerInside.current = false;
          scheduleClose();
        }}
        onFocus={() => {
          if (!restoringFocus.current) {
            openFromKeyboard();
          }
        }}
        onBlur={(event) => {
          if (!contains(event.relatedTarget)) {
            scheduleClose();
          }
        }}
        onClick={() => {
          openFromKeyboard();
        }}
        onKeyDown={(event) => {
          if (open && event.key === 'ArrowDown') {
            event.preventDefault();
            panel.current?.focus({ preventScroll: true });
          }
        }}
      >
        {children}
      </button>
      {open ? createPortal(
        <div
          ref={panel}
          id={id}
          role="dialog"
          aria-label={label}
          tabIndex={0}
          className="tapl-custom-popover"
          data-theme="tapl"
          style={position}
          onPointerEnter={() => {
            pointerInside.current = true;
            clearTimers();
          }}
          onPointerLeave={() => {
            pointerInside.current = false;
            scheduleClose();
          }}
          onFocus={clearTimers}
          onBlur={(event) => {
            if (!contains(event.relatedTarget)) {
              scheduleClose();
            }
          }}
        >
          <div className="tapl-custom-header"><span className="tapl-eyebrow">{label}</span></div>
          {content}
        </div>,
        document.body
      ) : null}
    </>
  );
}
