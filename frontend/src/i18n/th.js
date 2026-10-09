/**
 * Thai dictionary (default language; formal, concise academic/official
 * register for researchers, competition judges and agency staff).
 *
 * Every key here must also exist in en.js with the same `{param}`
 * placeholders (tests/i18n.test.js). Scientific symbols, band names,
 * formulas, units, DOIs and API-supplied free text are never translated;
 * the server `disclaimer` is shown verbatim, not re-worded here.
 * "raster" is written แรสเตอร์, as elsewhere in this UI.
 *
 * Truth boundary (dashboard spec §2, test-baseline spec §5/§8): no string
 * presents a risk level except to deny one, and none says a bloom is
 * present or absent. Keys grow in later tasks; keep both files in step.
 */
export default {
  app: {
    name: 'Plankton Watch',
    tagline: 'ค่าดัชนีสีน้ำจากภาพถ่ายดาวเทียม Sentinel-2 และ MODIS บริเวณอ่าวไทยตอนบน',
  },

  nav: {
    main_label: 'เมนูหลัก',
    overview: 'ภาพรวม',
    map: 'แผนที่แรสเตอร์',
    sites: 'จุดเฝ้าระวัง',
    methods: 'วิธีการ',
    data: 'ข้อมูลและข้อจำกัด',
    cite: 'อ้างอิง',
    language: 'ภาษา',
    skip_to_content: 'ข้ามไปยังเนื้อหาหลัก',
  },

  common: {
    of: '{n} จาก {total}',
    loading: 'กำลังโหลด…',
    error: 'ไม่สามารถโหลดข้อมูลได้',
    retry: 'ลองอีกครั้ง',
    unknown: 'ไม่ทราบค่า',
    not_available: 'ไม่มีข้อมูล',
    yes: 'ใช่',
    no: 'ไม่ใช่',
    none: 'ไม่มี',
    close: 'ปิด',
    copy: 'คัดลอก',
    copied: 'คัดลอกแล้ว',
    server_text: 'ข้อความจากเซิร์ฟเวอร์ (แสดงตามต้นฉบับ)',
    utc: 'เวลาทั้งหมดเป็นเวลา UTC',
    run: 'รอบสแกน',
  },

  action: {
    copy_citation: 'คัดลอกข้อความอ้างอิง',
    copy_permalink: 'คัดลอกลิงก์ถาวร',
    download_csv: 'ดาวน์โหลด CSV',
    open_raw_json: 'เปิด JSON ต้นฉบับ',
  },

  // StatusChip text: one entry per STATUS value and per ANOMALY_CHIP_KEYS
  // entry in src/lib/statusChip.js.
  status: {
    measured: 'มีค่าตรวจวัด',
    not_measured: 'ไม่มีค่าตรวจวัด',
    outside_study_area: 'นอกพื้นที่ศึกษา',
    no_usable_data: 'ไม่มีข้อมูลที่ใช้ได้',
    not_checked_yet: 'ยังไม่ได้ตรวจสอบ',
    not_evaluated: 'ไม่ได้ประเมินความเสี่ยง',
    stale: 'ข้อมูลไม่เป็นปัจจุบัน',
    anomaly_normal: 'ไม่ผิดปกติเมื่อเทียบกับประวัติของตำแหน่ง',
    anomaly_watch: 'ผิดปกติเมื่อเทียบกับประวัติของตำแหน่ง: ระดับเฝ้าดู',
    anomaly_high: 'ผิดปกติเมื่อเทียบกับประวัติของตำแหน่ง: ระดับสูง',
    anomaly_not_assessed: 'ไม่ได้ประเมินค่าผิดปกติ',
    anomaly_normal_test: 'ไม่ผิดปกติเมื่อเทียบกับประวัติของตำแหน่ง (TEST)',
    anomaly_watch_test: 'ผิดปกติเมื่อเทียบกับประวัติของตำแหน่ง: ระดับเฝ้าดู (TEST)',
    anomaly_high_test: 'ผิดปกติเมื่อเทียบกับประวัติของตำแหน่ง: ระดับสูง (TEST)',
    anomaly_not_assessed_test: 'ไม่ได้ประเมินค่าผิดปกติ (TEST)',
  },

  // Status banner (src/lib/statusBanner.js BANNER_KEYS), dashboard spec §4.1.
  banner: {
    raster_unknown: 'ไม่สามารถโหลดสถานะของภาพแรสเตอร์ได้ จึงไม่ทราบว่ามีการตรวจวัดแล้วหรือไม่',
    no_raster: 'ยังไม่มีภาพแรสเตอร์ จึงยังไม่มีการตรวจวัดใด ๆ ซึ่งไม่ได้หมายความว่า "ไม่มีบลูม"',
    stale_run: 'แสดงภาพแรสเตอร์ล่าสุดที่มีอยู่ (รอบ {run} วันที่เป้าหมาย {date}) รอบสแกนที่ใหม่กว่า (รอบ {stale_run}) ยังไม่มีภาพให้แสดง เนื่องจากอยู่ระหว่างดำเนินการ ล้มเหลว หรือหมดอายุ',
    poll_never: 'การตรวจหาภาพถ่ายใหม่ยังไม่เคยดำเนินการสำเร็จ จึงอาจมีภาพใหม่กว่านี้ที่ยังไม่ได้ตรวจสอบ',
    poll_failing: 'การตรวจหาภาพถ่ายใหม่ขัดข้อง (ข้อผิดพลาด: {kind}; สำเร็จครั้งล่าสุด {last_ok}) จึงอาจมีภาพใหม่กว่านี้ที่ยังไม่ได้ตรวจสอบ',
    poll_old: 'การตรวจหาภาพถ่ายใหม่สำเร็จครั้งล่าสุดเมื่อ {hours} ชั่วโมงก่อน ({last_ok}) จึงอาจมีภาพใหม่กว่านี้ที่ยังไม่ได้ตรวจสอบ',
    scene_rejected_cloud: 'ภาพถ่ายใหม่สุดวันที่ {date} ไม่ได้นำมาใช้ (สัดส่วนเมฆเหนือผิวน้ำ {cloud} > {threshold}) จึงแสดงข้อมูลก่อนหน้า ซึ่งมีภาพใหม่สุดวันที่ {shown}',
    scene_not_used: 'ภาพถ่ายใหม่สุดวันที่ {date} ไม่ได้นำมาใช้ ({decision}) จึงแสดงข้อมูลก่อนหน้า ซึ่งมีภาพใหม่สุดวันที่ {shown}',
    scene_pending: 'ภาพถ่ายใหม่สุดวันที่ {date} ผ่านเกณฑ์เมฆและพื้นที่ผิวน้ำแล้ว แต่ยังไม่อยู่ในภาพแรสเตอร์ที่แสดง ภาพใหม่สุดที่แสดงคือวันที่ {shown}',
    indices_available: 'มีค่าดัชนีสำหรับจุดเฝ้าระวัง {n} จาก {total} จุด ไม่ได้ประเมินความเสี่ยงการเกิดบลูม เนื่องจากยังไม่มีบรรทัดฐานที่ผ่านการตรวจสอบหรือเกณฑ์ความเสี่ยงที่สอบเทียบแล้ว',
    no_site_readings: 'ยังไม่มีจุดเฝ้าระวังใดมีค่าดัชนีที่ใช้ได้ โดยไม่มีข้อมูลที่ใช้ได้ {no_usable} จาก {total} จุด และยังไม่ได้ตรวจสอบ {not_checked} จุด',
    raster_readings: 'มีค่าดัชนีจากภาพแรสเตอร์ (ภาพใหม่สุดวันที่ {date}) แต่ไม่สามารถโหลดสรุปจุดเฝ้าระวังได้ ทั้งนี้ไม่ได้ประเมินความเสี่ยงการเกิดบลูม',
    tiers_not_shown: 'API ส่งระดับความเสี่ยงมาสำหรับจุดเฝ้าระวัง {tiers} จาก {total} จุด แต่แดชบอร์ดนี้ไม่แสดงระดับความเสี่ยง เนื่องจากยังไม่มีการประเมินความเสี่ยงที่ผ่านการตรวจสอบ',
    test_baseline_version: 'บรรทัดฐานทดสอบรุ่น {version}',
    test_baseline_invalid: 'เปิดโหมดบรรทัดฐานทดสอบอยู่ แต่ไม่มีบรรทัดฐานทดสอบที่ใช้ได้ ({reason}) จึงไม่แสดงค่าผิดปกติ',
  },

  // Truth-boundary footer (dashboard spec §2 points 1-3) and the TEST
  // banner (test-baseline spec §5, wording fixed by the spec).
  truth: {
    heading: 'ขอบเขตของข้อมูล: สิ่งที่ข้อมูลนี้แสดงและไม่ได้แสดง',
    point_1: 'การตรวจจับอยู่ในระดับจุดภาพ (pixel) ของดาวเทียม ได้แก่ Sentinel-2 (แบนด์ความละเอียดดั้งเดิม 10–20 ม. อ่านค่าตามมาตราส่วนที่ระบุในแต่ละรอบสแกน) และ MODIS (กริด Level-3 ขนาดตามที่ระบุในหน้าวิธีการ) ข้อมูลแสดงเพียงลักษณะสีของน้ำ ไม่ใช่ตัวสิ่งมีชีวิต',
    point_2: 'บลูมที่มีขนาดเล็กหรือกระจายตัวอาจตรวจไม่พบ',
    point_3: 'การตรวจจับและการพยากรณ์เป็นข้อกล่าวอ้างที่แยกจากกัน ปัจจุบันรายงานเฉพาะค่าดัชนี ไม่มีคะแนนความผิดปกติของ Sentinel-2 และไม่มีระดับความเสี่ยง เนื่องจากยังไม่มีบรรทัดฐานที่ใช้ได้ ส่วนค่า z ของ chlor_a จาก MODIS เป็นการคำนวณแยกต่างหากที่เทียบกับปริมาณเดียวกัน',
    point_3_test: 'การตรวจจับและการพยากรณ์เป็นข้อกล่าวอ้างที่แยกจากกัน ระบบรายงานค่าดัชนีพร้อมค่าผิดปกติแบบทดสอบ (TEST) ซึ่งเทียบกับประวัติตามฤดูกาลของตำแหน่งเดียวกันและยังไม่ได้สอบเทียบกับเหตุการณ์จริง โดยไม่มีระดับความเสี่ยง ส่วนค่า z ของ chlor_a จาก MODIS เป็นการคำนวณแยกต่างหากที่เทียบกับปริมาณเดียวกัน',
    null_rule: '"—" หมายถึงไม่ทราบค่า โดยมีเหตุผลกำกับ และไม่ใช่ค่าศูนย์หรือค่าต่ำ',
    test_banner: 'บรรทัดฐานทดสอบ (TEST): ค่าผิดปกติเทียบกับประวัติของตำแหน่งเดียวกัน ยังไม่สอบเทียบกับเหตุการณ์จริง ไม่ใช่การประเมินความเสี่ยงบลูม',
    server_disclaimer: 'ข้อความกำกับจากเซิร์ฟเวอร์ (แสดงตามต้นฉบับ)',
  },

  // Why a value is "—" (src/lib/format.js NULL_REASONS).
  reason: {
    not_available: 'ไม่มีค่าในข้อมูลที่ได้รับ',
    invalid_value: 'ค่าที่ได้รับไม่ใช่ตัวเลขหรือวันที่ที่ถูกต้อง',
    not_measured: 'ไม่มีค่าที่ใช้ได้ ณ ตำแหน่งนี้ (เมฆ การมาสก์ หรือไม่มีภาพครอบคลุม) และไม่ใช่ค่าต่ำ',
    outside_study_area: 'อยู่นอกขอบเขตพื้นที่ศึกษา จึงไม่ได้สแกน',
    no_usable_data: 'ไม่มีข้อมูลที่ใช้ได้',
    not_checked_yet: 'ยังไม่ได้ตรวจสอบ',
    no_imagery: 'ไม่มีภาพ Sentinel-2 ที่ใช้ได้ในช่วงเวลาที่ค้นหา',
    no_water_pixels: 'ไม่มีจุดภาพผิวน้ำเหลือหลังการมาสก์เมฆและพื้นดิน',
    no_climatology: 'ไม่มีค่าภูมิอากาศวิทยา (climatology) สำหรับการเปรียบเทียบ',
    error: 'การอ่านค่าล้มเหลวที่เซิร์ฟเวอร์',
    no_data_yet: 'ยังไม่มีการอ่านค่าสำหรับจุดนี้',
    not_evaluated: 'ไม่ได้ประเมินความเสี่ยง เนื่องจากยังไม่มีบรรทัดฐานที่ผ่านการตรวจสอบหรือเกณฑ์ความเสี่ยงที่สอบเทียบแล้ว',
    no_baseline: 'ไม่มีบรรทัดฐานสำหรับตำแหน่งนี้',
    insufficient_dates: 'จำนวนวันที่อิสระในบรรทัดฐานไม่เพียงพอ',
    insufficient_independent_dates: 'จำนวนวันที่อิสระในบรรทัดฐานไม่เพียงพอ',
    zero_mad: 'ค่าการกระจาย (MAD) ของบรรทัดฐานเป็นศูนย์ จึงคำนวณค่า z ไม่ได้',
    incompatible_preprocessing: 'บรรทัดฐานสร้างด้วยการประมวลผลเบื้องต้นที่ต่างกัน จึงเปรียบเทียบกันไม่ได้',
    too_old: 'ภาพถ่ายเก่ากว่าอายุสูงสุดที่กำหนด',
    not_after_history: 'วันที่ของภาพไม่อยู่หลังช่วงประวัติของบรรทัดฐาน',
    low_signal: 'แบนด์ช่วงคลื่นที่ตามองเห็นบางแบนด์มีสัญญาณต่ำกว่าเกณฑ์คัดกรอง',
    invalid: 'ค่าที่อ่านได้ผิดรูป (เช่น NDCI เท่ากับ ±1 พอดี)',
    site_not_in_baseline: 'จุดนี้ไม่อยู่ในบรรทัดฐาน',
    not_assessed_against_active_baseline: 'ค่าที่บันทึกไว้ยังไม่ได้ประเมินเทียบกับบรรทัดฐานรุ่นที่ใช้อยู่',
    no_cached_reading_yet: 'ยังไม่มีค่าที่บันทึกไว้',
    baseline_invalid: 'ไม่สามารถใช้บรรทัดฐานทดสอบได้',
    unreadable_band: 'ไม่สามารถอ่านค่าแบนด์นี้ ณ ตำแหน่งนี้ได้',
  },

  // SourceChip popover rows (src/lib/provenance.js SOURCE_ROW_IDS).
  source: {
    heading: 'ที่มาของค่านี้',
    endpoint: 'ปลายทาง API',
    field: 'ฟิลด์ข้อมูล',
    value: 'ค่า (ตามที่ API ส่งมา)',
    unit: 'หน่วย',
    observed_date: 'วันที่ถ่ายภาพ',
    run_id: 'รอบสแกนแรสเตอร์',
    scene_id: 'รหัสภาพถ่าย',
    formula: 'สูตรคำนวณ',
  },

  unit: {
    dimensionless: 'ไม่มีหน่วย',
    count: 'จำนวน',
    fraction: 'สัดส่วน (0–1)',
  },

  // Plain-text citation parts (src/lib/citation.js).
  citation: {
    heading: 'อ้างอิงมุมมองนี้',
    raster_run: 'รอบสแกนแรสเตอร์ {run}',
    scenes: 'ภาพถ่ายดาวเทียมวันที่ {span}',
    test_baseline: 'บรรทัดฐานทดสอบ (TEST) {version}',
    accessed: 'สืบค้นเมื่อ {date}',
    plain_text_note: 'ข้อความธรรมดา ระบุเฉพาะที่มาของข้อมูล',
  },
}
