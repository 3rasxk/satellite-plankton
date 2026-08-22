/**
 * Persistent truth-boundary banner. Rendered once in App.jsx's layout
 * shell so it appears on every route without depending on any fetch
 * having resolved — CLAUDE.md: "mandatory in every output — no
 * overclaiming." Text defaults to the verbatim constant but accepts an
 * override so a page can pass the exact string it got back from a live
 * response if one is available (they're always identical in practice).
 */
export default function Disclaimer({ text }) {
  return (
    <footer className="disclaimer" role="contentinfo">
      <p>{text}</p>
    </footer>
  )
}
