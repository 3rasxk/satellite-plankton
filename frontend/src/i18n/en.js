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

  // Overview page (src/pages/OverviewPage.jsx, src/components/OverviewMapPreview.jsx;
  // messages built by src/lib/overviewModel.js).
  overview: {
    eyebrow: 'Upper Gulf of Thailand · Sentinel-2',
    lede: 'What the satellite measured, when, and how much of the study area has a reading. These are index readings only: not a bloom detection and not a risk level.',
    open_map: 'Open the raster map',
    status_heading: 'Status',
    facts_heading: 'Key facts',
    scene_heading: 'Scene selection',
    scene_label: 'Newest acquisition',
    poll_label: 'Newer-scene check',
    map_heading: 'Map preview',
    sites_heading: 'Monitoring sites',
    sites_lede: 'Seven fixed points read from the same Sentinel-2 scenes. Each name opens the site page.',
    server_reason: 'Server reason (verbatim)',
    server_error: 'Server error message (verbatim)',

    fact: {
      newest_scene: 'Newest scene date',
      newest_scene_note: 'Raster run {run}, target date {date_used}; the oldest cell is from {oldest}. Each cell keeps its own acquisition date.',
      newest_scene_unchecked: 'Newer scenes may exist that were not checked: see the newer-scene check below.',
      measured_area: 'Measured area',
      measured_unit: 'of the study polygon has a reading',
      measured_pixels: '{measured} of {polygon} overlay pixels inside the study polygon. The polygon includes land, so this is not a share of water.',
      measured_pixels_unknown: 'The measured pixel count was not recorded for this overlay ({polygon} pixels in the polygon). The polygon includes land, so this is not a share of water.',
      coverage_unknown: 'This overlay predates the coverage count, so the measured share is unknown, not zero.',
      not_measured_note: 'Not measured is not low: the rest is cloud, land or no covering scene.',
      scenes: 'Scenes mixed',
      scenes_unit: 'Sentinel-2 scenes',
      scenes_days: 'Cells come from {days} acquisition days ({span}); each cell keeps its own date.',
      scenes_days_unknown: 'The per-day breakdown was not recorded for this run: unknown, not evenly spread.',
      scenes_share: 'Largest share: {date}, {share} of the cells.',
      scenes_note: 'Scenes are tiles by date considered for the mosaic; some contribute no cells after masking.',
      scenes_link: 'Date shares on the raster map',
      sites: 'Sites with a usable reading',
      sites_unit: 'of {total} sites',
      sites_note: 'Index readings only; bloom risk is not evaluated.',
    },

    stale: {
      raster: 'Stale: this is the last good raster (run {run}); a newer scan (run {stale_run}) did not produce a picture.',
      sites: '{n} of {total} site readings are stale: their last refresh failed.',
      sites_strip: '{n} of {total} sites show a stale reading: their last refresh failed.',
    },

    // One distinct text per block and state (dashboard spec §10).
    state: {
      banner_loading: 'Loading the raster and site status…',
      raster_loading: 'Loading the raster status…',
      raster_error: 'The raster status could not be loaded, so what was measured is unknown here.',
      raster_empty: 'No raster has been produced yet, so nothing has been measured. This is not a low reading and not "no bloom".',
      summary_loading: 'Loading the monitoring-site summary…',
      summary_error: 'The monitoring-site summary could not be loaded, so the site counts are unknown.',
      summary_empty: 'The summary lists no monitoring sites, so there is nothing to count.',
      sites_loading: 'Loading the monitoring sites…',
      sites_error: 'The monitoring sites could not be loaded, so their status is unknown here.',
      sites_empty: 'The API returned no monitoring sites. This says nothing about the water.',
      pins_loading: 'Loading the pins of this run…',
      pins_error: 'The pins could not be loaded; the raster itself is unaffected.',
      map_empty_title: 'No map to preview',
    },

    // Latest-scene line (test-baseline spec §7). ≤ / > restate the server's
    // decision; they are not a comparison made here.
    scene: {
      none: 'No acquisition date has been assessed by the newer-scene check yet.',
      used: 'Newest assessed acquisition {date}: used in the raster shown (cloud over water {cloud} ≤ {threshold}).',
      used_other_run: 'Newest assessed acquisition {date}: passed (cloud over water {cloud} ≤ {threshold}) and used by run {run}, which is not the raster shown.',
      pending: 'Newest assessed acquisition {date}: passed the cloud and water screen (cloud over water {cloud} ≤ {threshold}) but is not in the raster shown yet.',
      rejected_cloud: 'Newest assessed acquisition {date}: not used (cloud over water {cloud} > {threshold}).',
      rejected_no_water: 'Newest assessed acquisition {date}: not used (fewer than {min} unmasked water pixels observed).',
      not_used: 'Newest assessed acquisition {date}: not used ({decision}).',
      reassessed_cloud: 'Newest assessed acquisition {date}: used by run {run}, then re-assessed as not passing (cloud over water {cloud} > {threshold}).',
      reassessed_other: 'Newest assessed acquisition {date}: used by run {run}, then re-assessed as not passing ({decision}).',
      shown: 'The raster shown (run {run}) has its newest scene on {shown}.',
      no_raster: 'No raster is being served.',
      settled: 'Decision final: assessed after every granule of that day had normally arrived.',
      settled_hours: 'Decision final: assessed at least {hours} h after the date began (UTC).',
      provisional: 'Provisional: tiles of this date may still be arriving, so the decision can change.',
      assessed_at: 'Assessed {at}.',
    },

    // Newer-scene poll line. A failing, missing or old poll means newer
    // scenes MAY exist unchecked; nothing here claims there is none.
    poll: {
      ok: 'Last successful check for newer scenes: {last_ok} ({age} ago).',
      ok_note: 'Scenes acquired or ingested after that check appear only after the next one.',
      old: 'The last successful check for newer scenes was {age} ago ({last_ok}), so newer scenes may exist that were not checked.',
      never: 'The check for newer scenes has not completed yet, so newer scenes may exist that were not checked.',
      failing: 'The check for newer scenes is failing (error kind {kind}, since {since}); last success {last_ok} ({age} ago). Newer scenes may exist that were not checked.',
      failing_never_ok: 'The check for newer scenes is failing (error kind {kind}, since {since}) and has never succeeded, so newer scenes may exist that were not checked.',
      recovered: 'An earlier failure ({kind}, {at}) was followed by a successful check.',
    },

    age: {
      unknown: '—',
      under_minute: 'under a minute',
      minutes: '{n} min',
      hours: '{n} h',
      days: '{n} d',
    },

    map: {
      alt: 'NDCI raster of run {run} over the study area, cells acquired {span}; transparent where nothing was measured.',
      caption: 'NDCI raster, run {run}: cells acquired {span}, read at {scale} m. North up, latitude–longitude grid.',
      extent_label: 'Extent',
      extent: '{south}–{north} N, {west}–{east} E',
      no_bounds: 'The raster has no valid geographic bounds, so it cannot be placed on a figure.',
      no_overlay: 'The raster has no overlay image to show.',
      image_error: 'The overlay image could not be loaded. The figure is blank because of the download, not because nothing was measured.',
      legend_heading: 'Legend',
      legend_ndci: 'NDCI (dimensionless): a display ramp, not a risk level',
      legend_no_data: 'Transparent: no usable reading (cloud, land mask or no covering scene), not a low or zero value.',
      legend_site: 'Monitoring site (fixed point)',
      server_meaning: 'Server legend text (verbatim)',
    },

    // Highlight / anomaly pins (dashboard spec §4.6, test-baseline spec §6).
    pins: {
      heading: 'Pins',
      heading_ndci: 'Highest NDCI in this scan',
      heading_anomaly: 'Anomaly pins (TEST)',
      legend_ndci: 'Numbered square: highest NDCI in this scan (a rank within one image), not a risk level.',
      legend_anomaly: "Numbered diamond: anomaly against the cell's own seasonal history (TEST), ranked by robust z; not a risk level.",
      caveat: 'High NDCI can also come from suspended sediment (e.g. river mouths), shallow bottom, sun glint or cloud edges; it does not by itself identify a bloom or a species.',
      anomaly_counts: '{assessable} of {measured} measured cells could be assessed against the TEST baseline; {flagged} met the TEST anomaly condition.',
      fewer: '{count} of {n} requested pins.',
      none: 'No pins in this run.',
      no_raster: 'No pins: no raster run is available to rank.',
      other_run: 'The pins returned belong to run {pins_run}, not to the raster shown (run {run}), so they are not drawn.',
      unknown_mode: 'The pins use a ranking this page does not know ({mode}), so they are not drawn.',
      outside_figure: 'Some pins lie outside the figure extent and are listed only.',
      rank: 'Rank',
      z: 'robust z',
      edge: 'Next to unmeasured area: cloud edges and masks can distort index values.',
      open: 'Open pin {rank} on the raster map',
      open_short: 'On the map',
    },

    sites: {
      date_label: 'Newest reading',
    },
  },
}
