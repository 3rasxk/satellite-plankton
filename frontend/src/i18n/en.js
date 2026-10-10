/**
 * English dictionary (plain scientific style).
 *
 * Every key here must also exist in th.js with the same `{param}`
 * placeholders (tests/i18n.test.js). Scientific symbols, band names,
 * formulas, units, DOIs and API-supplied free text are never translated;
 * the server `disclaimer` is shown verbatim, not re-worded here.
 *
 * Truth boundary (dashboard spec §2, test-baseline spec §5/§8): no string
 * presents a risk level except to deny one, and none says a bloom is
 * present or absent. Keys grow in later tasks; keep both files in step.
 */
export default {
  app: {
    name: 'Plankton Watch',
    tagline: 'Sentinel-2 and MODIS water-colour index readings for the upper Gulf of Thailand',
  },

  nav: {
    main_label: 'Main navigation',
    overview: 'Overview',
    map: 'Raster map',
    sites: 'Monitoring sites',
    methods: 'Methods',
    data: 'Data & limits',
    cite: 'Cite',
    language: 'Language',
    skip_to_content: 'Skip to main content',
    menu: 'Menu',
    home: 'Plankton Watch: overview',
    // Language names are written in their own language (autonyms) in both
    // dictionaries, so a reader can find their language whatever is shown.
    lang_th: 'ไทย',
    lang_en: 'English',
  },

  page: {
    title: '{page} · Plankton Watch',
  },

  common: {
    of: '{n} of {total}',
    loading: 'Loading…',
    error: 'The data could not be loaded.',
    retry: 'Retry',
    unknown: 'Unknown',
    not_available: 'Not available',
    yes: 'Yes',
    no: 'No',
    none: 'None',
    close: 'Close',
    copy: 'Copy',
    copied: 'Copied',
    server_text: 'Server text, shown verbatim',
    utc: 'All times are UTC.',
    run: 'Run',
  },

  action: {
    copy_citation: 'Copy citation',
    copy_permalink: 'Copy permalink',
    download_csv: 'Download CSV',
    open_raw_json: 'Open raw JSON',
  },

  // StatusChip text: one entry per STATUS value and per ANOMALY_CHIP_KEYS
  // entry in src/lib/statusChip.js.
  status: {
    measured: 'Measured',
    not_measured: 'Not measured',
    outside_study_area: 'Outside study area',
    no_usable_data: 'No usable data',
    not_checked_yet: 'Not checked yet',
    not_evaluated: 'Risk not evaluated',
    stale: 'Stale',
    anomaly_normal: 'Not anomalous vs own history',
    anomaly_watch: 'Anomaly vs own history: watch',
    anomaly_high: 'Anomaly vs own history: high',
    anomaly_not_assessed: 'Anomaly not assessed',
    anomaly_normal_test: 'Not anomalous vs own history (TEST)',
    anomaly_watch_test: 'Anomaly vs own history: watch (TEST)',
    anomaly_high_test: 'Anomaly vs own history: high (TEST)',
    anomaly_not_assessed_test: 'Anomaly not assessed (TEST)',
  },

  // Status banner (src/lib/statusBanner.js BANNER_KEYS), dashboard spec §4.1.
  banner: {
    raster_unknown: 'The raster status could not be loaded, so whether anything was measured is unknown.',
    no_raster: 'No raster is available yet: nothing has been measured, which is not the same as "no bloom".',
    stale_run: 'Showing the last available raster (run {run}, target date {date}). A newer scan (run {stale_run}) has no picture to show: it is running, failed or expired.',
    poll_never: 'The check for newer scenes has not completed yet, so newer scenes may exist that were not checked.',
    poll_failing: 'The check for newer scenes is failing (error: {kind}; last success {last_ok}), so newer scenes may exist that were not checked.',
    poll_old: 'The last successful check for newer scenes was {hours} h ago ({last_ok}), so newer scenes may exist that were not checked.',
    scene_rejected_cloud: 'Newest acquisition {date} not used (cloud over water {cloud} > {threshold}); showing earlier data, newest scene {shown}.',
    scene_not_used: 'Newest acquisition {date} not used ({decision}); showing earlier data, newest scene {shown}.',
    scene_pending: 'Newest acquisition {date} passed the cloud and water screen but is not in the raster shown yet; newest scene shown {shown}.',
    indices_available: 'Index readings are available for {n} of {total} monitoring sites. Bloom risk is not evaluated: no validated baseline or calibrated risk rule exists.',
    no_site_readings: 'No monitoring site has a usable index reading: {no_usable} of {total} have no usable data and {not_checked} have not been checked yet.',
    raster_readings: 'Raster index readings are available (newest scene {date}); the monitoring-site summary could not be loaded. Bloom risk is not evaluated.',
    tiers_not_shown: 'The API returned a risk tier for {tiers} of {total} monitoring sites. This dashboard does not display risk tiers: no validated risk evaluation is documented.',
    test_baseline_version: 'TEST baseline version {version}',
    test_baseline_invalid: 'TEST baseline mode is on, but no TEST baseline can be used ({reason}); no anomaly values are shown.',
  },

  // Truth-boundary footer (dashboard spec §2 points 1-3) and the TEST
  // banner (test-baseline spec §5).
  truth: {
    heading: 'Truth boundary: what these data do and do not show',
    point_1: "Detection is at satellite pixel resolution: Sentinel-2 (native bands 10–20 m, read at each run's stated scale) and MODIS (Level-3 grid; size stated on the Methods page). It shows water-colour signatures only, never organisms.",
    point_2: 'Small or dispersed blooms may be missed.',
    point_3: 'Detection and prediction are separate claims. At present only index readings are reported: no Sentinel-2 anomaly score and no risk level, because no valid baseline exists. MODIS chlor_a z-scores are a separate, same-quantity calculation.',
    point_3_test: "Detection and prediction are separate claims. Index readings are reported with a provisional TEST anomaly against each location's own seasonal history, not calibrated against recorded events; there is no risk level. MODIS chlor_a z-scores are a separate, same-quantity calculation.",
    null_rule: '"—" means unknown, with the reason stated; it is never a zero or a low reading.',
    test_banner: "TEST baseline: anomalies are relative to the same location's own history; not yet calibrated against recorded events; not a bloom-risk assessment.",
    server_disclaimer: 'Server disclaimer (verbatim)',
    disclaimer_source: 'Received with {endpoint}',
    no_server_disclaimer: 'No server disclaimer has been received yet, so none is shown; the points above still apply.',
  },

  // Page footer (TruthFooter) beyond the truth-boundary points.
  footer: {
    version: 'App version',
    commit: 'commit',
    reproduce: 'Methods, data sources and limitations',
  },

  // TEST-baseline strip under the header (BaselineBanner).
  baseline: {
    badge: 'TEST',
    label: 'Baseline status',
    version: 'Version',
    methods_link: 'How the TEST baseline is built',
    unknown: 'The baseline mode could not be read (GET /methods failed), so whether a TEST baseline is in force is unknown here.',
  },

  // Why a value is "—" (src/lib/format.js NULL_REASONS).
  reason: {
    not_available: 'No value in the response.',
    invalid_value: 'The response value is not a valid number or date.',
    not_measured: 'No usable reading here (cloud, mask or no covering scene); not a low value.',
    outside_study_area: 'Outside the study polygon; not scanned.',
    no_usable_data: 'No usable data.',
    not_checked_yet: 'Not checked yet.',
    no_imagery: 'No usable Sentinel-2 scene in the search window.',
    no_water_pixels: 'No water pixel left after cloud and land masking.',
    no_climatology: 'No climatology available for comparison.',
    error: 'The reading failed on the server.',
    no_data_yet: 'No reading has been made for this site yet.',
    not_evaluated: 'Risk is not evaluated: no validated baseline or calibrated risk rule exists.',
    no_baseline: 'No baseline exists for this location.',
    insufficient_dates: 'Too few independent dates in the baseline.',
    insufficient_independent_dates: 'Too few independent dates in the baseline.',
    zero_mad: 'The baseline spread (MAD) is zero, so z cannot be computed.',
    incompatible_preprocessing: 'The baseline was made with different preprocessing, so it is not comparable.',
    too_old: 'The scene is older than the allowed observation age.',
    not_after_history: "The scene is not later than the baseline's history.",
    low_signal: 'A visible band is below the low-signal screen.',
    invalid: 'The reading is degenerate (for example NDCI exactly ±1).',
    site_not_in_baseline: 'This site is not in the baseline.',
    not_assessed_against_active_baseline: 'The cached reading was not assessed against the baseline version in force.',
    no_cached_reading_yet: 'No cached reading yet.',
    baseline_invalid: 'The TEST baseline cannot be used.',
    unreadable_band: 'This band could not be read here.',
  },

  // SourceChip popover rows (src/lib/provenance.js SOURCE_ROW_IDS).
  source: {
    heading: 'Source of this value',
    endpoint: 'Endpoint',
    field: 'Field',
    value: 'Value (as returned)',
    unit: 'Unit',
    observed_date: 'Observation date',
    run_id: 'Raster run',
    scene_id: 'Scene ID',
    formula: 'Formula',
    show: 'Show the source of {field}',
    unknown_field: 'this value',
  },

  // Value: the accessible text beside a "—".
  value: {
    unknown: 'Unknown: {reason}',
  },

  // FigureFrame.
  figure: {
    label: 'Fig. {n}',
    view_table: 'View the data table',
  },

  // CiteButton confirmation (aria-live).
  cite: {
    copied: 'Citation copied to the clipboard.',
    failed: 'The citation could not be copied automatically. Select the text below and copy it.',
    text_label: 'Citation text',
  },

  // ErrorState.
  error: {
    http: 'HTTP {status}',
    no_response: 'No response from the server: it may be stopped or unreachable.',
    request: 'Request',
    server_detail: 'Server message (verbatim)',
  },

  // Temporary pages for routes later tasks build (EmptyState).
  placeholder: {
    eyebrow: 'Not built yet',
    title: 'This page is a temporary placeholder',
    body: 'It belongs to a later step of the dashboard plan. Nothing on it is data, and its absence says nothing about the water.',
    site_label: 'Requested site ID',
    go_map: 'Open the raster map',
  },

  notfound: {
    title: 'Page not found',
    body: 'No page exists at {path}. The navigation above lists every page.',
    home: 'Go to the overview',
  },

  unit: {
    dimensionless: 'dimensionless',
    count: 'count',
    fraction: 'fraction (0–1)',
  },

  // Plain-text citation parts (src/lib/citation.js).
  citation: {
    heading: 'Cite this view',
    raster_run: 'raster run {run}',
    scenes: 'scenes {span}',
    test_baseline: 'TEST baseline {version}',
    accessed: 'accessed {date}',
    plain_text_note: 'Plain text; it records provenance only.',
  },
}
