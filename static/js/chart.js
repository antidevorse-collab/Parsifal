// График цены товара: ступенчатая линия (цена держится до следующей смены),
// пропуски в наблюдениях — пунктиром, прогноз — пунктир с 90% диапазоном.
// Данные — JSON из ProductCard.chart() (presenters.py) внутри [data-price-chart].
(function () {
  "use strict";

  const SVG = "http://www.w3.org/2000/svg";
  const DAY = 86400000;
  const PAD = { top: 16, right: 74, bottom: 28, left: 64 };
  const moneyFmt = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
  const dayFmt = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" });
  const fullFmt = new Intl.DateTimeFormat("ru-RU", {
    day: "numeric", month: "long", hour: "2-digit", minute: "2-digit",
  });

  const money = (v) => moneyFmt.format(Math.round(v)) + " ₽";

  function el(name, attrs, parent) {
    const node = document.createElementNS(SVG, name);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }

  // «Круглые» деления оси: шаг 1/2/2.5/5 × 10^n
  function niceTicks(min, max, count) {
    if (min === max) {
      const pad = Math.max(Math.abs(min) * 0.05, 1);
      min -= pad;
      max += pad;
    }
    const raw = (max - min) / count;
    const pow = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw);
    const lo = Math.floor(min / step) * step;
    const hi = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = lo; v <= hi + step / 2; v += step) ticks.push(v);
    return ticks;
  }

  // Точки в окне периода; цена на начало окна — последняя известная до него
  function visiblePoints(points, days) {
    if (!days) return points;
    const start = points[points.length - 1].t - days * DAY;
    const inside = points.filter((p) => p.t >= start);
    const before = points.filter((p) => p.t < start).pop();
    if (before && (!inside.length || inside[0].t > start)) {
      inside.unshift({ t: start, p: before.p, gap: false });
    }
    return inside;
  }

  function render(box, chart, days) {
    box.textContent = "";
    const width = box.clientWidth;
    const height = box.clientHeight;
    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img",
                            "aria-label": `График цены: ${chart.title}` }, box);

    const all = chart.points.map((p) => ({ t: new Date(p.t).getTime(), p: p.p, gap: p.gap }));
    if (!all.length) {
      el("text", { x: width / 2, y: height / 2, "text-anchor": "middle", class: "empty" }, svg)
        .textContent = "Нет данных о цене";
      return;
    }
    const pts = visiblePoints(all, days);
    const last = pts[pts.length - 1];
    const fc = chart.forecast && {
      t: new Date(chart.forecast.t).getTime(), p: chart.forecast.p,
      low: chart.forecast.low, high: chart.forecast.high,
    };

    let t0 = pts[0].t;
    let t1 = fc ? Math.max(last.t, fc.t) : last.t;
    if (t1 - t0 < DAY) { t0 -= DAY / 2; t1 += DAY / 2; }

    const values = pts.map((p) => p.p);
    if (fc) values.push(fc.low, fc.high);
    const ticks = niceTicks(Math.min(...values), Math.max(...values), 4);
    const v0 = ticks[0];
    const v1 = ticks[ticks.length - 1];

    const plotW = width - PAD.left - PAD.right;
    const plotH = height - PAD.top - PAD.bottom;
    const x = (t) => PAD.left + ((t - t0) / (t1 - t0)) * plotW;
    const y = (v) => PAD.top + (1 - (v - v0) / (v1 - v0)) * plotH;

    const defs = el("defs", {}, svg);
    const grad = el("linearGradient", { id: "chartFill", x1: 0, x2: 0, y1: 0, y2: 1 }, defs);
    el("stop", { offset: "0%", "stop-color": "#78c9ad", "stop-opacity": 0.3 }, grad);
    el("stop", { offset: "100%", "stop-color": "#78c9ad", "stop-opacity": 0 }, grad);

    // Сетка и оси
    const grid = el("g", { class: "grid" }, svg);
    const axis = el("g", { class: "axis" }, svg);
    for (const v of ticks) {
      el("line", { x1: PAD.left, x2: width - PAD.right, y1: y(v), y2: y(v) }, grid);
      el("text", { x: PAD.left - 10, y: y(v) + 4, "text-anchor": "end" }, axis).textContent = money(v);
    }
    const labels = Math.max(2, Math.min(6, Math.floor(plotW / 90)));
    for (let i = 0; i < labels; i++) {
      const t = t0 + ((t1 - t0) * i) / (labels - 1);
      const anchor = i === 0 ? "start" : i === labels - 1 ? "end" : "middle";
      el("text", { x: x(t), y: height - 6, "text-anchor": anchor }, axis).textContent = dayFmt.format(t);
    }

    // Ступенчатая линия: сплошные отрезки и пунктирные через пропуски
    let solid = `M${x(pts[0].t)},${y(pts[0].p)}`;
    let dashed = "";
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1];
      const b = pts[i];
      const seg = `M${x(a.t)},${y(a.p)}H${x(b.t)}V${y(b.p)}`;
      if (b.gap) dashed += seg;
      else solid += `H${x(b.t)}V${y(b.p)}`;
      if (b.gap) solid += `M${x(b.t)},${y(b.p)}`;
    }
    const base = y(v0);
    let area = `M${x(pts[0].t)},${base}V${y(pts[0].p)}`;
    for (let i = 1; i < pts.length; i++) area += `H${x(pts[i].t)}V${y(pts[i].p)}`;
    area += `V${base}Z`;
    el("path", { d: area, class: "area" }, svg);
    el("path", { d: solid, class: "series" }, svg);
    if (dashed) el("path", { d: dashed, class: "series gap" }, svg);

    // Прогноз
    if (fc) {
      el("path", { class: "forecast-band",
                   d: `M${x(last.t)},${y(last.p)}L${x(fc.t)},${y(fc.high)}L${x(fc.t)},${y(fc.low)}Z` }, svg);
      el("path", { class: "forecast-line", d: `M${x(last.t)},${y(last.p)}L${x(fc.t)},${y(fc.p)}` }, svg);
      el("text", { class: "forecast-label", x: x(fc.t) + 8, y: y(fc.p) + 4 }, svg)
        .textContent = "≈ " + money(fc.p);
    }
    el("circle", { class: "dot", cx: x(last.t), cy: y(last.p), r: 5 }, svg);

    // Наведение: перекрестие и подсказка с ценой на выбранный момент
    const cross = el("line", { class: "crosshair", y1: PAD.top, y2: PAD.top + plotH, visibility: "hidden" }, svg);
    const hoverDot = el("circle", { class: "dot", r: 5, visibility: "hidden" }, svg);
    const tip = document.createElement("div");
    tip.className = "chart-tooltip";
    tip.hidden = true;
    box.appendChild(tip);

    function show(clientX) {
      const rect = svg.getBoundingClientRect();
      const t = t0 + ((clientX - rect.left - PAD.left) / plotW) * (t1 - t0);
      let px, py, html;
      if (fc && t > last.t) {
        px = x(fc.t);
        py = y(fc.p);
        html = `Прогноз на ${dayFmt.format(fc.t)}<strong>≈ ${money(fc.p)}</strong>` +
               `${money(fc.low)} – ${money(fc.high)}`;
      } else {
        const tt = Math.max(pts[0].t, Math.min(t, last.t));
        let point = pts[0];
        for (const p of pts) if (p.t <= tt) point = p;
        px = x(tt);
        py = y(point.p);
        html = `${fullFmt.format(tt)}<strong>${money(point.p)}</strong>`;
      }
      cross.setAttribute("x1", px);
      cross.setAttribute("x2", px);
      hoverDot.setAttribute("cx", px);
      hoverDot.setAttribute("cy", py);
      cross.setAttribute("visibility", "visible");
      hoverDot.setAttribute("visibility", "visible");
      tip.innerHTML = html;
      tip.hidden = false;
      const half = tip.offsetWidth / 2;
      tip.style.left = Math.max(half, Math.min(width - half, px)) + "px";
      tip.style.top = Math.max(0, py - tip.offsetHeight - 12) + "px";
    }

    function hide() {
      cross.setAttribute("visibility", "hidden");
      hoverDot.setAttribute("visibility", "hidden");
      tip.hidden = true;
    }

    const hit = el("rect", { x: PAD.left, y: 0, width: Math.max(plotW, 0), height, fill: "transparent" }, svg);
    hit.addEventListener("pointermove", (e) => show(e.clientX));
    hit.addEventListener("pointerdown", (e) => show(e.clientX));
    hit.addEventListener("pointerleave", hide);
  }

  function init(section) {
    const charts = JSON.parse(section.querySelector("[data-chart-data]").textContent);
    const box = section.querySelector("[data-chart-canvas]");
    const select = section.querySelector("[data-chart-select]");
    const buttons = section.querySelectorAll("[data-days]");
    const state = { index: 0, days: 0 };
    if (!charts.length) return;

    const draw = () => render(box, charts[state.index], state.days);
    select && select.addEventListener("change", () => { state.index = +select.value; draw(); });
    buttons.forEach((btn) => btn.addEventListener("click", () => {
      state.days = +btn.dataset.days;
      buttons.forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      draw();
    }));
    let lastWidth = 0;
    new ResizeObserver(() => {
      if (box.clientWidth !== lastWidth) { lastWidth = box.clientWidth; draw(); }
    }).observe(box);
  }

  document.querySelectorAll("[data-price-chart]").forEach(init);
})();
