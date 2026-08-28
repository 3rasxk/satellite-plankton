import React from 'react'

export function SkeletonBar({ width = '100%', height = '14px', style = {} }) {
  return (
    <div
      className="skeleton-shimmer skeleton-bar"
      style={{ width, height, ...style }}
    />
  )
}

export function SkeletonCard({ height = '140px' }) {
  return (
    <div className="skeleton-card" style={{ minHeight: height }}>
      <div className="skeleton-shimmer skeleton-bar skeleton-bar-title" />
      <div className="skeleton-grid-2x2">
        <div className="skeleton-shimmer skeleton-grid-cell" />
        <div className="skeleton-shimmer skeleton-grid-cell" />
      </div>
      <div className="skeleton-shimmer skeleton-bar" style={{ width: '80%', height: '10px' }} />
    </div>
  )
}

export function MapOverlaySkeleton() {
  return (
    <div className="map-overlay-skeleton glass">
      <div className="skeleton-shimmer skeleton-bar skeleton-bar-title" style={{ width: '60%' }} />
      <div className="skeleton-shimmer skeleton-bar-row" />
      <div className="skeleton-shimmer skeleton-bar" style={{ width: '45%' }} />
    </div>
  )
}

export default SkeletonCard
