export default function StatCard({ label, value, detail, riskLevel }) {
  return (
    <div className={`stat-card${riskLevel ? ` risk-${riskLevel}` : ''}`}>
      <span className="stat-value mono">{value}</span>
      <span className="stat-label">{label}</span>
      {detail && <span className="stat-detail">{detail}</span>}
    </div>
  )
}
