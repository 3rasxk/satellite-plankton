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

  // Raster map page (src/pages/RasterPage.jsx and its components; messages
  // built by src/lib/mapModel.js). Pin and legend strings mention risk only
  // in the negation "not a risk level" (tests/pins.test.js).
  map: {
    title: 'Raster map',

    rail: {
      label: 'Map panel: layer, legend, pins and provenance',
      show: 'Show panel',
      hide: 'Hide panel',
      layers: 'Layer',
      legend: 'Legend',
      pins: 'Pins',
      scene: 'Scene selection',
      coverage: 'Coverage and sampling',
      dates: 'Acquisition dates',
      provenance: 'Run provenance',
    },

    layer: {
      group: 'Choose the map layer',
      true_color: 'True Color',
      light_map: 'Light Map',
      ndci: 'NDCI Raster',
      true_color_unavailable: 'No true-colour image matches this scan run',
      true_color_unavailable_title: 'This run stored no true-colour image, so True Color cannot be shown.',
      true_color_alt: 'Sentinel-2 true-colour image of the scan run shown',
      ndci_alt: 'NDCI index raster over the study area',
    },

    legend: {
      aria: 'Raster map legend',
      aria_caption: 'What transparent areas mean',
      title: 'NDCI index value (not a risk level)',
      transparent: 'Transparent areas have no usable reading: cloud, land or no covering scene.',
      transparent_strong: 'Not a low or zero index value.',
      note: 'Each cell is one real pixel with its own image date · the colour is the NDCI reading, not an anomaly.',
    },

    // RasterScanBanner (the "Coverage and sampling" section of the rail).
    banner: {
      headline: 'Raster over the whole study area',
      refresh: 'Load the latest result',
      refreshing: 'Loading…',
      loading: 'Loading the raster…',
      error: 'The raster could not be loaded —',
      error_strong: 'this does not mean no algae were found',
      error_rest: 'only that the stored result could not be read.',
      no_raster: 'No raster yet: a scan has to run first.',
      status_ok: 'Scan completed',
      status_no_data: 'No usable image in this run',
      status_error: 'The scan run failed',
      status_running: 'Scanning: the picture shown is still the previous run',
      stale: 'A newer scan run (run {stale_run}) has no picture to show: it is scanning, failed or was removed by age ·',
      stale_strong: 'every picture and number here belongs to run {run}, which is older than the newest run',
      target_date: 'Scan target date',
      newest: 'Newest image in this raster',
      oldest: 'oldest',
      days_before: '({n} days before the target date)',
      completed: 'This run was scanned on',
      target_not_data: 'The target date is not the date of the data: each cell keeps its own image date.',
      no_breakdown: 'This run did not record the per-day cell shares: only the date range is known, not how many cells each day gave —',
      no_breakdown_strong: 'which does not mean they are evenly spread',
      days_count: 'The stored cells have {n} acquisition days',
      top_day: 'the day with the most cells is',
      top_share: 'with {pct}% of all cells',
      scenes_considered: 'candidate images considered: {n} (some may leave no cell in the result)',
      cells_count: '{n} cells',
      range_note: 'A date range alone does not say which day most cells came from, so the per-day shares are shown too.',
      no_coverage: 'This run did not record the measured share of the area: no number is reported that was not measured.',
      coverage: 'A reading exists for {pct}% of the area inside the study polygon · the other {rest}% has no reading',
      denominator: 'The denominator is the whole area inside the polygon,',
      denominator_strong: 'land inside the polygon included',
      denominator_rest: '— the polygon is the study boundary, not a water mask, so this is not a share of “water”',
      pixels: '({measured} of {polygon} pixels of the overlay image)',
      unmeasured: 'The area without a reading is cloud, land or no covering image, reported as one state because the stored data cannot separate them ·',
      unmeasured_strong: 'not a low index value and not zero',
      sampling_a: 'One cell =',
      sampling_strong: 'one real pixel',
      sampling_b: 'picked by nearest neighbour',
      sampling_every: 'every {m} m',
      ratio10: 'sampling 1 in {n} pixels of the 10 m bands',
      ratio20: 'and 1 in {n} of the 20 m bands',
      not_average: 'not an average of the square drawn on screen',
      consequence: 'Anything smaller than the sampling interval is caught whole or missed whole, never diluted by averaging — a low cell is therefore no evidence about the water beside it.',
      click_hint: 'Click the map to read one cell at a time.',
      index_only: 'Index values only:',
      index_only_strong: 'no anomaly statistic is computed',
      index_only_rest: '— no usable index baseline exists, so there is no risk level and no verdict that algae were or were not found.',
      index_only_en: 'index values only — no anomaly detection active',
      test_only: 'Index values plus a provisional TEST anomaly against the same location’s own seasonal history,',
      test_only_strong: 'not calibrated against recorded events',
      test_only_rest: '— there is no risk level and no verdict that algae were or were not found.',
      test_only_en: 'index values with a TEST anomaly vs own history — not calibrated, no risk level',
    },

    run: {
      run_id: 'Raster run',
      status: 'Run status',
      date_used: 'Target date (not the date of the data)',
      scale_m: 'Read scale',
      completed_at: 'Run completed',
      cell_count: 'Cells with a reading',
      scene_count: 'Candidate scenes considered',
      scene_ids: 'Selected scene IDs ({n})',
      scene_ids_none: 'This run did not record its selected scene IDs.',
      none: 'No raster run is being served, so there is no provenance to show.',
    },

    chart: {
      caption: 'Share of the cells of run {run} by acquisition day ({days} days). Each cell keeps its own date; shares as recorded by the run.',
      alt: 'Bar chart of cell shares by acquisition day: {list}',
      date: 'Acquisition day (UTC)',
      share: 'Share of cells',
      cells: 'Cells',
      none: 'This run did not record the per-day breakdown: unknown, not evenly spread.',
    },

    pins: {
      heading: 'Pins',
      heading_ndci: 'Highest NDCI in this scan',
      heading_anomaly: 'Anomaly pins (TEST)',
      legend_ndci: 'Highest NDCI in this scan (rank within one image) — not a risk level',
      legend_anomaly: 'Anomaly vs own seasonal history, TEST baseline — not a risk level',
      shape_ndci: 'Numbered square',
      shape_anomaly: 'Numbered diamond',
      show: 'Show highlights',
      count: 'Number of pins (3–10)',
      hidden: 'Highlights are hidden on the map; the list stays available.',
      loading: 'Loading the pins of this run…',
      error: 'The pins could not be loaded. This is a failed request, not an absence of pins.',
      error_reason: 'Server reason: {reason}',
      none: 'No pins in this run.',
      no_raster: 'No pins: no raster run is available to rank.',
      other_run: 'The pins returned belong to run {pins_run}, not to the raster shown (run {run}), so they are not drawn.',
      unknown_mode: 'The pins use a ranking this page does not know ({mode}), so they are not drawn.',
      fewer: '{count} of {n} requested pins.',
      no_position: 'Some pins have no position and are listed only.',
      row_label_ndci: 'Pin {rank}: NDCI {ndci}',
      row_label_anomaly: 'Pin {rank}: robust z {z}, NDCI {ndci}',
      select: 'Show pin {rank} in the inspector and on the map',
      marker: 'Pin {rank}',
      edge: 'next to unmeasured area',
      list_label: 'Pins in rank order',
    },

    pin: {
      title: 'Pin {rank} of {count}',
      indices: 'Index values (this cell)',
      percentile: 'Percentile',
      percentile_ndci: 'Share of the {cohort} measured cells of this run with a lower NDCI, × 100. Relative to this run only.',
      percentile_anomaly: 'Share of the {assessable} assessable cells with a lower robust z, × 100. Relative to this run only.',
      acquired_date: 'Acquisition date (this cell)',
      acquired_at: 'Acquisition time (UTC)',
      cell: 'Observation (the sampled pixel)',
      centre: 'Centre of the drawn square (display only)',
      ranking: 'Ranking (server text, verbatim)',
      separation: 'Pins are at least {m} m apart (between cell coordinates); a closer, lower-ranked cell is skipped.',
      edge_true: 'Next to unmeasured area: cloud edges and masks can distort index values.',
      edge_false: 'Every neighbouring square inside the study polygon carries a reading.',
      edge_unknown: 'Whether this cell borders an unmeasured area was not reported.',
      bands: 'Visible bands (raw DN = reflectance × 10000)',
      bands_none: 'This run stored no visible bands, so the low-signal screen could not run for it.',
      caveat: 'High NDCI can also come from suspended sediment (e.g. river mouths), shallow bottom, sun glint or cloud edges; it does not by itself identify a bloom or a species.',
      zoom: 'Zoom to cell',
      inspect: 'Read this cell',
      csv_row: 'Download CSV row',
      disclaimer: 'Server disclaimer sent with these pins (verbatim)',
    },

    anomaly: {
      heading: 'Against its own seasonal history (TEST)',
      robust_z: 'robust z (TEST)',
      median_ndci: 'Baseline median NDCI',
      mad: 'Baseline MAD (unscaled)',
      n_dates: 'Independent dates in the baseline',
      level: 'Level',
      reason: 'Not assessed because',
      baseline_version: 'TEST baseline version',
      season_key: 'Season window',
      note: 'A provisional statistic for one sampled pixel against its own clear-sky record, not calibrated against recorded events; not a bloom detection.',
    },

    bands: {
      red: 'Red (B4)',
      green: 'Green (B3)',
      blue: 'Blue (B2)',
    },

    counts: {
      heading_anomaly: 'How the measured cells of this run were assessed',
      heading_ndci: 'Cells ranked in this run',
      intro_anomaly: 'Each measured cell is counted once: it could be compared with its own TEST baseline, or the first rule it failed is named. So "no pins" is different from "nothing assessed".',
      intro_ndci: 'The pins rank the measured cells of this one image by NDCI; no baseline is involved.',
      cohort: 'Measured cells ranked (overlay squares with a reading)',
      measured: 'Measured cells (overlay squares with a reading)',
      assessable: 'Could be compared with their own TEST baseline',
      not_assessable: 'Could not be compared, by the first rule failed:',
      invalid: 'Degenerate or invalid reading (e.g. NDCI exactly ±1, or acquired after the target date)',
      low_signal: 'Low signal: a visible band below the screen (developer-chosen, not validated)',
      too_old: 'Acquired too long before the target date',
      not_after_history: 'Acquired on or before the end of the baseline history (leakage guard)',
      no_baseline: 'No baseline cell at this location for the season',
      insufficient_dates: 'The baseline has too few independent dates',
      zero_mad: 'The baseline spread (MAD) is zero',
      condition: 'Of the assessable cells:',
      watch: 'Met the condition at watch level (TEST)',
      high: 'Met the condition at high level (TEST)',
      flagged_share: 'Share of assessable cells meeting the condition in this scan. A large share means the criterion fires often, not that blooms are widespread.',
      flagged_share_null: 'No cell was assessable, so there is no share.',
      partition_ok: 'Assessable plus not-assessable cells: {sum} = {measured} measured cells (the counts add up).',
      partition_mismatch: 'Assessable plus not-assessable cells: {sum}, but {measured} measured cells (off by {diff}); shown as received.',
      partition_unknown: 'Some counts are missing, so the partition cannot be checked.',
      quality: 'Data-quality screens (these cells are never pinned)',
      excluded_degenerate: 'Excluded: NDCI exactly ±1 (a zero band, not a water-colour value)',
      excluded_low_signal: 'Excluded: a visible band below the low-signal screen (developer-chosen, not validated)',
      excluded_low_signal_null: 'Screen not run: this run stored no visible bands.',
      quality_note: 'Server note on the screens (verbatim)',
    },

    cell: {
      region: 'Readings of the selected cell',
      title: 'Index values of the selected cell',
      loading: 'Reading the stored cell…',
      error: 'The cell could not be read —',
      error_strong: 'this does not mean no algae were found',
      error_rest: 'only that the stored data could not be read.',
      outside: 'Outside the study area: this point was not measured, so there is no value to report.',
      not_measured: 'No reading at this point: cloud, land or no covering image.',
      not_measured_strong: 'Not a low index value and not zero.',
      not_measured_causes: 'The stored data cannot tell the three causes apart, so they are reported as one state.',
      meaning: 'Server meaning of this state (verbatim)',
      unreadable: 'could not be computed (stored value not finite)',
      acquired_date: 'This cell’s acquisition date',
      acquired_at: 'Acquisition time (UTC)',
      cell: 'Observed pixel (where the measurement is)',
      centre: 'Centre of the drawn square (display only)',
      scale: 'Read scale',
      sampling: 'Each cell is one real nearest-neighbour pixel sampled every ~{scale} m, with its own image date; not an average of the square. An index reading, not a risk level.',
      sampling_unknown: 'Each cell is one real pixel, not an average of the square. An index reading, not a risk level.',
      no_anomaly: 'No anomaly assessment is returned for this cell.',
      download_csv: 'Download cell CSV',
      disclaimer: 'Server disclaimer sent with this cell (verbatim)',
    },

    actions: {
      label: 'Actions',
      permalink_copied: 'Permalink copied to the clipboard.',
      permalink_failed: 'The permalink could not be copied automatically; select it below.',
      permalink_label: 'Permalink',
    },

    truthbar: {
      label: 'Truth boundary',
      summary: 'Pixel-level water colour only; small blooms may be missed; not a risk level.',
    },

    permalink: {
      run_gone: 'The link named run {run}, which is no longer the run served. Showing the latest run ({latest}) instead; its values may differ.',
      run_gone_none: 'The link named run {run}, but no raster run is served now.',
      pin_gone: 'Pin {pin} of that run cannot be restored: pins belong to one run.',
      layer_unavailable: 'The linked True Color layer is not stored for this run, so NDCI is shown.',
      pin_missing: 'Pin {pin} from the link is not among the pins of this run.',
    },

    inspector: {
      label: 'Inspector',
      hint: 'Click the map to read one cell, or choose a pin.',
    },
  },
}
