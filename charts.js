// 여러 페이지가 공유하는 포맷 유틸 + 차트 렌더링 함수 (다이버징 바, 파이차트).

export function formatKRW(v) {
  const sign = v < 0 ? "-" : "";
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(1)}억원`;
  if (abs >= 1e4) return `${sign}${Math.round(abs / 1e4).toLocaleString()}만원`;
  return `${sign}${Math.round(abs).toLocaleString()}원`;
}

export function formatPct(v) {
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

export function formatMonth(id) {
  const [y, m] = id.split("-");
  return `${y}년 ${parseInt(m, 10)}월`;
}

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// items: [{label, value}]. sortByValue=false면 입력 순서를 그대로 유지한다 (예: 시간순 추이).
export function renderDivergingBars(items, posLegend, negLegend, valueFormatter, sortByValue = true) {
  if (items.length === 0) {
    return `<p class="empty-note">데이터 없음</p>`;
  }
  const sorted = sortByValue ? [...items].sort((a, b) => b.value - a.value) : [...items];
  const maxAbs = Math.max(1, ...sorted.map((it) => Math.abs(it.value)));
  const maxHalf = 38;

  const rows = sorted.map((it) => {
    const ratio = it.value / maxAbs;
    const barPct = Math.abs(ratio) * maxHalf;
    const isPos = it.value >= 0;
    const fillStyle = isPos
      ? `left:50%; width:${barPct}%; border-radius:0 4px 4px 0; background:var(--series-pos);`
      : `right:50%; width:${barPct}%; border-radius:4px 0 0 4px; background:var(--series-neg);`;
    const valueStyle = isPos
      ? `left:calc(50% + ${barPct}% + 6px);`
      : `right:calc(50% + ${barPct}% + 6px); text-align:right;`;
    return `
      <div class="divbar-row">
        <div class="divbar-label" title="${escapeHtml(it.label)}">${escapeHtml(it.label)}</div>
        <div class="divbar-track">
          <div class="divbar-baseline"></div>
          <div class="divbar-fill" style="${fillStyle}"></div>
          <div class="divbar-value" style="${valueStyle}">${valueFormatter(it.value)}</div>
        </div>
      </div>`;
  }).join("");

  return `
    <div class="divbar-legend">
      <span class="legend-item"><span class="swatch pos"></span>${posLegend}</span>
      <span class="legend-item"><span class="swatch neg"></span>${negLegend}</span>
    </div>
    ${rows}`;
}

export const ASSET_CLASS_ORDER = [
  { key: "주식(개별)", colorVar: "--cat-1", textOnFill: "#ffffff" },
  { key: "주식(ETF)", colorVar: "--cat-2", textOnFill: "#ffffff" },
  { key: "금", colorVar: "--cat-3", textOnFill: "#ffffff" },
  { key: "코인", colorVar: "--cat-4", textOnFill: "#0b0b0b" },
];

function polarToCartesian(cx, cy, r, angleDeg) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: cx + r * Math.sin(rad), y: cy - r * Math.cos(rad) };
}

// breakdown: {카테고리명: {eval_krw, invested_krw}}
export function renderPieChart(breakdown) {
  const entries = ASSET_CLASS_ORDER
    .map((c) => {
      const d = breakdown[c.key] || { eval_krw: 0, invested_krw: 0 };
      const profitPct = d.invested_krw ? ((d.eval_krw - d.invested_krw) / d.invested_krw) * 100 : 0;
      return { ...c, value: d.eval_krw, profitPct };
    })
    .filter((c) => c.value > 0);
  const total = entries.reduce((sum, e) => sum + e.value, 0);
  if (total <= 0) {
    return `<p class="empty-note">데이터 없음</p>`;
  }

  const cx = 80, cy = 80, r = 72;
  let angle = 0;
  let paths = "";
  let labels = "";

  if (entries.length === 1) {
    paths = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="var(${entries[0].colorVar})" stroke="var(--surface-1)" stroke-width="2" />`;
  } else {
    entries.forEach((e) => {
      const pct = e.value / total;
      const startAngle = angle;
      const endAngle = angle + pct * 360;
      const largeArc = endAngle - startAngle > 180 ? 1 : 0;
      const p1 = polarToCartesian(cx, cy, r, startAngle);
      const p2 = polarToCartesian(cx, cy, r, endAngle);
      paths += `<path d="M ${cx} ${cy} L ${p1.x.toFixed(2)} ${p1.y.toFixed(2)} A ${r} ${r} 0 ${largeArc} 1 ${p2.x.toFixed(2)} ${p2.y.toFixed(2)} Z" fill="var(${e.colorVar})" stroke="var(--surface-1)" stroke-width="2" />`;

      if (pct >= 0.08) {
        const mid = polarToCartesian(cx, cy, r * 0.65, (startAngle + endAngle) / 2);
        labels += `<text x="${mid.x.toFixed(2)}" y="${mid.y.toFixed(2)}" class="pie-slice-label" fill="${e.textOnFill}" text-anchor="middle" dominant-baseline="middle">${Math.round(pct * 100)}%</text>`;
      }
      angle = endAngle;
    });
  }

  const legend = entries.map((e) => `
    <div class="pie-legend-row">
      <span class="swatch" style="background:var(${e.colorVar})"></span>
      <span class="pie-legend-label">${e.key}</span>
      <span class="pie-legend-value">
        ${Math.round((e.value / total) * 100)}% · ${formatKRW(e.value)}
        <span class="${e.profitPct > 0 ? "text-good" : e.profitPct < 0 ? "text-bad" : ""}">(${formatPct(e.profitPct)})</span>
      </span>
    </div>`).join("");

  const table = `
    <details class="table-toggle">
      <summary>표로 보기</summary>
      <table class="data-table">
        <thead><tr><th>자산군</th><th>평가금액</th><th>비중</th><th>수익률</th></tr></thead>
        <tbody>
          ${entries.map((e) => `
            <tr>
              <td>${e.key}</td><td>${formatKRW(e.value)}</td><td>${Math.round((e.value / total) * 100)}%</td>
              <td class="${e.profitPct > 0 ? "text-good" : e.profitPct < 0 ? "text-bad" : ""}">${formatPct(e.profitPct)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </details>`;

  return `
    <div class="pie-wrap">
      <svg class="pie-svg" viewBox="0 0 160 160">${paths}${labels}</svg>
      <div class="pie-legend">${legend}</div>
    </div>
    ${table}`;
}
