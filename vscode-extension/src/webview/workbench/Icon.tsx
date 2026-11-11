import type { ReactNode } from 'react';

const icons: Record<string, ReactNode> = {
  'panel-expand': <><rect x="3" y="3" width="18" height="18" rx="3" /><path d="M9 3v18m4-12 3 3-3 3" /></>,
  'panel-collapse': <><rect x="3" y="3" width="18" height="18" rx="3" /><path d="M9 3v18m7-12-3 3 3 3" /></>,
  plan: (
    <>
      <rect x="8" y="3" width="8" height="5" rx="1" />
      <rect x="2" y="16" width="7" height="5" rx="1" />
      <rect x="15" y="16" width="7" height="5" rx="1" />
      <path d="M12 8v4M5.5 16v-4h13v4" />
    </>
  ),
  task: (
    <>
      <rect x="8" y="2" width="8" height="4" rx="1" />
      <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2M9 14l2 2 4-5" />
    </>
  ),
  finding: (
    <>
      <circle cx="10" cy="10" r="6" />
      <path d="m14.5 14.5 6 6M7.5 10.5l1.7 1.7 3.3-3.4" />
    </>
  ),
  languages: <path d="M3 5h12M9 3v2M5 5c0 6 5 9 8 10M13 5c0 6-5 9-8 10M14 21l4-10 4 10M15.5 18h5" />,
  refresh: <path d="M20 7v5h-5M4 17v-5h5M5.5 8a7 7 0 0 1 11.6-3L20 8M4 16l2.9 3A7 7 0 0 0 18.5 16" />,
  debug: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5" />
    </>
  ),
  moon: <path d="M20.5 14.5A9 9 0 0 1 9.5 3.5a9 9 0 1 0 11 11z" />,
  focus: (
    <>
      <path d="M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5" />
      <circle cx="12" cy="12" r="4" />
    </>
  ),
  table: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9h18M3 14h18M9 9v11" />
    </>
  ),
  file: <path d="M5 3h9l5 5v13H5zM14 3v6h5M8 13h8M8 17h6" />,
  folder: <path d="M3 7V5h7l2 3h9v12H3z" />,
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 4 4" />
    </>
  ),
  book: <path d="M4 4h6a3 3 0 0 1 2 1 3 3 0 0 1 2-1h6v15h-6a3 3 0 0 0-2 1 3 3 0 0 0-2-1H4zM12 5v15" />,
  trash: <path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7" />,
  arrow: <path d="M5 12h14M14 7l5 5-5 5" />,
  back: <path d="M19 12H5M10 7l-5 5 5 5" />,
  chevron: <path d="m9 5 7 7-7 7" />,
  alert: <path d="m12 3 10 18H2zM12 9v5M12 17h.01" />,
  check: <path d="m5 12 4 4L19 6" />,
  inbox: <path d="m5 4-3 11v5h20v-5L19 4zM2 15h6l2 3h4l2-3h6" />,
  lock: (
    <>
      <rect x="5" y="10" width="14" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" />
    </>
  )
};
export function Icon({ name }: { name: string }): JSX.Element {
  return (
    <svg
      className="wb-icon"
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {icons[name] ?? icons.file}
    </svg>
  );
}
