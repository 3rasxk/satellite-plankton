const MODES = [
  { value: 'true_color', label: 'True Color (RGB)' },
  { value: 'ndci', label: 'NDCI Index (20m)' },
  { value: 'risk', label: 'แผนที่ความเสี่ยง (rule-based)' },
]

/** Floating glass segmented control switching RiskMap's `mode` prop. */
export default function MapControls({ mode, onModeChange }) {
  return (
    <div className="map-segmented-control glass">
      {MODES.map((m) => (
        <button
          key={m.value}
          type="button"
          className={mode === m.value ? 'active' : ''}
          onClick={() => onModeChange(m.value)}
        >
          {m.label}
        </button>
      ))}
    </div>
  )
}
