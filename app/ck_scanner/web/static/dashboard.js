let charts = [];
let chartFilter = { setup: "", label: "", sector: "" };
let filterOptionsLoaded = false;

function showTab(t) {
  ["action", "top", "screener", "ichimoku", "ma20ema", "sib", "charts"].forEach((x) => {
    let sec = document.getElementById("section" + cap(x));
    let tab = document.getElementById("tab" + cap(x));
    if (sec) sec.classList.toggle("active", x === t);
    if (tab) tab.classList.toggle("active", x === t);
  });
}
function cap(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

async function j(u) {
  let r = await fetch(u);
  if (!r.ok) throw new Error(u + " HTTP " + r.status);
  return await r.json();
}
function destroy() {
  charts.forEach((c) => {
    try {
      c && c.destroy && c.destroy();
    } catch (e) {}
  });
  charts = [];
}

function qs(extra = true) {
  let p = new URLSearchParams();
  for (let [id, key] of [
    ["date", "date"],
    ["start", "start"],
    ["end", "end"],
    ["ticker", "ticker"],
    ["sectorFilter", "sector"],
    ["actionFilter", "action"],
    ["breakoutFilter", "breakout"],
    ["minScore", "min_score"],
    ["minRR", "min_rr"],
    ["maxRisk", "max_risk"],
    ["minLiquidity", "min_liquidity"],
    ["presetFilter", "preset"],
  ]) {
    let v = document.getElementById(id)?.value;
    if (v) p.set(key, v);
  }
  if (extra && chartFilter.setup) p.set("setup", chartFilter.setup);
  if (extra && chartFilter.label) p.set("label", chartFilter.label);
  if (extra && chartFilter.sector) p.set("sector", chartFilter.sector);
  let s = p.toString();
  updatePresetHint();
  const rangeEl = document.getElementById("rangeText");
  if (rangeEl) {
    rangeEl.textContent = s
      ? "Đang lọc: " + s.replaceAll("&", " | ")
      : "Đang xem: tất cả dữ liệu";
  }
  return s ? "?" + s : "";
}

function fmt(v) {
  return v === null || v === undefined ? "—" : v;
}
function num(v, d = 0) {
  if (v === null || v === undefined || v === "") return "—";
  let n = Number(v);
  if (!Number.isFinite(n)) return v;
  return n.toLocaleString("vi-VN", {
    maximumFractionDigits: d,
    minimumFractionDigits: d,
  });
}
function price(v) {
  if (v === null || v === undefined || v === "") return "—";
  let n = Number(v);
  if (!Number.isFinite(n)) return v;
  return n.toLocaleString("vi-VN", {
    maximumFractionDigits: n >= 1000 ? 0 : 2,
  });
}
function priceAudit(r) {
  let latest = r["Giá mới nhất"];
  let scan = r["Giá lúc lọc"];
  let diff = r["Lệch giá %"];
  let hasLatest = latest !== null && latest !== undefined && latest !== "";
  let diffCls = Number(diff || 0) === 0 ? "muted" : Number(diff || 0) > 0 ? "txtGood" : "txtBad";
  return `<b>${price(hasLatest ? latest : scan)}</b><br><span class="muted">Lọc: ${price(scan)}</span>${hasLatest ? `<br><span class="${diffCls}">Mới: ${price(latest)} (${pct(diff)})</span><br><span class="muted">${esc(r["Nguồn giá"]||"")} ${esc(r["Ngày giá mới nhất"]||"")}</span>` : `<br><span class="muted">Chưa có giá đóng cửa</span>`}`;
}
function vol(v) {
  if (v === null || v === undefined) return "—";
  let n = Number(v);
  if (!Number.isFinite(n)) return v;
  if (Math.abs(n) >= 1000000)
    return (
      (n / 1000000).toLocaleString("vi-VN", { maximumFractionDigits: 2 }) + "M"
    );
  if (Math.abs(n) >= 1000)
    return (
      (n / 1000).toLocaleString("vi-VN", { maximumFractionDigits: 1 }) + "K"
    );
  return n.toLocaleString("vi-VN", { maximumFractionDigits: 0 });
}
function pct(v) {
  if (v === null || v === undefined) return "—";
  let n = Number(v);
  if (!Number.isFinite(n)) return v;
  return n.toLocaleString("vi-VN", { maximumFractionDigits: 2 }) + "%";
}
function badge(v) {
  v = v || "";
  let c =
    v.includes("Mua") || v.includes("Đã vượt") || v.includes("Vùng mua")
      ? "good"
      : v.includes("Không") || v.includes("Tránh")
        ? "bad"
        : "warn";
  return `<span class="pill ${c}">${v}</span>`;
}
function labelColor(v) {
  v = v || "";
  if (v.includes("Vùng mua")) return "#22c55e";
  if (v.includes("thăm dò")) return "#84cc16";
  if (v.includes("Chờ") || v.includes("Theo dõi")) return "#facc15";
  if (v.includes("Không") || v.includes("Tránh")) return "#ef4444";
  return "#60a5fa";
}
function rowClass(r) {
  let a = r.action_label || r.buy_zone_label || "";
  if (a.includes("Mua") || a.includes("Đã vượt")) return "good";
  if (a.includes("Không") || a.includes("Tránh")) return "bad";
  return "warn";
}
function changeCell(v) {
  if (v === null || v === undefined) return "<td></td>";
  let c = Number(v);
  let cls = c > 0 ? "good" : c < 0 ? "bad" : "warn";
  let sign = c > 0 ? "+" : "";
  return `<td><span class="pill ${cls}">${sign}${c.toLocaleString("vi-VN", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}%</span></td>`;
}

const DASH_ROWS = {};

function closeScoreModal() {
  document.getElementById("scoreModal").style.display = "none";
}

function esc(v) {
  return String(v ?? "").replace(
    /[&<>'"]/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[
        c
      ],
  );
}

async function fetchScoreExplain(r, scoreName) {
  let q = new URLSearchParams({
    ticker: r.ticker || "",
    signal_date: r.signal_date || "",
    score_name: scoreName,
  });
  let res = await fetch("/api/score/explain?" + q.toString());
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

function renderScoreExplain(ex) {
  let max = ex.max_score == null ? "" : `/${ex.max_score}`;
  let comps = (ex.components || [])
    .map(
      (c) =>
        `<div>${esc(c.name)}<br><span class="muted">${esc(c.reason || "")}</span></div><div><b>${c.score == null ? "—" : esc(c.score)}${c.max == null ? "" : "/" + esc(c.max)}</b></div>`,
    )
    .join("");
  let sug = ex.suggestions || {};
  let sugHtml = "";
  if (Object.keys(sug).length) {
    sugHtml =
      '<div class="helpLine">' +
      Object.entries(sug)
        .map(([k, v]) => `<b>${esc(k)}:</b> ${esc(v == null ? "—" : v)}`)
        .join("<br>") +
      "</div>";
  }
  return `<h2>${esc(ex.label || ex.score_name)}: ${esc(ex.ticker || "")}</h2><div class="scoreBig">${ex.score == null ? "—" : esc(ex.score)}${max}</div><div class="helpLine"><b>Rule:</b> ${esc(ex.rule_version || "—")}<br>${esc(ex.description || "")}</div><div class="formulaGrid">${comps}</div>${sugHtml}`;
}

async function showScoreExplain(el, i, scoreName) {
  let r = (DASH_ROWS[el] || [])[i];
  if (!r) return;
  let box = document.getElementById("scoreModalContent");
  box.innerHTML = "<h2>Đang tải diễn giải...</h2>";
  document.getElementById("scoreModal").style.display = "flex";
  try {
    let ex = await fetchScoreExplain(r, scoreName);
    box.innerHTML = renderScoreExplain(ex);
  } catch (e) {
    box.innerHTML = `<h2>Không tải được diễn giải</h2><div class="helpLine">${esc(e.message || e)}</div>`;
  }
}

function bDetail(r, el, i) {
  if (r.b_accumulation_score === null || r.b_accumulation_score === undefined)
    return "—";
  return `Nền ${num(r.b_tight_range_score, 0)} · Gần đỉnh ${num(r.b_near_high_score, 0)} · Vol cạn ${num(r.b_volume_dry_score, 0)} · Tiền ${num(r.b_accumulation_money_score, 0)} · Xả ${num(r.b_no_distribution_score, 0)} <button class="infoBtn" title="Click để xem công thức và giải thích chi tiết B-score" onclick="event.stopPropagation();showScoreExplain('${el}',${i},'B_ACCUMULATION')">?</button><br><span class="muted" title="Range20: biên nền; Cách đỉnh: khoảng cách tới high20; Dry: Vol TB5/TB20; UpVol: tỷ trọng volume phiên tăng; Dist: số phiên phân phối">Range ${pct(r.range20_pct)} · Cách đỉnh ${pct(r.distance_to_high20_pct)} · Dry ${num(r.vol_dry_ratio, 2)} · UpVol ${pct((r.up_volume_ratio_20 || 0) * 100)} · Dist ${num(r.distribution_days_20, 0)}</span>`;
}

function decisionCell(r, el, i) {
  return `<b>${num(r.decision_score, 0)}</b> <button class="infoBtn" title="Xem cách tính Điểm QĐ" onclick="event.stopPropagation();showScoreExplain('${el}',${i},'DECISION_SCORE')">?</button>`;
}

function pullbackCell(r, el, i) {
  if (r.pullback_quality_score == null) return "—";
  return `<b>${num(r.pullback_quality_score, 0)}</b> <button class="infoBtn" title="Xem cách tính điểm pullback đẹp" onclick="event.stopPropagation();showScoreExplain('${el}',${i},'PULLBACK_QUALITY')">?</button>`;
}

function pullbackZone(r) {
  return r.pullback_wait_low
    ? `${price(r.pullback_wait_low)} - ${price(r.pullback_wait_high)}<br><span class="muted">Bật lại &gt; ${price(r.pullback_rebound_trigger)} (${pct(r.pullback_to_trigger_pct)})</span>`
    : "—";
}

const PRESET_META = {
  "": { label: "Tất cả tín hiệu", hint: "Tất cả dữ liệu: chưa áp bộ lọc cố định." },
  actionable: { label: "Có thể hành động", hint: "Có thể hành động: Điểm QĐ ≥65, R/R ≥1.5, rủi ro ≤8%, Vol TB5 ≥1M. Đã nới theo backtest để không bỏ sót nhóm điểm 65-70." },
  backtest_edge: { label: "Backtest edge", hint: "Backtest edge: rủi ro ≤6%, R/R ≥1.5, Vol TB5 ≥1M và RSI/RVOL theo setup. Dựa trên backtest 65 mã × 65 ngày; dùng để xem danh sách ưu tiên thận trọng." },
  smart_market: { label: "Smart Market", hint: "Smart Market: lọc theo market regime, ưu tiên quality cao + false-break thấp + sector hỗ trợ." },
  quality_focus: { label: "Quality focus", hint: "Quality focus: lọc theo chất lượng setup tổng hợp — RS/Sector, risk, R/R, nền/pullback/retest, thanh khoản và không xa trigger." },
  low_false_break: { label: "Low false break", hint: "Low false break: ưu tiên setup có rủi ro phá vỡ giả thấp — không xa trigger, ít phân phối, RS/Sector ổn, R/R và risk đạt chuẩn." },
  volman_breakout: { label: "Volman nén BO", hint: "Volman nén breakout: nền chặt, gần high20, volume cạn, không xa trigger, R/R ổn và có RS/Sector hỗ trợ." },
  volman_retest: { label: "Volman retest", hint: "Volman retest: đã breakout/retest score tốt, giá quay lại gần vùng retest, không chase, RS/Sector còn ổn." },
  breakout_retest: { label: "Breakout canh retest", hint: "Breakout canh retest: Điểm retest ≥60. Dùng khi mã đã vượt mốc và cần canh vùng retest thay vì mua đuổi." },
  pullback_good: { label: "Pullback đẹp", hint: "Pullback đẹp: Pullback score ≥60. Dùng để tìm mã trong xu hướng tăng đang chờ bật lại." },
  accumulation_strong: { label: "Nền tích lũy mạnh", hint: "Nền tích lũy mạnh: B tích lũy ≥14. Dùng để tìm nền chặt/gần đỉnh/volume cạn/dòng tiền ổn." },
  sector_rs: { label: "Ngành/RS mạnh", hint: "Ngành/RS mạnh: Sector score ≥55 và Điểm QĐ ≥70. Dùng để ưu tiên mã có gió ngành hỗ trợ." },
  no_chase: { label: "Không mua đuổi", hint: "Không mua đuổi: loại trạng thái Không mua đuổi và rủi ro ≤10%. Dùng để bỏ bớt mã nóng/rủi ro cao." },
  trend_leader: { label: "Trend Leader", hint: "Trend Leader: proxy Minervini — RS Rank ≥70, Sector RS ≥55, R/R ≥1.5, risk ≤8%, không chase quá 5%." },
  canslim_technical: { label: "CANSLIM Technical", hint: "CANSLIM Technical: RS/Sector leader + nền tích lũy tốt + volume cạn + R/R/risk đạt; bản kỹ thuật, chưa dùng fundamental." },
  vcp_compression: { label: "VCP nén giá", hint: "VCP nén giá: nền chặt, range thấp, gần high20, volume cạn, ít phân phối, có RS/Sector hỗ trợ." },
  retest_priority: { label: "Retest ưu tiên", hint: "Retest ưu tiên: breakout đã có, giá quay lại gần vùng retest, R/R/risk đạt, RS/Sector hỗ trợ; tránh mua đuổi." },
};
const PRESET_HINTS = Object.fromEntries(Object.entries(PRESET_META).map(([k, v]) => [k, v.hint]));
const PRESET_LABELS = Object.fromEntries(Object.entries(PRESET_META).map(([k, v]) => [k, v.label]));

function presetLabel(key) {
  return PRESET_LABELS[key || ""] || PRESET_LABELS[""];
}

function syncPresetButtons() {
  let current = document.getElementById("presetFilter")?.value || "";
  document.querySelectorAll(".presetButtons button[data-preset]").forEach((btn) => {
    btn.classList.toggle("activePresetBtn", (btn.dataset.preset || "") === current);
  });
}

function updatePresetHint() {
  let p = document.getElementById("presetFilter")?.value || "";
  let el = document.getElementById("presetHint");
  if (el) el.textContent = PRESET_HINTS[p] || PRESET_HINTS[""];
  syncPresetButtons();
}

function applyPreset(name) {
  let p = document.getElementById("presetFilter");
  if (p) p.value = name || "";
  chartFilter = { setup: "", label: "", sector: "" };
  loadDash();
}

function setSelectIfExists(id, value) {
  let el = document.getElementById(id);
  if (!el) return;
  let v = value || "";
  if (
    v &&
    !Array.from(el.options || []).some((o) => o.value === v || o.text === v)
  ) {
    let opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    el.appendChild(opt);
  }
  el.value = v;
}

async function applyRowContext(el, i, targetTab = "screener") {
  let r = (DASH_ROWS[el] || [])[i];
  if (!r) return;

  // Drill-down rows should make the linked table obvious and reliable.
  // Older behavior stacked ticker + sector + action + setup/label, so a Top 20
  // click could look unchanged or over-filter the Screener. Keep the row click
  // focused on the ticker; users can add sector/action filters manually after.
  chartFilter = { setup: "", label: "", sector: "" };
  ["sectorFilter", "actionFilter", "breakoutFilter", "presetFilter", "minScore", "minRR", "maxRisk", "minLiquidity"].forEach((id) => {
    let e = document.getElementById(id);
    if (e) e.value = "";
  });

  let tickerInput = document.getElementById("ticker");
  if (tickerInput) tickerInput.value = r.ticker || "";

  await loadDash();
  showTab(targetTab);

  let range = document.getElementById("rangeText");
  if (range) {
    range.textContent = `Đang liên kết Top 20 → Bộ lọc nâng cao theo mã ${r.ticker || ""}. Có thể thêm lọc Ngành/Hành động sau.`;
  }

  let screener = document.getElementById("screener") || document.getElementById("sectionScreener");
  if (screener && screener.scrollIntoView) {
    screener.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}


const COL_HELP = {
  "Rank": {desc:"Thứ tự xếp hạng trong bảng hiện tại sau khi áp filter/preset.", formula:"Rank = vị trí sau khi sort. Top 20/Bộ lọc thường sort theo Điểm QĐ giảm dần; Top RS sort theo Điểm v2.1 rồi Điểm QĐ.", use:"Dùng để xem ưu tiên đọc trước, không phải điểm kỹ thuật."},
  "Ngày": {desc:"Ngày phát sinh tín hiệu/snapshot dữ liệu.", formula:"Lấy từ daily_signals.signal_date.", use:"Nếu bật lịch sử RS, cùng một mã có thể có nhiều ngày."},
  "Mã": {desc:"Mã cổ phiếu.", formula:"Lấy từ ticker trong daily_signals.", use:"Click dòng để drill-down theo mã."},
  "Ngành": {desc:"Ngành/sector của mã.", formula:"Lấy từ overlay ngành v2.1 nếu có.", use:"Dùng cùng Sector score để tránh chọn mã đẹp trong ngành yếu."},
  "Giá": {desc:"Giá hiển thị để tính risk/RR/trạng thái.", formula:"Ưu tiên daily_prices.close theo ngày tín hiệu. Nếu thiếu close thì dùng daily_signals.entry_price. Nếu dữ liệu close dạng nghìn VND thì chuẩn hóa về VND khi cần.", use:"Đây là giá căn cứ cho các cột R/R, risk, breakout/retest."},
  "% đổi": {desc:"% thay đổi giá trong khoảng ngày đang filter.", formula:"% đổi = (giá cuối khoảng - giá đầu khoảng) / giá đầu khoảng × 100.", use:"Xem mã đang tăng/giảm trong chính khoảng ngày đang lọc."},
  "Hành động": {desc:"Nhãn hành động tổng hợp do hệ thống suy luận.", formula:"Ưu tiên theo rule: Không mua đuổi → Mua thăm dò → Breakout tốt/canh retest → Đã breakout chờ volume/retest → Chờ vượt mốc → Pullback → Tích lũy → Theo dõi.", use:"Đây là nhãn đọc nhanh; quyết định cuối vẫn xem điểm, vùng mua, R/R, risk."},
  "Điểm QĐ": {desc:"Điểm quyết định tổng hợp để xếp hạng mã.", formula:"Điểm QĐ = action_score + breakout_score + volume_confirm_score + rr_score + risk_score + sector_rs_score - no_chase_penalty.", use:"Điểm càng cao càng đáng xem trước. Bấm nút ? trong ô điểm để xem breakdown theo mã."},
  "Pullback đẹp": {desc:"Điểm riêng cho setup pullback.", formula:"Chấm theo: khoảng cách tới vùng pullback, chất lượng bật lại, R/R, rủi ro, xu hướng/sector. Ngưỡng tham khảo: ≥75 đẹp, 60-74 theo dõi, <60 yếu.", use:"Dùng cho mã đang chờ nhịp chỉnh rồi bật lại, tránh mua đuổi."},
  "Vùng chờ PB": {desc:"Vùng giá chờ pullback và mốc bật lại.", formula:"Backend tính vùng chờ quanh MA/hỗ trợ gần nhất và mốc rebound trigger. Hiển thị dạng: vùng chờ thấp-cao + giá bật lại xác nhận.", use:"Canh giá rơi về vùng tốt rồi đợi vượt trigger mới hành động."},
  "B tích lũy": {desc:"Điểm nền tích lũy.", formula:"B = tight_range + near_high + volume_dry + accumulation_money + no_distribution. Ngưỡng: ≥17 nền mạnh, 14-16 nền ổn, <14 nền yếu.", use:"Dùng để tìm nền chặt, gần đỉnh, ít phân phối."},
  "B chi tiết": {desc:"Breakdown của B tích lũy.", formula:"Range20 đo độ chặt nền; Cách đỉnh đo khoảng cách tới high20; Dry = Vol TB5/TB20; UpVol = tỷ trọng volume phiên tăng; Dist = số phiên phân phối 20 phiên.", use:"Bấm ? trong ô B chi tiết để xem breakdown theo mã."},
  "Điểm HĐ": {desc:"Action score gốc từ scanner.", formula:"Điểm scanner ban đầu trước khi cộng thêm các overlay quyết định như breakout, volume, R/R, risk, sector.", use:"Dùng để biết tín hiệu gốc mạnh hay yếu."},
  "Giá vượt đề xuất": {desc:"Mốc giá cần đóng cửa vượt để xác nhận setup hiện tại.", formula:"Pullback: prev_high5 × 1.003 hoặc prev_close × 1.01. Tích lũy: high20_prev × 1.005. Dòng tiền: prev_high5/high20_prev × 1.003-1.005. Breakout: high20_prev × 1.005.", use:"Không mua chỉ vì chạm intraday; ưu tiên đóng cửa vượt mốc."},
  "Ghi chú điểm mua": {desc:"Lý do chọn mốc trigger.", formula:"Sinh theo setup_type: Pullback/Tích lũy/Dòng tiền/Breakout/Momentum.", use:"Đọc để hiểu trigger thuộc kiểu nào."},
  "Breakout": {desc:"Điểm mua breakout chuẩn.", formula:"Breakout buy price = high20_prev × 1.005.", use:"Dùng làm mốc xác nhận breakout."},
  "Điểm mua Breakout": {desc:"Điểm mua breakout chuẩn.", formula:"Breakout buy price = high20_prev × 1.005.", use:"Dùng làm mốc xác nhận breakout."},
  "Trạng thái": {desc:"Trạng thái breakout hiện tại.", formula:"Nếu thiếu high20_prev → Chưa đủ dữ liệu. Nếu giá hiện tại > high20_prev × 1.005 → Đã vượt mốc breakout. Ngược lại → Chờ giá đóng cửa > mốc.", use:"Cho biết mã đã vượt hay còn chờ xác nhận."},
  "Trạng thái Breakout": {desc:"Trạng thái breakout hiện tại.", formula:"Nếu thiếu high20_prev → Chưa đủ dữ liệu. Nếu giá hiện tại > high20_prev × 1.005 → Đã vượt mốc breakout. Ngược lại → Chờ giá đóng cửa > mốc.", use:"Cho biết mã đã vượt hay còn chờ xác nhận."},
  "Vol BO": {desc:"Tỷ lệ volume breakout.", formula:"Vol BO = volume hiện tại / volume trung bình 20 phiên trước. ≥1.2 có xác nhận, ≥1.5 mạnh.", use:"Breakout thiếu volume thì dễ false break/retest yếu."},
  "Điểm retest": {desc:"Điểm riêng cho setup breakout-retest.", formula:"Điểm retest = nền đã breakout + điểm sát vùng retest + volume breakout + R/R + risk + sector. Ngưỡng: ≥75 tốt, 60-74 theo dõi, <60 yếu.", use:"Dùng khi đã breakout nhưng không muốn mua đuổi, chờ retest."},
  "Vùng retest": {desc:"Vùng giá mua lại quanh mốc breakout.", formula:"Retest buy = high20_prev × 1.005. Vùng retest thấp = retest_buy × 0.99; cao = retest_buy × 1.015.", use:"Giá quay về vùng này và giữ được là điểm canh tốt hơn."},
  "Cách retest %": {desc:"Khoảng cách giá hiện tại tới mốc retest.", formula:"Cách retest % = (giá hiện tại / retest_buy_price - 1) × 100.", use:"Càng gần vùng retest thì càng đỡ mua đuổi."},
  "R/R": {desc:"Reward/Risk.", formula:"R/R = (target_1 - giá hiện tại) / (giá hiện tại - stoploss). Nếu thiếu dữ liệu dùng reward_risk gốc.", use:"Ưu tiên ≥1.5; tốt hơn nếu ≥2."},
  "Rủi ro %": {desc:"Khoảng cách tới stoploss.", formula:"Rủi ro % = (giá hiện tại - stoploss) / giá hiện tại × 100.", use:"Rủi ro càng thấp càng dễ quản trị vốn. Thường ưu tiên ≤8%."},
  "Vol TB5": {desc:"Volume trung bình 5 phiên gần nhất.", formula:"Vol TB5 = AVG(volume) của 5 phiên gần nhất đến ngày tín hiệu.", use:"Kiểm tra thanh khoản gần đây; mặc định preset dùng ≥1M."},
  "Lý do": {desc:"Tóm tắt lý do kỹ thuật.", formula:"Ghép từ setup, MA, RSI, MACD, volume, nền, breakout/pullback và cảnh báo.", use:"Đọc nhanh vì sao mã vào danh sách."},
  "Nhãn vùng mua": {desc:"Đánh giá vùng giá hiện tại.", formula:"Sinh từ scanner dựa trên vùng mua hợp lý, trạng thái mua đuổi, rủi ro và setup.", use:"Nếu là Không mua đuổi/Tránh thì không nên hành động dù điểm một số cột cao."},
  "Setup tags": {desc:"Các tag setup thực chiến mà mã đang đạt.", formula:"Sinh từ các preset/overlay như Trend Leader, CANSLIM Technical, VCP nén giá, Breakout Retest, Retest ưu tiên.", use:"Mã có nhiều tag đồng thuận đáng ưu tiên hơn, nhưng vẫn cần xem risk/R/R và điều kiện hủy."},
  "Setup": {desc:"Loại setup chính.", formula:"Phân loại từ scanner: Tích lũy, Pullback, Breakout/Vượt, Dòng tiền...", use:"Dùng để chọn cách vào lệnh phù hợp từng kiểu."},
  "Điểm v2.1": {desc:"Điểm nâng cấp v2.1.", formula:"Điểm scanner đã điều chỉnh thêm overlay RS/sector và các yếu tố v2.1.", use:"Dùng trong tab Top RS để ưu tiên mã có sức mạnh tương đối."},
  "RS20": {desc:"Sức mạnh tương đối 20 phiên.", formula:"RS20 ≈ hiệu suất 20 phiên của cổ phiếu - hiệu suất 20 phiên của VNINDEX.", use:"RS20 cao nghĩa là mã khỏe hơn thị trường trong 20 phiên."},
  "RS Rank": {desc:"Thứ hạng percentile của RS20 trong universe.", formula:"RS Rank = percentile của RS20 so với toàn bộ mã đang quét. 80 nghĩa là khỏe hơn khoảng 80% mã.", use:"Ưu tiên >70 nếu setup/risk/RR cũng ổn."},
  "Sector": {desc:"Điểm sức mạnh ngành.", formula:"Tổng hợp sức mạnh tương đối các mã trong cùng ngành/sector.", use:"Sector >55 là có hỗ trợ ngành; >70 là ngành mạnh."},
  "RS Rank": {desc:"Thứ hạng percentile của RS20 trong universe.", formula:"RS Rank = percentile của RS20 so với toàn bộ mã đang quét. 80 nghĩa là khỏe hơn khoảng 80% mã.", use:"Ưu tiên >70 nếu setup/risk/RR cũng ổn."},
  "Sector RS": {desc:"Điểm hỗ trợ ngành/sức mạnh tương đối ngành.", formula:"Sector RS = sector_score từ overlay v2.1; >55 là ngành hỗ trợ, >70 là ngành mạnh.", use:"Giúp tránh chọn mã đẹp trong ngành yếu."},
  "Volman": {desc:"Setup kiểu Bob Volman chuyển hóa sang cổ phiếu daily: nén giá, breakout/retest, không mua đuổi.", formula:"Dùng b_accumulation, range20, distance_to_high20, vol_dry, retest_distance, R/R, risk, RS Rank và Sector RS.", use:"Dùng như preset quan sát/backtest, chưa thay rule lõi."},
  "Kế hoạch mua": {desc:"Kế hoạch giao dịch gợi ý theo rank, regime, false-break, timing và risk.", formula:"Sinh từ final_rank_score, false_break_risk, setup trigger, stoploss, target, RS/Sector.", use:"Dùng như checklist hành động; không all-in và luôn tuân thủ điều kiện hủy."},
  "Tỷ trọng": {desc:"Tỷ trọng gợi ý so với vị thế kế hoạch, không phải toàn bộ tài khoản.", formula:"Rank cao + false-break thấp + risk thấp => tỷ trọng cao hơn; Defensive/unclear => giảm tỷ trọng.", use:"Chia lệnh 2 lần, không mua toàn bộ một lần."},
  "Điều kiện hủy": {desc:"Điều kiện khiến kèo không còn hợp lệ.", formula:"Xa trigger, false-break cao, sector/RS yếu, thủng stop/trigger, VNINDEX Defensive.", use:"Nếu điều kiện hủy xảy ra thì không mua hoặc giảm/thoát."},
  "Rank thực chiến": {desc:"Điểm xếp hạng cuối cho Top 20.", formula:"Final rank = Decision Score 35% + Quality 35% - False Break 20% + Regime fit/RR/Risk bonus.", use:"Dùng để xếp thứ tự thực chiến; Decision Score vẫn giữ làm tham chiếu."},
  "Quality": {desc:"Điểm chất lượng setup tổng hợp.", formula:"Quality = RS + Sector + risk thấp + R/R + nền/pullback/retest + volume + timing + ít phân phối - chase risk.", use:"Dùng để xếp ưu tiên sâu hơn Decision Score, chưa thay core rule."},
  "False break": {desc:"Rủi ro phá vỡ giả.", formula:"Tăng khi xa trigger, breakout thiếu volume, RS thấp, sector yếu, phân phối cao, R/R thấp hoặc risk cao.", use:"Ưu tiên thấp; nếu cao thì chờ retest/không mua đuổi."},

  "Timing": {desc:"Nhãn timing Ichimoku sau khi kết hợp D1 setup và 15M timing.", formula:"Sinh từ Timing Score: D1 setup/activation + 15M breakout Tenkan65 + volume + no-chase.", use:"Ưu tiên Timing đẹp/Kích hoạt mạnh; Watch D1 chỉ để theo dõi, chưa phải tín hiệu mua."},
  "Timing score": {desc:"Điểm timing tổng hợp cho tab Ichimoku.", formula:"Timing score = D1 setup score + 15M timing score + volume score + no-chase/risk score + điểm nền.", use:"Dùng để xếp hạng riêng trong tab Ichimoku. Điểm cao hơn nghĩa là setup/timing đồng thuận hơn."},
  "D1": {desc:"Điểm setup Ichimoku trên khung ngày.", formula:"Chấm theo khoảng cách giá với Tenkan65/Kijun129, trạng thái vượt trigger, không mua đuổi và chất lượng setup D1.", use:"D1 dùng để chọn mã. Không mua chỉ vì 15M đẹp nếu D1 chưa đạt setup."},
  "15M": {desc:"Điểm xác nhận timing trên khung 15 phút.", formula:"Chấm theo việc giá 15M vượt Tenkan65/Kijun129, điểm 15M và khoảng cách với Tenkan65.", use:"15M chỉ dùng để canh điểm vào sau khi D1 đã đạt setup."},
  "Khung đạt": {desc:"Các khung thời gian Ichimoku đang đạt điều kiện.", formula:"Tổng hợp từ 15m, 1h, 1D theo Tenkan/Kijun 9/17/65/129.", use:"Càng nhiều khung đồng thuận càng tốt, nhưng vẫn ưu tiên D1 trước."},
  "Điểm": {desc:"Điểm xếp hạng Ichimoku MTF gốc.", formula:"Tổng hợp điểm Ichimoku đa khung trước khi thêm Timing Score mới.", use:"Dùng tham khảo; Timing score quan trọng hơn cho quyết định timing."},
  "Vùng mua": {desc:"Vùng giá hợp lý để canh mua.", formula:"Tính quanh giá hiện tại, trigger Ichimoku và biên rủi ro cho phép.", use:"Không mua nếu giá đã vượt xa vùng mua cao/trigger."},
  "Trigger": {desc:"Mốc giá cần vượt/giữ để xác nhận setup.", formula:"Dựa trên Tenkan65/Kijun129 hoặc vùng breakout gần nhất.", use:"Ưu tiên đóng nến vượt trigger, không chỉ chạm intraday."},
  "Stoploss": {desc:"Mốc dừng lỗ kỹ thuật.", formula:"Đặt dưới vùng hỗ trợ/trigger/Ichimoku gần nhất theo rule scanner.", use:"Nếu rủi ro % quá cao thì bỏ qua hoặc giảm tỷ trọng."},
  "Mục tiêu gần": {desc:"Target gần cho setup Ichimoku.", formula:"Tính từ vùng mua/trigger theo biên lợi nhuận mục tiêu đầu tiên.", use:"Dùng cùng R/R để quyết định có đáng vào lệnh không."},
  "Volume": {desc:"Xác nhận volume cho setup Ichimoku.", formula:"So sánh volume hiện tại hoặc 15M với trung bình gần đây; relvol ≥1.2 là xác nhận cơ bản.", use:"Breakout/timing thiếu volume có xác suất false break cao hơn."},
  "Xác nhận": {desc:"Điều kiện cần có để setup hợp lệ.", formula:"Sinh theo trạng thái Ichimoku: đóng nến vượt trigger, volume xác nhận, đa khung đồng thuận.", use:"Chỉ hành động khi điều kiện xác nhận xảy ra."},
  "Hủy": {desc:"Điều kiện khiến setup không còn hợp lệ.", formula:"Giá mất trigger, thủng stoploss, chạy xa vùng mua, volume yếu hoặc market xấu.", use:"Nếu điều kiện hủy xuất hiện thì không mua hoặc loại khỏi watchlist."},
};

function showColHelp(name) {
  const h = COL_HELP[name] || { desc: "Chưa có giải thích cho cột này.", formula: "—", use: "—" };
  document.getElementById("scoreModalContent").innerHTML = `
    <h2>${esc(name)}</h2>
    <div class="helpLine"><b>Ý nghĩa:</b><br>${esc(h.desc || "—")}</div>
    <div class="helpLine"><b>Cách tính / nguồn dữ liệu:</b><br>${esc(h.formula || "—")}</div>
    <div class="helpLine"><b>Cách dùng thực tế:</b><br>${esc(h.use || "—")}</div>
  `;
  document.getElementById("scoreModal").style.display = "flex";
}


function sectorRsBadge(r) {
  let rs = Number(r.rs_rank_pct);
  let sec = Number(r.sector_score);
  let ok = (Number.isFinite(rs) && rs >= 70) && (Number.isFinite(sec) && sec >= 55);
  let warn = (Number.isFinite(rs) && rs >= 55) || (Number.isFinite(sec) && sec >= 55);
  return `<span class="pill ${ok ? "good" : warn ? "warn" : "bad"}">RS ${num(r.rs_rank_pct,0)} · Ngành ${num(r.sector_score,0)}</span>`;
}

function showRowDetail(el, i) {
  let r = (DASH_ROWS[el] || [])[i];
  if (!r) return;
  document.getElementById("scoreModalContent").innerHTML = `
    <h2>Chi tiết ${esc(r.ticker || "")}</h2>
    <div class="helpLine"><b>Ngày:</b> ${esc(r.signal_date || "—")} · <b>Ngành:</b> ${esc(r.sector || "—")} · <b>Setup:</b> ${esc(r.setup_type || "—")}</div>
    <div class="detailSection">1. Kế hoạch giao dịch</div>
    <div class="formulaGrid">
      <div><b>Giá / nguồn</b><br>${price(r.entry_price)} · <span class="muted">${esc(r.price_source || "")}</span></div><div>${badge(r.action_label)}</div>
      <div><b>Điểm QĐ</b><br>${num(r.decision_score,0)} = HĐ ${num(r.action_score,0)} + BO ${num(r.breakout_score,0)} + Vol ${num(r.volume_confirm_score,0)} + RR ${num(r.rr_score,0)} + Risk ${num(r.risk_score,0)} + Sector ${num(r.sector_rs_score,0)} + penalty ${num(r.no_chase_penalty,0)}</div><div><button class="infoBtn" onclick="showScoreExplain('${el}',${i},'DECISION_SCORE')">?</button></div>
      </div><div class="detailSection">2. Điểm / RS / Sector</div><div class="formulaGrid"><div><b>RS / Sector RS</b><br>RS20 ${num(r.rs20,2)} · RS Rank ${num(r.rs_rank_pct,0)} · Sector ${num(r.sector_score,0)} · Sector bonus ${num(r.sector_rs_score,0)}</div><div>${sectorRsBadge(r)}</div>
      <div><b>Volman-style</b><br>${esc(r.volman_setup || "—")} · ${esc(r.volman_quality || "—")}<br><span class="muted">${esc(r.volman_warning || "")}</span></div><div>${esc(r.volman_setup || "—")}</div>
      <div><b>Rank thực chiến</b><br>${num(r.final_rank_score,0)} · ${esc(r.rank_reason || "—")}</div><div>Final</div>
      <div><b>Kế hoạch mua</b><br>${esc(r.trade_plan || "—")}<br><span class="muted">${esc(r.suggested_position || "")}</span></div><div>${esc(r.valid_entry || "—")}</div>
      <div><b>Stop / Target</b><br>Stop ${price(r.plan_stoploss)} · Target ${price(r.plan_target_near)}<br><span class="muted">${esc(r.target_plan || "")}</span></div><div>Risk plan</div>
      <div><b>Điều kiện hủy</b><br>${esc(r.cancel_condition || "—")}<br><span class="muted">${esc(r.capital_note || "")}</span></div><div>Cancel</div>
      <div><b>Quality / False break</b><br>Quality ${num(r.quality_score,0)} · False-break ${num(r.false_break_risk_score,0)}<br><span class="muted">${esc(r.false_break_risk_label || "")} · ${esc(r.regime_fit || "")}</span></div><div>${esc(r.false_break_risk_label || "—")}</div>
      </div><div class="detailSection">3. Setup kỹ thuật đầy đủ</div><div class="formulaGrid"><div><b>B tích lũy</b><br>${bDetail(r, el, i)}</div><div>${num(r.b_accumulation_score,0)}</div>
      <div><b>Pullback</b><br>${pullbackZone(r)}</div><div>${pullbackCell(r, el, i)}</div>
      <div><b>Breakout</b><br>Mốc ${price(r.breakout_buy_price)} · ${esc(r.breakout_status || "—")} · Vol BO ${num(r.breakout_volume_ratio,2)}</div><div>${num(r.breakout_score,0)}</div>
      <div><b>Retest</b><br>${r.retest_buy_price ? price(r.retest_zone_low) + " - " + price(r.retest_zone_high) + " · cách " + pct(r.retest_distance_pct) : "—"}</div><div>${num(r.retest_setup_score,0)}</div>
      <div><b>Timing mua</b><br>${esc(r.suggested_buy_timing || "—")}<br><span class="muted">${esc(r.timing_probability_note || "")}</span></div><div>${esc(r.timing_warning || "—")}</div>
      <div><b>R/R · Rủi ro · Vol</b><br>R/R ${num(r.reward_risk,2)} · Risk ${pct(r.risk_pct)} · Vol TB5 ${vol(r.avg_volume5_latest)}</div><div>${badge(r.buy_zone_label)}</div>
      <div><b>Lý do</b><br>${esc(r.main_reason || "—")}</div><div><b>Cảnh báo</b><br>${esc(r.warning || "—")}</div>
    </div>`;
  document.getElementById("scoreModal").style.display = "flex";
}

function thHelp(x) {
  const label = String(x);
  const raw = label.replace(/<[^>]+>/g, "").replace(/[?]/g, "").trim();
  if (label.includes("infoBtn") || label.includes("showColHelp(")) return label;
  if (!COL_HELP[raw]) return label;
  const safe = raw.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
  return `${label} <button class="infoBtn" title="Giải thích cột ${esc(raw)}" onclick="event.stopPropagation();showColHelp('${safe}')">?</button>`;
}


function actionGroupClass(k) {
  return k === "actionable" ? "good" : k === "watch" ? "warn" : "bad";
}
function actionExplainHtml(ex) {
  if (!ex) return "";
  const criteria=(ex.criteria||[]).map(x=>`<li>${esc(x)}</li>`).join("");
  const dos=(ex.do||[]).map(x=>`<li>${esc(x)}</li>`).join("");
  const avoid=(ex.avoid||[]).map(x=>`<li>${esc(x)}</li>`).join("");
  return `<div class="actionExplain"><b>${esc(ex.meaning||"")}</b><div class="explainCols"><div><span class="muted">Điều kiện</span><ul>${criteria}</ul></div><div><span class="muted">Nên làm</span><ul>${dos}</ul></div><div><span class="muted">Tránh</span><ul>${avoid}</ul></div></div></div>`;
}
function renderActionRows(rows, key = "actionBoard") {
  if (!rows || !rows.length) return '<div class="muted emptyGroup">Không có mã trong nhóm này.</div>';
  DASH_ROWS[key] = rows;
  return `<table class="miniTable actionTable"><thead><tr>${["Mã","Giá","Trạng thái","Vùng mua","Trigger","Stop","Target","R/R","Tỷ trọng","Hủy nếu","Lý do"].map(x=>`<th>${thHelp(x)}</th>`).join("")}</tr></thead><tbody>` + rows.map((r,i)=>`<tr class="${rowClass(r)} clickableRow" onclick="showRowDetail('${key}',${i})"><td><b>${esc(r.ticker)}</b><br><span class="muted">${esc(r.sector||"")}</span></td><td>${price(r.entry_price)}</td><td>${badge(r.action_status)}${actionExplainHtml(r.action_explain)}</td><td>${esc(r.entry_zone||"—")}</td><td>${price(r.trigger_price)}</td><td>${price(r.stoploss)}</td><td>${price(r.target)}</td><td>${num(r.reward_risk,2)}</td><td>${esc(r.position_size||"—")}</td><td>${esc(r.cancel_condition||"—")}</td><td><b>${esc(r.action_reason||"—")}</b><br><span class="muted">${esc(r.main_reason_short||"")}</span></td></tr>`).join("") + '</tbody></table>';
}
async function loadActionBoard() {
  let wrap = document.getElementById("actionBoard");
  if (!wrap) return;
  try {
    let data = await j("/api/action/today" + qs());
    let s = data.summary || {};
    let m = data.market || {};
    window.CURRENT_ACTION_DATE = data.date || "";
    document.getElementById("actionSummary").innerHTML = `<b>Ngày:</b> ${esc(data.date||"—")} · <b>VNINDEX:</b> ${esc(data.market_regime||"—")} · <b>Action:</b> ${num(s.actionable,0)} · <b>Watch:</b> ${num(s.watch,0)} · <b>No chase:</b> ${num(s.no_chase,0)} · <b>Cancel:</b> ${num(s.cancel,0)}<br><span class="muted">${esc(m.strategy||"")}</span><div class="snapshotLinks">Snapshot: <a href="/api/action/snapshot/save" target="_blank">lưu hôm nay</a> · <a href="/api/action/snapshots" target="_blank">lịch sử</a> · <a href="/api/action/compare" target="_blank">so sánh D/D-1</a></div>`;
    const order=["actionable","watch","no_chase","cancel"];
    wrap.innerHTML = order.map(k=>{let g=data.groups[k]||{label:k,rows:[]}; return `<div class="actionGroup card"><h3><span class="pill ${actionGroupClass(k)}">${esc(g.label)}</span> <span class="muted">${g.count||0} mã</span></h3>${renderActionRows(g.rows||[], `action_${k}`)}</div>`}).join("");
  } catch(e) {
    wrap.innerHTML = `<div class="helpLine txtBad">Không tải được Daily Action Board: ${esc(e.message||e)}</div>`;
  }
}

async function exportTradingPlan() {
  const btn = document.getElementById("exportTradingPlanBtn");
  const st = document.getElementById("tradingPlanExportStatus");
  const date = window.CURRENT_ACTION_DATE || (document.getElementById("end")?.value || "");
  if (btn) btn.disabled = true;
  if (st) st.innerHTML = "Đang xuất Trading Plan...";
  try {
    const data = await j("/api/trading-plan/export" + (date ? `?date=${encodeURIComponent(date)}` : ""));
    if (st) st.innerHTML = `Đã xuất <b>${esc(data.date||date||"—")}</b>: <a href="${esc(data.out||"")}" target="_blank">${esc(data.out||"")}</a> · ${num(data.rows,0)} dòng · Ichimoku ${num(data.ichimoku_rows,0)} dòng`;
  } catch(e) {
    if (st) st.innerHTML = `<span class="txtBad">Xuất lỗi: ${esc(e.message||e)}</span>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

function table(el, rows, mode) {
  DASH_ROWS[el] = rows;
  const isTop = mode === "top";
  let h = isTop
    ? ["Rank", "Ngày", "Mã", "Ngành", "Giá", "Hành động", "Setup tags", "BUY_SCORE", "Nhãn mua", "Rank thực chiến", "Quality", "False break", "Regime fit", "R/R", "Rủi ro %", "Kế hoạch mua", "Tỷ trọng", "Entry hợp lệ", "Điều kiện hủy", "Chi tiết"]
    : ["Ngày", "Mã", "Ngành", "Giá", "% đổi", "Hành động", "Setup tags", "BUY_SCORE", "Nhãn mua", "Rank thực chiến", "Quality", "False break", "Regime fit", "Setup", "R/R", "Rủi ro %", "Kế hoạch mua", "Tỷ trọng", "Điều kiện hủy", "Chi tiết"];
  let body = rows.map((r, i) =>
    isTop
      ? `<tr class="${rowClass(r)} clickableRow" title="Click để liên kết sang Bộ lọc nâng cao" onclick="applyRowContext('${el}',${i},'screener')"><td>${i + 1}</td><td>${r.signal_date}</td><td><b>${r.ticker}</b></td><td>${r.sector || ""}</td><td>${price(r.entry_price)}</td><td>${badge(r.action_label)}</td><td>${esc(r.setup_tags || "—")}</td><td><b>${num(r.buy_score,0)}</b><br><span class="muted">${esc(r.buy_score_reason || "")}</span></td><td>${badge(r.buy_label || "—")}</td><td><b>${num(r.final_rank_score,0)}</b><br><span class="muted">${r.rank_reason || ""}</span></td><td><b>${num(r.quality_score,0)}</b></td><td>${num(r.false_break_risk_score,0)}<br><span class="muted">${r.false_break_risk_label || ""}</span></td><td>${r.regime_fit || "—"}</td><td>${num(r.reward_risk,2)}</td><td>${pct(r.risk_pct)}</td><td>${r.trade_plan || "—"}</td><td>${r.suggested_position || "—"}</td><td>${r.valid_entry || "—"}</td><td>${r.cancel_condition || "—"}</td><td><button class="detailBtn" title="Xem chi tiết đầy đủ" onclick="event.stopPropagation();showRowDetail('${el}',${i})">Chi tiết</button></td></tr>`
      : `<tr class="${rowClass(r)} clickableRow" title="Click để liên kết theo mã/ngành/hành động" onclick="applyRowContext('${el}',${i},'screener')"><td>${r.signal_date}</td><td><b>${r.ticker}</b></td><td>${r.sector || ""}</td><td>${price(r.entry_price)}</td>${changeCell(r.change_pct)}<td>${badge(r.action_label)}</td><td>${esc(r.setup_tags || "—")}</td><td><b>${num(r.buy_score,0)}</b><br><span class="muted">${esc(r.buy_score_reason || "")}</span></td><td>${badge(r.buy_label || "—")}</td><td><b>${num(r.final_rank_score,0)}</b><br><span class="muted">${r.rank_reason || ""}</span></td><td><b>${num(r.quality_score,0)}</b></td><td>${num(r.false_break_risk_score,0)}<br><span class="muted">${r.false_break_risk_label || ""}</span></td><td>${r.regime_fit || "—"}</td><td>${r.setup_type || ""}</td><td>${num(r.reward_risk,2)}</td><td>${pct(r.risk_pct)}</td><td>${r.trade_plan || "—"}</td><td>${r.suggested_position || "—"}</td><td>${r.cancel_condition || "—"}</td><td><button class="detailBtn" title="Xem chi tiết đầy đủ" onclick="event.stopPropagation();showRowDetail('${el}',${i})">Chi tiết</button></td></tr>`
  ).join("");
  document.getElementById(el).innerHTML = "<thead><tr>" + h.map((x) => `<th>${thHelp(x)}</th>`).join("") + "</tr></thead><tbody>" + body + "</tbody>";
}


function showTabHelp(tab) {
  const content = {
    action: {
      title: "Kế hoạch hôm nay",
      body: `<div class="helpLine"><b>Mục tiêu:</b> chuyển Top20/scoring thành hành động rõ: mua thăm dò, chờ xác nhận, không mua đuổi, hủy/loại.</div><div class="formulaGrid"><div><b>Có thể hành động</b><br><span class="muted">Điểm/quality/RR/risk đạt, false-break thấp, VNINDEX không Defensive.</span></div><div><b>Action</b></div><div><b>Chờ xác nhận</b><br><span class="muted">Setup ổn nhưng cần trigger, volume hoặc regime xác nhận.</span></div><div><b>Watch</b></div><div><b>Không mua đuổi</b><br><span class="muted">Giá đã xa trigger >3%, chờ retest.</span></div><div><b>No chase</b></div><div><b>Hủy/loại</b><br><span class="muted">RR/risk/RS/Sector/false-break không đạt hoặc VNINDEX Defensive.</span></div><div><b>Cancel</b></div></div>`,
    },
    top: {
      title: "Top 20 hôm nay",
      body: `
        <div class="helpLine"><b>Mục tiêu:</b> bảng quyết định nhanh: mã nào, hành động gì, rủi ro bao nhiêu, timing mua ra sao. Chi tiết kỹ thuật nằm trong nút Chi tiết/Bộ lọc nâng cao.</div>
        <div class="formulaGrid">
          <div><b>Top 20 khác Bộ lọc nâng cao</b><br><span class="muted">Top 20 chỉ lấy 20 mã mạnh nhất theo filter hiện tại; Bộ lọc nâng cao hiển thị toàn bộ danh sách khớp filter/preset để soi sâu.</span></div><div><b>Scope</b></div>
          <div><b>Preset gợi ý</b><br><span class="muted">Dùng các nút Smart Market / Quality focus / Low false break / Volman / Pullback đẹp / Nền mạnh để đổi toàn bộ dashboard.</span></div><div><b>Auto</b></div>
          <div><b>Click dòng</b><br><span class="muted">Tự set Mã/Ngành/Hành động và mở Bộ lọc nâng cao.</span></div><div><b>Drill-down</b></div>
          <div><b>Điểm QĐ ?</b><br><span class="muted">Xem công thức điểm quyết định từ backend rule version.</span></div><div><b>Explain</b></div>
          <div><b>Pullback đẹp ?</b><br><span class="muted">Xem điểm pullback, vùng chờ và giá bật lại.</span></div><div><b>Setup</b></div>
          <div><b>B chi tiết ?</b><br><span class="muted">Xem nền tích lũy: range, gần đỉnh, volume cạn, dòng tiền, phân phối.</span></div><div><b>Nền</b></div>
          <div><b>RS/Sector</b><br><span class="muted">Mọi tab chính đều có RS20, RS Rank, Sector RS để biết mã có mạnh hơn thị trường và được ngành hỗ trợ không.</span></div><div><b>RS</b></div>
          <div><b>Ngày mua gợi ý</b><br><span class="muted">Timing plan thống kê từ backtest 3M rolling: mua sớm/chờ vượt nền/chờ retest theo từng setup.</span></div><div><b>Timing</b></div>
        </div>`,
    },
    screener: {
      title: "Bộ lọc nâng cao",
      body: `
        <div class="helpLine"><b>Mục tiêu:</b> xem toàn bộ kết quả theo filter đang chọn: ngày, mã, ngành, hành động, breakout, điểm, R/R, rủi ro, thanh khoản.</div>
        <div class="formulaGrid">
          <div><b>Khác Top 20</b><br><span class="muted">Tab này không giới hạn 20 mã; dùng để xem đầy đủ kết quả khớp filter/preset và kiểm tra điều kiện từng setup.</span></div><div><b>Full list</b></div>
          <div><b>Click dòng</b><br><span class="muted">Áp context của dòng đó rồi chuyển sang tab Biểu đồ.</span></div><div><b>Chart link</b></div>
          <div><b>% đổi</b><br><span class="muted">Tính theo khoảng ngày đang filter.</span></div><div><b>Trend</b></div>
          <div><b>Giá vượt đề xuất</b><br><span class="muted">Mốc chờ xác nhận theo setup hiện tại.</span></div><div><b>Trigger</b></div>
          <div><b>Vùng chờ PB</b><br><span class="muted">Vùng canh pullback đẹp + mốc bật lại.</span></div><div><b>Pullback</b></div>
          <div><b>Cảnh báo timing</b><br><span class="muted">Tránh mua đuổi khi xa trigger, breakout spike ngắn hoặc pullback chưa bật rõ.</span></div><div><b>Risk</b></div>
        </div>`,
    },
    ichimoku: {
      title: "Ichimoku — 1H T65/K129 Breakout v1.3 | 1D T65/K129 Breakout v1.0",
      body: `<div class="helpLine"><b>Mục tiêu:</b> lọc riêng Top mã theo Ichimoku T65/K129 Breakout, không trộn vào rule ABCDE chính. Có sẵn 2 khung: 1H (v1.3) và 1D (v1.0).</div><div class="formulaGrid"><div><b>Rule chung</b><br><span class="muted">Top 100 Volume D1; khung chính Tenkan65≈Kijun129; giá sát dưới hoặc vừa vượt cụm T65/K129.</span></div><div><b>1H / D1</b></div><div><b>Context</b><br><span class="muted">Khung còn lại (15m, 1H, 1D tuỳ khung chính) chỉ dùng để hiển thị/timing context, không phải điều kiện MTF bắt buộc.</span></div><div><b>Guardrail</b></div><div><b>1D v1.0 lưu ý</b><br><span class="muted">Entry thực tế nên chờ xác nhận 1H/15m breakout. D1 target gần +8%, target rộng +20%.</span></div><div><b>Risk</b></div></div>`,
    },
    charts: {
      title: "Biểu đồ & v2.1 Top RS",
      body: `
        <div class="helpLine"><b>Mục tiêu:</b> nhìn tổng quan theo ngày, nhãn vùng mua, setup, sức mạnh ngành và Top RS theo đúng filter hiện tại.</div>
        <div class="formulaGrid">
          <div><b>Click biểu đồ Nhãn/Setup/Ngành</b><br><span class="muted">Tự set chartFilter và reload toàn bộ dashboard.</span></div><div><b>Filter</b></div>
          <div><b>v2.1 Sức mạnh ngành</b><br><span class="muted">Đã dùng filter thực tế từ BASE_CTE/ranked.</span></div><div><b>Sector</b></div>
          <div><b>v2.1 Top RS</b><br><span class="muted">Mặc định mỗi mã chỉ 1 dòng mới nhất. Bật “Hiện lịch sử nhiều ngày” nếu muốn xem các snapshot cũ.</span></div><div><b>Unique</b></div>
          <div><b>Click dòng Top RS</b><br><span class="muted">Liên kết ngược sang Bộ lọc nâng cao.</span></div><div><b>Drill-down</b></div>
        </div>`,
    },
  };
  const item = content[tab] || content.top;
  document.getElementById("scoreModalContent").innerHTML =
    `<h2>${item.title}</h2>${item.body}`;
  document.getElementById("scoreModal").style.display = "flex";
}

async function loadHealthBanner() {
  let el = document.getElementById("healthBanner");
  if (!el) return;
  try {
    let h = await j("/api/health");
    let f = h.freshness || {};
    let cls = f.ready ? "good" : "warn";
    el.className = "healthBanner " + cls;
    el.innerHTML = `<b>System:</b> v${esc(h.dashboard_version || "")} · ${esc(h.codename || "")} &nbsp; | &nbsp; <b>Cache:</b> ${f.ready ? "fresh" : "stale"} · ${esc(f.latest_cache_signal_date || "—")}/${esc(f.latest_signal_date || "—")} · rows ${esc(f.cache_rows ?? "—")}/${esc(f.total_signals ?? "—")} · built ${esc(f.cache_created_at || "—")}`;
  } catch (e) {
    el.className = "healthBanner bad";
    el.innerHTML = `<b>System:</b> không đọc được health/cache status · ${esc(e.message || e)}`;
  }
}



async function loadMarketPanel() {
  let el = document.getElementById("marketPanel");
  if (!el) return;
  try {
    let m = await j("/api/market/regime");
    let b = m.breadth || {};
    el.innerHTML = `
      <div class="panelHead">
        <div>
          <h3>Trạng thái thị trường <span class="muted">— Market Regime</span></h3>
          <p class="muted">Dùng để quyết định hôm nay nên aggressive hay chỉ watchlist/chờ xác nhận.</p>
        </div>
        <div class="pill ${m.regime === "Bullish" ? "good" : m.regime === "Neutral" ? "warn" : "bad"}">${esc(m.regime || "—")}</div>
      </div>
      <div class="grid backtestKpis">
        <div><div class="muted">Market score</div><div class="kpiSmall">${num(m.market_score,0)}</div></div>
        <div><div class="muted">VNINDEX</div><div class="kpiSmall">${num(m.vnindex_close,2)}</div></div>
        <div><div class="muted">VNINDEX 5D</div><div class="kpiSmall ${Number(m.return_5d_pct || 0) >= 0 ? "txtGood" : "txtBad"}">${pct(m.return_5d_pct)}</div></div>
        <div><div class="muted">VNINDEX 20D</div><div class="kpiSmall ${Number(m.return_20d_pct || 0) >= 0 ? "txtGood" : "txtBad"}">${pct(m.return_20d_pct)}</div></div>
        <div><div class="muted">RS mạnh</div><div class="kpiSmall">${pct(b.rs_strong_pct)}</div></div>
        <div><div class="muted">Ngành hỗ trợ</div><div class="kpiSmall">${pct(b.sector_supported_pct)}</div></div>
        <div><div class="muted">Quality cao</div><div class="kpiSmall">${pct(b.quality_high_pct)}</div></div>
        <div><div class="muted">False-break thấp</div><div class="kpiSmall">${pct(b.low_false_break_pct)}</div></div>
      </div>
      <div class="helpLine"><b>Chiến lược:</b> ${esc(m.strategy || "—")}</div>`;
  } catch (e) {
    el.innerHTML = `<h3>Trạng thái thị trường</h3><p class="muted">Chưa đọc được regime: ${esc(e.message || e)}</p>`;
  }
}

function currentBacktestDate() {
  return document.getElementById("end")?.value || document.getElementById("start")?.value || "";
}

function renderDailyBacktestResult(st) {
  let el = document.getElementById("dailyBacktestResult");
  if (!el) return;
  let res = st.result || {};
  let sm = res.summary || {};
  if (st.status === "running") {
    el.innerHTML = `<div class="helpLine"><b>Đang chạy:</b> ${esc(st.message || "")}<br><span class="muted">${esc(st.out || "")}</span></div>`;
    return;
  }
  if (st.status === "failed") {
    el.innerHTML = `<div class="helpLine txtBad"><b>Backtest lỗi:</b> ${esc(st.message || "")}<br><pre>${esc(st.log_tail || "")}</pre></div>`;
    return;
  }
  if (!sm || !Object.keys(sm).length) {
    el.innerHTML = `<div class="helpLine muted">Chưa có kết quả backtest ngày cho preset đang chọn.</div>`;
    return;
  }
  el.innerHTML = `
    <div class="helpLine">
      <b>Kết quả backtest ngày ${esc(sm.date || st.date || "—")}</b> — ${esc(sm.preset_label || presetLabel(st.preset || ""))}<br>
      <span class="muted">File: ${esc(st.out || "")}</span>
    </div>
    <div class="grid backtestKpis">
      <div><div class="muted">Signals</div><div class="kpiSmall">${num(sm.signals,0)}</div></div>
      <div><div class="muted">Matured T+20</div><div class="kpiSmall">${num(sm.matured_t20,0)}</div></div>
      <div><div class="muted">T+3 TB</div><div class="kpiSmall ${Number(sm.avg_return_3d_pct || 0) >= 0 ? "txtGood" : "txtBad"}">${pct(sm.avg_return_3d_pct)}</div></div>
      <div><div class="muted">T+5 TB</div><div class="kpiSmall ${Number(sm.avg_return_5d_pct || 0) >= 0 ? "txtGood" : "txtBad"}">${pct(sm.avg_return_5d_pct)}</div></div>
      <div><div class="muted">T+10 TB</div><div class="kpiSmall ${Number(sm.avg_return_10d_pct || 0) >= 0 ? "txtGood" : "txtBad"}">${pct(sm.avg_return_10d_pct)}</div></div>
      <div><div class="muted">T+20 TB</div><div class="kpiSmall ${Number(sm.avg_return_20d_pct || 0) >= 0 ? "txtGood" : "txtBad"}">${pct(sm.avg_return_20d_pct)}</div></div>
      <div><div class="muted">Win T+20</div><div class="kpiSmall">${pct(sm.win_rate_20d_pct)}</div></div>
      <div><div class="muted">Hit stop T+20</div><div class="kpiSmall txtBad">${pct(sm.hit_stop_20d_pct)}</div></div>
    </div>`;
}

async function pollDailyBacktest() {
  let st = await j("/api/backtest/daily_status");
  renderDailyBacktestResult(st);
  let btn = document.getElementById("dailyBacktestBtn");
  if (btn) {
    btn.disabled = st.status === "running";
    btn.innerHTML = st.status === "running" ? '<span class="spinner"></span>Đang backtest...' : "Chạy backtest ngày";
  }
  if (st.status === "running") setTimeout(pollDailyBacktest, 2500);
}

async function runDailyBacktest() {
  let date = currentBacktestDate();
  if (!date) {
    showModal("Thiếu ngày backtest", "Chọn Từ ngày hoặc Đến ngày trước khi chạy backtest ngày.", "");
    return;
  }
  let preset = document.getElementById("presetFilter")?.value || "";
  let btn = document.getElementById("dailyBacktestBtn");
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Đang backtest...'; }
  let q = new URLSearchParams({ date, preset });
  let st = await j("/api/backtest/daily_run?" + q.toString());
  renderDailyBacktestResult(st);
  setTimeout(pollDailyBacktest, 1500);
}

async function loadBacktestPanel() {
  let el = document.getElementById("backtestPanel");
  if (!el) return;
  try {
    let data = await j("/api/backtest/quality_preset_performance");
    let current = document.getElementById("presetFilter")?.value || "";
    let rows = data.rows || [];
    let activeName = presetLabel(current);
    let active = rows.find((x) => x.preset === activeName) || (current ? { preset: activeName, description: "Preset này đang được áp dụng ở bảng lọc nhưng chưa có thống kê backtest riêng." } : rows[0] || {});
    let orderedNames = Object.values(PRESET_LABELS);
    let topRows = [...rows]
      .sort((a, b) => {
        let ia = orderedNames.indexOf(a.preset);
        let ib = orderedNames.indexOf(b.preset);
        if (ia === -1) ia = 999;
        if (ib === -1) ib = 999;
        return ia - ib;
      })
      .map(
        (r) => `<tr class="${r.preset === active.preset ? "activePresetRow" : ""}"><td><b>${esc(r.preset)}</b><br><span class="muted">${esc(r.description || "")}</span></td><td>${num(r.signals,0)}</td><td>${pct(r.avg_return_t3_pct)}</td><td>${pct(r.avg_return_t5_pct)}</td><td>${pct(r.avg_return_t10_pct)}</td><td>${pct(r.avg_return_t20_pct)}</td><td>${pct(r.win_rate_t20_pct)}</td><td>${pct(r.avg_max_drawdown_20d_pct)}</td><td>${pct(r.hit_stoploss_pct)}</td></tr>`,
      )
      .join("");
    el.innerHTML = `
      <div class="panelHead">
        <div>
          <h3>Hiệu quả backtest preset <span class="muted">— ${esc(data.universe || "")}, đến ${esc(data.backtest_end || "")}</span></h3>
          <p class="muted">Dùng để tránh lọc theo cảm tính. Backtest là thống kê lịch sử, không phải khuyến nghị chắc chắn.</p>
        </div>
        <div class="panelActions"><button id="dailyBacktestBtn" class="load" onclick="runDailyBacktest()">Chạy backtest ngày</button><a class="driveBtn" href="https://docs.google.com/spreadsheets/d/14pgVL7P4wKr-Egnr6OW8LoQBDYqxSYEl/edit?usp=drivesdk&ouid=114966300799929664143&rtpof=true&sd=true" target="_blank" rel="noopener">Mở file Drive</a></div>
      </div>
      <div class="grid backtestKpis">
        <div><div class="muted">Preset đang chọn</div><div class="kpiSmall">${esc(active.preset || "—")}</div></div>
        <div><div class="muted">Signals</div><div class="kpiSmall">${num(active.signals,0)}</div></div>
        <div><div class="muted">T+3 TB</div><div class="kpiSmall ${Number(active.avg_return_t3_pct || 0) >= 0 ? "txtGood" : "txtBad"}">${pct(active.avg_return_t3_pct)}</div></div>
        <div><div class="muted">T+5 TB</div><div class="kpiSmall ${Number(active.avg_return_t5_pct || 0) >= 0 ? "txtGood" : "txtBad"}">${pct(active.avg_return_t5_pct)}</div></div>
        <div><div class="muted">T+10 TB</div><div class="kpiSmall ${Number(active.avg_return_t10_pct || 0) >= 0 ? "txtGood" : "txtBad"}">${pct(active.avg_return_t10_pct)}</div></div>
        <div><div class="muted">T+20 TB</div><div class="kpiSmall ${Number(active.avg_return_t20_pct || 0) >= 0 ? "txtGood" : "txtBad"}">${pct(active.avg_return_t20_pct)}</div></div>
        <div><div class="muted">Win rate</div><div class="kpiSmall">${pct(active.win_rate_t20_pct)}</div></div>
        <div><div class="muted">Drawdown TB</div><div class="kpiSmall txtBad">${pct(active.avg_max_drawdown_20d_pct)}</div></div>
      </div>
      <div id="dailyBacktestResult" class="dailyBacktestResult helpLine muted">Chọn ngày + preset rồi bấm “Chạy backtest ngày” để kiểm tra riêng bộ lọc hiện tại.</div>
      <div style="max-height:260px;overflow:auto">
        <table class="miniTable"><thead><tr><th>Preset</th><th>Signals</th><th>T+3</th><th>T+5</th><th>T+10</th><th>T+20</th><th>Win rate</th><th>DD TB</th><th>Hit SL</th></tr></thead><tbody>${topRows}</tbody></table>
      </div>`;
    pollDailyBacktest().catch(() => {});
  } catch (e) {
    el.innerHTML = `<h3>Hiệu quả backtest preset</h3><p class="muted">Chưa đọc được dữ liệu backtest: ${esc(e.message || e)}</p>`;
  }
}




function renderFixedFilterBacktest(data){
  const meta=document.getElementById("fixedBacktestMeta");
  const sum=document.getElementById("fixedBacktestSummary");
  const tbl=document.getElementById("fixedBacktestTable");
  const ov=data.overview||{}; const rows=data.probability_table||[];
  if(meta) meta.innerHTML=`${esc(ov.preset_label||ov.preset||"")} · ${esc(ov.start||"")} → ${esc(ov.end||"")} · ${num(ov.signals,0)} tín hiệu` + (data.xlsx?` · <span class="muted">Excel: ${esc(data.xlsx)}</span>`:"");
  const t20=rows.find(r=>r["Mốc kiểm tra"]==="T+20")||{};
  if(sum) sum.innerHTML=`<b>T+20 TP +4%:</b> ${pct(t20["Xác suất đạt TP +4%"])} · <b>SL -10%:</b> ${pct(t20["Xác suất chạm SL -10%"])} · <b>Return TB:</b> ${pct(t20["Return TB đến mốc"])} · <b>Đóng cửa dương:</b> ${pct(t20["Xác suất đóng cửa dương"])}`;
  const h=["Mốc kiểm tra","Số tín hiệu đủ dữ liệu","Xác suất đạt TP +4%","Xác suất chạm SL -10%","Không chạm TP/SL","Return TB đến mốc","Return median","Xác suất đóng cửa dương","Max tăng TB","Max giảm TB"];
  const body=rows.map(r=>`<tr><td><b>${esc(r["Mốc kiểm tra"])}</b></td><td>${num(r["Số tín hiệu đủ dữ liệu"],0)}</td><td class="good"><b>${pct(r["Xác suất đạt TP +4%"])}</b></td><td class="bad">${pct(r["Xác suất chạm SL -10%"])}</td><td>${pct(r["Không chạm TP/SL"])}</td><td>${pct(r["Return TB đến mốc"])}</td><td>${pct(r["Return median"])}</td><td>${pct(r["Xác suất đóng cửa dương"])}</td><td>${pct(r["Max tăng TB"])}</td><td>${pct(r["Max giảm TB"])}</td></tr>`).join("");
  if(tbl) tbl.innerHTML="<thead><tr>"+h.map(x=>`<th>${esc(x)}</th>`).join("")+"</tr></thead><tbody>"+body+"</tbody>";
}
async function runFixedFilterBacktest(){
  const btn=document.getElementById("fixedBacktestBtn");
  const preset=document.getElementById("fixedBacktestPreset")?.value||"backtest_edge";
  const start=document.getElementById("fixedBacktestStart")?.value||"2024-01-01";
  const end=document.getElementById("fixedBacktestEnd")?.value||"";
  try{
    if(btn){btn.disabled=true; btn.innerHTML='<span class="spinner"></span>Đang backtest...';}
    const q=new URLSearchParams({preset,start}); if(end) q.set("end",end);
    const data=await j("/api/backtest/fixed_filter?"+q.toString());
    renderFixedFilterBacktest(data);
  }catch(e){ showModal("❌ Backtest bộ lọc lỗi", String(e), ""); }
  finally{ if(btn){btn.disabled=false; btn.innerHTML='Backtest bộ lọc';} }
}

async function loadRegimeBacktestPanel() {
  let el = document.getElementById("regimeBacktestPanel");
  if (!el) return;
  try {
    let [data, market] = await Promise.all([j("/api/backtest/regime_preset_performance"), j("/api/market/regime")]);
    let regime = market.regime || "Neutral";
    let rows = (data.rows || []).filter((r) => r.regime === regime && Number(r.signals || 0) > 0);
    rows.sort((a,b) => Number(b.avg_return_t10_pct || -999) - Number(a.avg_return_t10_pct || -999));
    let rec = (data.recommendations || []).find((x) => x.regime === regime) || {};
    let body = rows.slice(0,10).map((r) => `<tr><td><b>${esc(r.preset)}</b></td><td>${num(r.signals,0)}</td><td>${pct(r.avg_return_t3_pct)}</td><td>${pct(r.avg_return_t5_pct)}</td><td>${pct(r.avg_return_t10_pct)}</td><td>${pct(r.avg_return_t20_pct)}</td><td>${pct(r.win_rate_t20_pct)}</td><td>${pct(r.avg_max_drawdown_20d_pct)}</td><td>${pct(r.hit_stoploss_pct)}</td></tr>`).join("");
    el.innerHTML = `
      <div class="panelHead">
        <div>
          <h3>Preset phù hợp market hiện tại <span class="muted">— ${esc(regime)}</span></h3>
          <p class="muted">Backtest theo regime VNINDEX giúp chọn preset đúng bối cảnh thay vì lọc cảm tính.</p>
        </div>
        <div class="muted">File: regime_preset_performance_2026-05-21.json · regime từ VNINDEX</div>
      </div>
      <div class="helpLine"><b>Ưu tiên:</b> ${(rec.recommended_presets || []).map(esc).join(" → ") || "—"}<br><b>Hạn chế:</b> ${(rec.avoid_presets || []).map(esc).join(" / ") || "—"}</div>
      <div style="max-height:260px;overflow:auto">
        <table class="miniTable"><thead><tr><th>Preset</th><th>Signals</th><th>T+3</th><th>T+5</th><th>T+10</th><th>T+20</th><th>Win</th><th>DD</th><th>Hit SL</th></tr></thead><tbody>${body}</tbody></table>
      </div>`;
  } catch(e) {
    el.innerHTML = `<h3>Preset phù hợp market hiện tại</h3><p class="muted">Chưa đọc được regime backtest: ${esc(e.message || e)}</p>`;
  }
}

async function loadTimingPanel() {
  let el = document.getElementById("timingPanel");
  if (!el) return;
  try {
    let data = await j("/api/backtest/entry_timing");
    let rows = data.by_setup || [];
    let summary = data.summary || {};
    let body = rows.map((r) => `<tr><td><b>${esc(r.best_setup_abcd || "—")}</b></td><td>${num(r.signals,0)}</td><td>${pct(r.hit_high_2pct_rate)}</td><td>D+${num(r.median_days_to_high_2pct,0)}</td><td>D+${num(r.median_best_gain_day,0)}</td><td>${pct(r.stop_before_2pct_rate)}</td><td>${setupTimingAdvice(r.best_setup_abcd)}</td></tr>`).join("");
    el.innerHTML = `
      <div class="panelHead">
        <div>
          <h3>Timing mua sau khi lọc <span class="muted">— đo từ Top 20 rolling 3M</span></h3>
          <p class="muted">Thống kê ngày mã bắt đầu bật sau khi xuất hiện trong danh sách. Dùng để gợi ý timing, không phải ngày mua chắc chắn.</p>
        </div>
        <div class="muted">File: entry_timing_recent_top20_3m.xlsx</div>
      </div>
      <div class="grid backtestKpis">
        <div><div class="muted">Signals đo timing</div><div class="kpiSmall">${num(summary.signals,0)}</div></div>
        <div><div class="muted">Chạm +2%</div><div class="kpiSmall">${pct(summary.hit_high_2pct_rate)}</div></div>
        <div><div class="muted">Median +2%</div><div class="kpiSmall">D+${num(summary.median_days_to_high_2pct,0)}</div></div>
        <div><div class="muted">Median best gain</div><div class="kpiSmall">D+${num(summary.median_best_gain_day,0)}</div></div>
        <div><div class="muted">Stop trước +2%</div><div class="kpiSmall txtBad">${pct(summary.stop_before_2pct_rate)}</div></div>
      </div>
      <div style="max-height:260px;overflow:auto">
        <table class="miniTable"><thead><tr><th>Setup</th><th>Signals</th><th>Hit +2%</th><th>Median +2%</th><th>Best gain</th><th>Stop trước +2%</th><th>Gợi ý timing</th></tr></thead><tbody>${body}</tbody></table>
      </div>`;
  } catch (e) {
    el.innerHTML = `<h3>Timing mua sau khi lọc</h3><p class="muted">Chưa đọc được dữ liệu timing: ${esc(e.message || e)}</p>`;
  }
}

function setupTimingAdvice(setup) {
  let s = setup || "";
  if (s.includes("Dòng tiền")) return "Ưu tiên D/D+1 nếu không xa trigger; mua thăm dò + stop chặt";
  if (s.includes("Tích")) return "Chờ D+2–D+4 hoặc đóng cửa vượt nền/high20";
  if (s.includes("Breakout")) return "Không mua đuổi; chờ retest, chốt nhanh nếu spike";
  if (s.includes("Pullback")) return "Chờ vượt đỉnh hồi phục 3–5 phiên, không bắt dao rơi";
  return "Chờ xác nhận";
}


function getIchimokuTf() {
  const sel = document.getElementById("ichimokuTfSelect");
  return sel ? sel.value : "1H";
}
function onIchimokuTfChange() {
  loadIchimoku();
}
function renderIchimoku(data) {
  const rows = data.rows || [];
  const tf = getIchimokuTf();
  const ver = tf === "1D" ? "v1.0" : "v1.3";
  const dateSel = document.getElementById("ichimokuDateSelect");
  if (dateSel && Array.isArray(data.dates)) {
    const cur = dateSel.value || data.date || "";
    dateSel.innerHTML = '<option value="">Mới nhất</option>' + data.dates.map(d => `<option value="${esc(d.scan_date)}">${esc(d.scan_date)} (${num(d.total,0)})</option>`).join("");
    dateSel.value = cur;
  }
  const meta = document.getElementById("ichimokuMeta");
  if (meta) {
    if (data.message && !data.date) {
      meta.textContent = data.message;
    } else if (data.rows && data.rows.length === 0 && data.date) {
      const hint = data.message ? ' ' + data.message : '';
      meta.textContent = ` SQLite · ngày ${data.date} · ${tf} — không có mã đạt điều kiện lọc. Thử chuyển khung ${tf === '1D' ? '1H' : '1D'} hoặc chọn ngày khác.${hint}`;
    } else {
      meta.textContent = data.source === "sqlite" ? ` SQLite · ngày ${data.date || "—"} · ${tf} scan` : (data.file ? ` File: ${data.file} · cập nhật ${data.updated_at || "—"}` : (data.message || ""));
    }
  }
  const sm = data.summary || [];
  const sumEl = document.getElementById("ichimokuSummary");
  if (sumEl) sumEl.innerHTML = sm.length ? sm.map(x => `<b>${esc(x["Trạng thái hành động"] || "—")}:</b> ${num(x["Số_mã"],0)} mã · điểm TB ${num(x["Điểm_TB"],1)}`).join("<br>") : (data.date ? "Không có mã đạt điều kiện trên khung này." : "Chưa có tóm tắt.");
  DASH_ROWS.ichimokuTable = rows;
  const hasRows = rows && rows.length > 0;
  if (!hasRows) {
    const tbl = document.getElementById("ichimokuTable");
    if (tbl) tbl.innerHTML = '<thead><tr><th>Thông báo</th></tr></thead><tbody><tr><td style="text-align:center;padding:2em;color:var(--muted)">' + (data.message && !data.date ? esc(data.message) : (data.date ? 'Khung ' + tf + ' ngày ' + data.date + ': không có mã đạt điều kiện lọc.' : 'Chưa có dữ liệu. Bấm Quét Ichimoku để tạo.')) + '</td></tr></tbody>';
    return;
  }
  const h = ["Rank","Mã","Timing","Timing score","1D setup","15M timing","Khung đạt","Điểm","Trạng thái","Giá mới nhất / lúc lọc","Vùng mua","Trigger","Stoploss","Rủi ro %","Mục tiêu gần","R/R","Volume","Xác nhận","Hủy","Lý do"];
  const body = rows.map((r,i)=>{
    const action = r["Trạng thái hành động"] || "";
    const cls = action.includes("Theo dõi sát") || action.includes("Canh mua") ? "good" : action.includes("thiếu") ? "warn" : "bad";
    const rankScore = r["Điểm xếp hạng"] ?? r["Điểm xếp hạng v1.3"] ?? r["Điểm xếp hạng v1.1"];
    const ichiScore = r["Điểm Ichimoku 1H v1.3"] ?? r["Điểm Ichimoku"] ?? r["Điểm Ichimoku MTF"];
  return `<tr class="${cls}"><td>${i+1}</td><td><b>${esc(r["Mã"]||"")}</b></td><td>${badge(r["Timing label"] || action)}</td><td><b>${num(r["Timing score"],1)}</b></td><td>${num(r["D1 setup score"],0)}</td><td>${num(r["15M timing score"],0)}</td><td>${esc(r["Khung đạt"]||"")}</td><td><b>${num(rankScore,1)}</b><br><span class="muted">${tf} ${num(ichiScore,1)}</span></td><td>${badge(action)}</td><td>${priceAudit(r)}</td><td>${price(r["Vùng mua thấp"])} - ${price(r["Vùng mua cao/trigger"])}</td><td>${price(r["Giá trigger"])}</td><td>${price(r["Stoploss"])}</td><td>${pct(r["Rủi ro %"])}</td><td>${price(r["Mục tiêu gần"])}</td><td>${num(r["Lãi/Rủi ro mục tiêu gần"],2)}</td><td>${esc(r["Volume xác nhận"]||"")}</td><td>${esc(r["Điều kiện xác nhận"]||"")}</td><td>${esc(r["Điều kiện huỷ"]||"")}</td><td>${esc(r["Lý do"]||"")}</td></tr>`;
  }).join("");
  document.getElementById("ichimokuTable").innerHTML = "<thead><tr>" + h.map(x=>`<th>${thHelp(x)}</th>`).join("") + "</tr></thead><tbody>" + body + "</tbody>";
}
async function loadIchimoku() {
  const sel = document.getElementById("ichimokuDateSelect");
  const tf = getIchimokuTf();
  const params = ["tf=" + encodeURIComponent(tf)];
  if (sel && sel.value) params.push("date=" + encodeURIComponent(sel.value));
  const data = await j("/api/ichimoku/top20?" + params.join("&"));
  // If no date was selected and the API returned a date different from selector, update selector
  if (sel && (!sel.value || !data.rows || data.rows.length === 0)) {
    // Preselect latest date that has rows for this tf
    if (Array.isArray(data.dates) && data.dates.length > 0) {
      // Pick the most recent date with data
      const pick = data.dates.sort((a,b) => b.scan_date.localeCompare(a.scan_date)).find(d => d.total > 0);
      if (pick) { sel.value = pick.scan_date; }
    }
    // Reload with chosen date
    if (sel && sel.value) {
      const data2 = await j("/api/ichimoku/top20?tf=" + encodeURIComponent(tf) + "&date=" + encodeURIComponent(sel.value));
      renderIchimoku(data2);
      return;
    }
  }
  renderIchimoku(data);
}
function setIchimokuBtn(running) {
  let btn=document.getElementById("ichimokuScanBtn"); if(!btn) return;
  btn.disabled=running; btn.innerHTML=running ? '<span class="spinner"></span>Đang quét Ichimoku...' : 'Quét Ichimoku hôm nay';
}
let ichimokuPoll=null;
async function pollIchimoku(){
  let s=await j("/api/ichimoku/status"); setIchimokuBtn(s.status==="running");
  if(s.status==="running") { showModal("⏳ Đang quét Ichimoku", s.message||"Đang chạy...", s.log_tail||""); ichimokuPoll=setTimeout(pollIchimoku,3500); }
  else { if(ichimokuPoll){clearTimeout(ichimokuPoll); ichimokuPoll=null;} setIchimokuBtn(false); await loadIchimoku(); showModal(s.status==="success"?"✅ Quét Ichimoku xong":s.status==="failed"?"❌ Quét Ichimoku lỗi":"Trạng thái Ichimoku", s.message||"", s.log_tail||""); }
}
async function scanIchimoku(){
  const tf = getIchimokuTf();
  const verName = tf === "1D" ? "D1 T65/K129 Breakout v1.0" : "1H T65/K129 Breakout v1.3";
  try{ setIchimokuBtn(true); showModal("⏳ Đang quét " + verName, "Đang quét 100 mã khung " + tf + ". Do giới hạn vnstock, có thể mất vài phút...", ""); let r=await j("/api/ichimoku/scan?tf=" + encodeURIComponent(tf)); showModal("⏳ Đang quét " + verName, r.message||"Đang chạy...", r.log_tail||""); pollIchimoku(); }
  catch(e){ setIchimokuBtn(false); showModal("❌ Không chạy được Ichimoku", String(e), ""); }
}

function renderIchimokuBacktest(data){
  const meta=document.getElementById("ichimokuBacktestMeta");
  const sum=document.getElementById("ichimokuBacktestSummary");
  const tbl=document.getElementById("ichimokuBacktestTable");
  const ov=data.overview||{}; const rows=data.probability_table||[];
  if(meta) meta.innerHTML=`${esc(ov.ticker||"")} · ${esc(ov.start||"")} → ${esc(ov.end||"")} · ${num(ov.signals,0)} tín hiệu` + (data.xlsx?` · <a href="file://${esc(data.xlsx)}" target="_blank">Excel</a>`:"");
  if(sum) sum.innerHTML=`<b>TP4 T+20:</b> ${num(ov["TP4 trong T+20"],0)} · <b>SL10 T+20:</b> ${num(ov["SL10 trong T+20"],0)} · <b>Return exit TB:</b> ${pct(ov["Return exit TB %"])} · <b>Win rate exit:</b> ${pct(ov["Win rate exit %"])}`;
  const h=["Mốc kiểm tra","Số tín hiệu đủ dữ liệu","Xác suất đạt TP +4%","Xác suất chạm SL -10%","Không chạm TP/SL","Return TB đến mốc","Return median","Xác suất đóng cửa dương","Max tăng TB","Max giảm TB"];
  const body=rows.map(r=>`<tr><td><b>${esc(r["Mốc kiểm tra"])}</b></td><td>${num(r["Số tín hiệu đủ dữ liệu"],0)}</td><td class="good"><b>${pct(r["Xác suất đạt TP +4%"])}</b></td><td class="bad">${pct(r["Xác suất chạm SL -10%"])}</td><td>${pct(r["Không chạm TP/SL"])}</td><td>${pct(r["Return TB đến mốc"])}</td><td>${pct(r["Return median"])}</td><td>${pct(r["Xác suất đóng cửa dương"])}</td><td>${pct(r["Max tăng TB"])}</td><td>${pct(r["Max giảm TB"])}</td></tr>`).join("");
  if(tbl) tbl.innerHTML="<thead><tr>"+h.map(x=>`<th>${esc(x)}</th>`).join("")+"</tr></thead><tbody>"+body+"</tbody>";
}
async function runIchimokuBacktest(){
  const btn=document.getElementById("ichimokuBacktestBtn");
  const ticker=(document.getElementById("ichimokuBacktestTicker")?.value||"").trim().toUpperCase();
  const start=document.getElementById("ichimokuBacktestStart")?.value||"2024-01-01";
  if(!ticker){ showModal("Thiếu mã", "Nhập mã cổ phiếu cần backtest.", ""); return; }
  try{
    if(btn){btn.disabled=true; btn.innerHTML='<span class="spinner"></span>Đang backtest...';}
    const data=await j(`/api/ichimoku/backtest?ticker=${encodeURIComponent(ticker)}&start=${encodeURIComponent(start)}`);
    renderIchimokuBacktest(data);
  }catch(e){ showModal("❌ Backtest lỗi", String(e), ""); }
  finally{ if(btn){btn.disabled=false; btn.innerHTML='Backtest';} }
}

async function runMa20EmaTickerBacktest(){
  const btn=document.getElementById('ma20BacktestBtn');
  const ticker=(document.getElementById('ma20BacktestTicker')?.value||'').trim().toUpperCase();
  const start=document.getElementById('ma20BacktestStart')?.value||'2024-01-01';
  if(!ticker){ showModal('Thiếu mã', 'Nhập mã cổ phiếu cần backtest.', ''); return; }
  try{
    if(btn){btn.disabled=true; btn.innerHTML='<span class="spinner"></span>Đang backtest...';}
    const data=await j(`/api/ma20-ema/backtest_ticker?ticker=${encodeURIComponent(ticker)}&start=${encodeURIComponent(start)}`);
    renderMa20EmaTickerBacktest(data);
  }catch(e){ showModal('❌ Backtest lỗi', String(e), ''); }
  finally{ if(btn){btn.disabled=false; btn.innerHTML='Backtest';} }
}

function renderMa20EmaTickerBacktest(data){
  const ov=data.overview||{};
  const meta=document.getElementById('ma20BacktestMeta');
  if(meta) meta.textContent=`${esc(ov.ticker)} · ${ov.signals||0} tín hiệu · ${ov.data_min} → ${ov.data_max}`;
  const sum=document.getElementById('ma20BacktestSummTicker');
  if(sum) sum.innerHTML=`<b>TP4 T+20:</b> ${num(ov['TP4 trong T+20'],0)} · <b>SL3 T+20:</b> ${num(ov['SL3 trong T+20'],0)} · <b>Return exit TB:</b> ${pct(ov['Return exit TB %'])} · <b>Win rate exit:</b> ${pct(ov['Win rate exit %'])} · <b>Win rate net:</b> ${pct(ov['Win rate net %'])}`;
  const h=['Mốc','Số tín hiệu','TP4 %','SL3 %','NoHit %','Return TB %','Return median %','Dương %','Max tăng TB %','Max giảm TB %'];
  const rows=(data.summary||[]).map(r=>`<tr><td><b>${esc(r['Mốc'])}</b></td><td>${num(r['Số tín hiệu'],0)}</td><td class="good"><b>${pct(r['TP4 %'])}</b></td><td class="bad">${pct(r['SL3 %'])}</td><td>${pct(r['NoHit %'])}</td><td>${pct(r['Return TB %'])}</td><td>${pct(r['Return median %'])}</td><td>${pct(r['Dương %'])}</td><td>${pct(r['Max tăng TB %'])}</td><td>${pct(r['Max giảm TB %'])}</td></tr>`).join('');
  const tbl=document.getElementById('ma20BacktestTickerTable');
  if(tbl) tbl.innerHTML='<thead><tr>'+h.map(x=>`<th>${esc(x)}</th>`).join('')+'</tr></thead><tbody>'+rows+'</tbody>';
}

async function loadSibOverview() {
  const p = new URLSearchParams();
  const from=document.getElementById('sibFrom')?.value, to=document.getElementById('sibTo')?.value;
  const bucket=document.getElementById('sibBucket')?.value, regime=document.getElementById('sibRegime')?.value, variant=document.getElementById('sibVariant')?.value;
  if(from)p.set('from',from); if(to)p.set('to',to); if(bucket)p.set('bucket',bucket); if(regime)p.set('regime',regime); if(variant)p.set('variant',variant);
  const data=await j('/api/sib/v3?'+p.toString());
  document.getElementById('sibMeta').textContent=` · ${data.trades.length} kết quả chi tiết`;
  renderSimpleTable('sibReportTable', data.report, ['variant','regime','horizon','samples','win_rate','avg_return_pct','median_return_pct','avg_excess_pct','avg_mfe_pct','avg_mae_pct']);
  renderSimpleTable('sibTradesTable', data.trades, ['snapshot_date','ticker','variant','sib_score','regime','entry_date','entry_price','horizon','exit_date','return_pct','excess_return_pct','mfe_pct','mae_pct']);
  const by={}; for(const r of data.report){const k=r.variant; if(!by[k])by[k]=[]; if(Number(r.horizon)===10)by[k].push(Number(r.avg_return_pct)||0)}
  const labels=Object.keys(by), values=labels.map(k=>by[k].reduce((a,b)=>a+b,0)/(by[k].length||1));
  if(window.Chart && document.getElementById('sibChart')) { if(window.sibChartObj)sibChartObj.destroy(); window.sibChartObj=new Chart(document.getElementById('sibChart'),{type:'bar',data:{labels,datasets:[{label:'Avg return T+10 (%)',data:values,backgroundColor:'#2563eb'}]},options:{responsive:true,scales:{y:{beginAtZero:false}}}}); }
}

async function loadDash() {
  destroy();
  await ensureFilterOptions();
  let q = qs();
  let o = await j("/api/overview" + q);
  let k = document.getElementById("kpis");
  let items = [
    ["Tổng tín hiệu", o.tong_tin_hieu],
    ["Top điểm QĐ", o.top_decision_score],
    ["Điểm QĐ TB", o.decision_score_tb],
    ["Lãi/Rủi ro TB", o.lai_rui_ro_tb],
    ["Rủi ro TB %", o.rui_ro_tb],
    ["Đã breakout", o.da_breakout],
    ["Chờ breakout", o.cho_breakout],
  ];
  k.innerHTML = items
    .map(
      (x) =>
        `<div class="card"><div class="muted">${x[0]}</div><div class="kpi">${fmt(x[1])}</div></div>`,
    )
    .join("");
  await loadMarketPanel();
  await loadBacktestPanel();
  await loadRegimeBacktestPanel();
  await loadTimingPanel();
  await loadActionBoard();
  table("top20", await j("/api/top20" + q), "top");
  table("screener", await j("/api/screener" + q), "screener");
  await loadIchimoku();
  await loadMa20EmaD1();
  await loadSibOverview();
  let daily = await j("/api/daily" + q);
  charts.push(
    new Chart(document.getElementById("dailyChart"), {
      type: "line",
      data: {
        labels: daily.map((x) => x.signal_date),
        datasets: [
          {
            label: "Số tín hiệu",
            data: daily.map((x) => x.total),
            borderColor: "#1f4e78",
            backgroundColor: "#1f4e7833",
            yAxisID: "y",
          },
          {
            label: "Điểm QĐ TB",
            data: daily.map((x) => x.avg_decision),
            borderColor: "#22c55e",
            backgroundColor: "#22c55e33",
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: { beginAtZero: true },
          y1: {
            beginAtZero: true,
            position: "right",
            grid: { drawOnChartArea: false },
          },
        },
      },
    }),
  );
  let label = await j("/api/labels" + q);
  charts.push(
    new Chart(document.getElementById("labelChart"), {
      type: "bar",
      data: {
        labels: label.map((x) => x.buy_zone_label || "N/A"),
        datasets: [
          {
            label: "Số tín hiệu",
            data: label.map((x) => x.total),
            backgroundColor: label.map((x) => labelColor(x.buy_zone_label)),
          },
        ],
      },
      options: {
        onClick: (evt, els) => {
          if (els.length) {
            chartFilter.label = label[els[0].index].buy_zone_label || "";
            chartFilter.setup = "";
            loadDash();
          }
        },
      },
    }),
  );
  let setup = await j("/api/setup" + q);
  charts.push(
    new Chart(document.getElementById("setupChart"), {
      type: "bar",
      data: {
        labels: setup.map((x) => x.setup_type || "N/A"),
        datasets: [
          {
            label: "Số tín hiệu",
            data: setup.map((x) => x.total),
            backgroundColor: [
              "#22c55e",
              "#84cc16",
              "#facc15",
              "#fb923c",
              "#ef4444",
              "#60a5fa",
            ],
          },
        ],
      },
      options: {
        onClick: (evt, els) => {
          if (els.length) {
            chartFilter.setup = setup[els[0].index].setup_type || "";
            chartFilter.label = "";
            loadDash();
          }
        },
      },
    }),
  );
  let sectors = await j("/api/v21/sectors" + q);
  charts.push(
    new Chart(document.getElementById("sectorChart"), {
      type: "bar",
      data: {
        labels: sectors.map((x) => x.sector),
        datasets: [
          {
            label: "SectorScore",
            data: sectors.map((x) => x.sector_score),
            backgroundColor: sectors.map((x) =>
              x.sector_score >= 70
                ? "#22c55e"
                : x.sector_score >= 50
                  ? "#facc15"
                  : "#ef4444",
            ),
          },
        ],
      },
      options: {
        onClick: (evt, els) => {
          if (els.length) {
            chartFilter.sector = sectors[els[0].index].sector || "";
            chartFilter.setup = "";
            chartFilter.label = "";
            loadDash();
          }
        },
      },
    }),
  );
  let rsHistory = document.getElementById("rsHistoryToggle")?.checked;
  let rsQ = q;
  if (rsHistory) rsQ += (rsQ ? "&" : "?") + "rs_history=1";
  let rs = await j("/api/v21/rs" + rsQ);
  DASH_ROWS.rsTable = rs;
  document.getElementById("rsTable").innerHTML =
    "<thead><tr>" +
    [
      "Rank",
      "Mã",
      "Ngành",
      "Giá",
      "% đổi",
      "Điểm v2.1",
      "RS20",
      "RS Rank",
      "Sector",
      "Hành động",
      "Setup",
      "Điểm QĐ",
      "B tích lũy",
      "Pullback đẹp",
      "Giá vượt",
      "Vùng chờ PB",
      "R/R",
      "Rủi ro %",
      "Vol TB5",
      "Lý do",
    ]
      .map((x) => `<th>${thHelp(x)}</th>`)
      .join("") +
    "</tr></thead><tbody>" +
    rs
      .map(
        (r, i) =>
          `<tr class="${rowClass(r)} clickableRow" title="Click để liên kết Top RS sang Bộ lọc nâng cao" onclick="applyRowContext('rsTable',${i},'screener')"><td>${i + 1}</td><td><b>${r.ticker}</b></td><td>${r.sector || ""}</td><td>${price(r.entry_price)}</td>${changeCell(r.change_pct)}<td><b>${num(r.v21_adjusted_score, 0)}</b></td><td>${num(r.rs20, 2)}</td><td>${num(r.rs_rank_pct, 2)}</td><td>${num(r.sector_score, 2)}</td><td>${badge(r.action_label)}</td><td>${r.setup_type || ""}</td><td>${decisionCell(r, "rsTable", i)}</td><td>${bDetail(r, "rsTable", i)}</td><td>${pullbackCell(r, "rsTable", i)}</td><td><b>${price(r.setup_buy_trigger_price)}</b></td><td>${pullbackZone(r)}</td><td>${num(r.reward_risk, 2)}</td><td>${pct(r.risk_pct)}</td><td>${vol(r.avg_volume5_latest)}</td><td>${r.trade_plan || "—"}</td><td>${r.suggested_position || "—"}</td><td>${r.cancel_condition || "—"}</td><td>${r.suggested_buy_timing || "—"}</td><td>${r.timing_probability_note || "—"}</td><td>${r.timing_warning || "—"}</td><td>${r.main_reason || ""}</td></tr>`,
      )
      .join("") +
    "</tbody>";
}

function resetFilter() {
  [
    "start",
    "end",
    "ticker",
    "sectorFilter",
    "actionFilter",
    "breakoutFilter",
    "minScore",
    "minRR",
    "maxRisk",
    "minLiquidity",
    "presetFilter",
    "startSelect",
    "endSelect",
  ].forEach((id) => {
    let e = document.getElementById(id);
    if (e) e.value = "";
  });
  chartFilter = { setup: "", label: "", sector: "" };
  loadDash();
}
function clearChartFilter() {
  chartFilter = { setup: "", label: "", sector: "" };
  loadDash();
}
function showModal(t, b, l = "") {
  document.getElementById("modalTitle").textContent = t;
  document.getElementById("modalBody").textContent = b || "";
  document.getElementById("modalLog").textContent = l || "";
  document.getElementById("modal").style.display = "flex";
}
function hideModal() {
  document.getElementById("modal").style.display = "none";
}
function setLoadBtn(running) {
  let btn = document.getElementById("loadDataBtn");
  if (!btn) return;
  btn.disabled = running;
  btn.innerHTML = running
    ? '<span class="spinner"></span>Đang nạp giá...'
    : "Nạp giá";
}
let loadPoll = null;
async function pollLoadData() {
  let s = await j("/api/load_data_status");
  setLoadBtn(s.status === "running");
  if (s.status === "running") {
    showModal(
      "⏳ Đang nạp data",
      s.message || "Đang chạy...",
      s.log_tail || "",
    );
    loadPoll = setTimeout(pollLoadData, 2500);
  } else {
    if (loadPoll) {
      clearTimeout(loadPoll);
      loadPoll = null;
    }
    setLoadBtn(false);
    await loadDates();
    await loadOptions();
    await loadDash();
    await loadHealthBanner();
    showModal(
      s.status === "success"
        ? "✅ Nạp data xong"
        : s.status === "failed"
          ? "❌ Nạp data lỗi"
          : "Trạng thái nạp data",
      s.message || "",
      s.log_tail || "",
    );
  }
}
async function loadTodayData() {
  try {
    setLoadBtn(true);
    showModal("⏳ Đang nạp giá", "Đang bắt đầu job nạp giá hôm nay...", "");
    let r = await j("/api/load_data");
    showModal("⏳ Đang nạp giá", r.message || "Đang chạy...", r.log_tail || "");
    pollLoadData();
  } catch (e) {
    setLoadBtn(false);
    showModal("❌ Không chạy được Nạp giá", String(e), "");
  }
}
function setScanBtn(running) {
  let btn = document.getElementById("scanBtn");
  if (!btn) return;
  btn.disabled = running;
  btn.innerHTML = running
    ? '<span class="spinner"></span>Đang quét...'
    : "Quét mã mới";
}
let scanPoll = null;
async function pollScan() {
  let s = await j("/api/scan_status");
  setScanBtn(s.status === "running");
  if (s.status === "running") {
    showModal(
      "⏳ Đang quét mã mới",
      s.message || "Đang chạy...",
      s.log_tail || "",
    );
    scanPoll = setTimeout(pollScan, 3500);
  } else {
    if (scanPoll) {
      clearTimeout(scanPoll);
      scanPoll = null;
    }
    setScanBtn(false);
    await loadDates();
    await loadOptions();
    await loadDash();
    await loadHealthBanner();
    showModal(
      s.status === "success"
        ? "✅ Quét mã mới xong"
        : s.status === "failed"
          ? "❌ Quét mã mới lỗi"
          : "Trạng thái quét mã mới",
      s.message || "",
      s.log_tail || "",
    );
  }
}
async function scanNewUniverse() {
  try {
    setScanBtn(true);
    showModal(
      "⏳ Đang quét mã mới",
      "Đang bắt đầu scanner nhiều mã và chỉ lưu Top 20 mã mạnh nhất. Việc này có thể mất vài phút...",
      "",
    );
    let r = await j("/api/scan_new");
    showModal(
      "⏳ Đang quét mã mới",
      r.message || "Đang chạy...",
      r.log_tail || "",
    );
    pollScan();
  } catch (e) {
    setScanBtn(false);
    showModal("❌ Không chạy được Quét mã mới", String(e), "");
  }
}
async function loadDates() {
  let ds = await j("/api/dates");
  let opts =
    '<option value="">Chọn ngày</option>' +
    ds
      .map(
        (x) =>
          `<option value="${x.signal_date}">${x.signal_date} (${x.total})</option>`,
      )
      .join("");
  document.getElementById("startSelect").innerHTML = opts;
  document.getElementById("endSelect").innerHTML = opts;
}
async function loadOptions() {
  let sectorValue = document.getElementById("sectorFilter")?.value || "";
  let actionValue = document.getElementById("actionFilter")?.value || "";
  let o = await j("/api/options");
  document.getElementById("sectorFilter").innerHTML =
    '<option value="">Tất cả</option>' +
    o.sectors.map((x) => `<option>${x}</option>`).join("");
  document.getElementById("actionFilter").innerHTML =
    '<option value="">Tất cả</option>' +
    o.actions.map((x) => `<option>${x}</option>`).join("");
  setSelectIfExists("sectorFilter", sectorValue);
  setSelectIfExists("actionFilter", actionValue);
  filterOptionsLoaded = true;
}
async function ensureFilterOptions() {
  if (!filterOptionsLoaded) await loadOptions();
}
loadHealthBanner();
loadDates()
  .then(loadOptions)
  .then(loadDash)
  .catch((e) => showModal("❌ Lỗi tải dashboard", String(e), ""));


function renderSimpleTable(el, rows, cols) {
  let t = document.getElementById(el);
  if (!t) return;
  if (!rows || !rows.length) { t.innerHTML = '<tr><td class="muted">Không có dữ liệu</td></tr>'; return; }
  let h = '<tr>' + cols.map(c => `<th>${c}</th>`).join('') + '</tr>';
  let b = rows.map(r => '<tr>' + cols.map(c => `<td>${fmt(r[c])}</td>`).join('') + '</tr>').join('');
  t.innerHTML = h + b;
}

async function loadMa20EmaD1() {
  let p = new URLSearchParams();
  let d = document.getElementById('ma20Date')?.value; if (d) p.set('date', d);
  let st = document.getElementById('ma20State')?.value; if (st) p.set('state', st);
  let ms = document.getElementById('ma20MinScore')?.value; if (ms) p.set('min_score', ms);
  
  // Load date dropdown from persisted history
  try {
    const dates = await j('/api/ma20-ema-d1/dates');
    const sel = document.getElementById('ma20Date');
    if (sel && Array.isArray(dates) && dates.length > 0) {
      const cur = sel.value;
      sel.innerHTML = dates.map(x => `<option value="${x.scan_date}">${x.scan_date} (${x.cnt} mã)</option>`).join('');
      // Auto-select latest date if nothing selected
      if (cur) { sel.value = cur; }
      else { sel.value = dates[0].scan_date; p.set('date', dates[0].scan_date); }
    }
  } catch(e) { /* ignore */ }
  
  let data = await j('/api/ma20-ema-d1/scan?' + p.toString());
  const srcLabel = data.summary?.source === 'persisted' ? ' (từ DB)' : ' (tính realtime)';
  document.getElementById('ma20Meta').textContent = `Ngày ${data.date} · ${data.summary?.signal_count || 0} mã${srcLabel}`;
  document.getElementById('ma20Summary').innerHTML = `Bộ lọc: ema_gap 0.1-3% · Volume≥1tr · Close≥MA20×0.97`;
  let rows = (data.rows || []).map((r, i) => ({
    'STT': i + 1,
    'Mã': r.ticker,
    'Close': price(r.close),
    'MA20': price(r.ma20),
    'EMA99': price(r.ema99),
    'EMA200': price(r.ema200),
    'EMA Gap %': pct(r.ema_gap_pct),
    'Vol TB20': num(r.vol_ma20, 0)
  }));
  renderSimpleTable('ma20Table', rows, ['STT','Mã','Close','MA20','EMA99','EMA200','EMA Gap %','Vol TB20']);
}

async function runMa20EmaBacktest() {
  let p = new URLSearchParams();
  let d = document.getElementById('ma20Date')?.value; if (d) p.set('end', d);
  let data = await j('/api/ma20-ema-d1/backtest?' + p.toString());
  let stats = data.stats || {};
  let lines = Object.entries(stats).map(([k,v]) => `${k}: trades <b>${v.trades}</b> · winrate <b>${v.winrate_net}%</b> · avg <b>${v.avg_return_pct}%</b> · PF <b>${v.profit_factor ?? '—'}</b>`);
  document.getElementById('ma20BacktestSummary').innerHTML = (data.note ? `<div>${data.note}</div>` : '') + lines.join('<br>');
  let rows = (data.trades || []).map((r, i) => ({
    'STT': i + 1,
    'Mã': r.ticker,
    'Horizon': 'T+' + r.horizon,
    'Signal': r.signal_date,
    'Entry': r.entry_date + ' @ ' + price(r.entry_price),
    'Exit': r.exit_date + ' @ ' + price(r.exit_price),
    'Reason': r.exit_reason,
    'Gross %': pct(r.gross_return_pct),
    'Net %': pct(r.net_return_pct),
    'Score': num(r.score,1)
  }));
  renderSimpleTable('ma20BacktestTable', rows, ['STT','Mã','Horizon','Signal','Entry','Exit','Reason','Gross %','Net %','Score']);
}
