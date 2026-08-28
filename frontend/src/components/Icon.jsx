const ICON_PATHS = {
  map: <><path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3V6Z" /><path d="M9 3v15M15 6v15" /></>,
  satellite: <><path d="m13.5 10.5 3-3M10.5 13.5l-3 3" /><path d="M8.5 8.5 5 5m10.5 10.5L19 19" /><path d="M13 5a6 6 0 0 1 6 6M5 13a6 6 0 0 0 6 6" /><rect x="9" y="9" width="6" height="6" rx="1" transform="rotate(45 12 12)" /></>,
  trend: <><path d="M3 17 9 11l4 4 7-8" /><path d="M15 7h5v5" /></>,
  fish: <><path d="M3 12c3-5 8-6 13-3l5-3-1 6 1 6-5-3c-5 3-10 2-13-3Z" /><path d="M7 12h.01M15 9c1 1 1 5 0 6" /></>,
  file: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></>,
  chart: <><path d="M4 19V5M4 19h17" /><path d="m7 15 3-4 3 2 5-6" /></>,
  clipboard: <><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4.5V3h6v1.5M8 10h8M8 14h8M8 18h5" /></>,
  wrench: <><path d="M14.7 6.3a5 5 0 0 0-6.4 6.4L3 18l3 3 5.3-5.3a5 5 0 0 0 6.4-6.4l-3.1 3.1-3-3 3.1-3.1Z" /></>,
  settings: <><path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z" /><path d="m4.9 4.9 2.1 2.1m10-2.1-2.1 2.1m2.1 10-2.1-2.1m-10 2.1 2.1-2.1M3 12h3m12 0h3M12 3v3m0 12v3" /></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01" /></>,
  alert: <><path d="M12 3 2.7 20h18.6L12 3Z" /><path d="M12 9v5M12 17h.01" /></>,
  refresh: <><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" /><path d="M21 3v5h-5" /></>,
  chevronDown: <path d="m6 9 6 6 6-6" />,
}

export default function Icon({ name, size = 18, strokeWidth = 1.8, className = '' }) {
  return (
    <svg
      className={`icon ${className}`.trim()}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {ICON_PATHS[name]}
    </svg>
  )
}
