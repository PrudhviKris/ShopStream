// Small, dependency-free charts for the admin analytics dashboard.
//
// Conventions (kept deliberately quiet so the data is the loud part):
//   - single-series marks in the brand accent; text always in ink tokens
//   - 2px line + ~10% area wash; bars <= 14px thick, 4px rounded data-end,
//     square at the baseline; 1px solid recessive gridlines
//   - every chart has a hover/focus layer, and every value it shows is also
//     reachable without hovering (direct labels, or the table toggle)
import { useEffect, useMemo, useRef, useState } from "react";

function useWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

// 0 → a clean round ceiling (1, 2, 2.5, 5 × 10^n) so axis ticks read naturally.
function niceMax(value, ticks = 4) {
  if (value <= 0) return ticks;
  const raw = value / ticks;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].find((m) => m * magnitude >= raw) * magnitude;
  return step * ticks;
}

const shortDate = (iso) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });

export function TrendChart({ data, valueKey, format, formatAxis = format, secondary, height = 230 }) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState(null);

  const pad = { top: 14, right: 16, bottom: 28, left: 64 };
  const innerW = Math.max(0, width - pad.left - pad.right);
  const innerH = height - pad.top - pad.bottom;
  const max = useMemo(() => niceMax(Math.max(0, ...data.map((d) => d[valueKey]))), [data, valueKey]);

  const x = (i) => pad.left + (data.length <= 1 ? innerW / 2 : (i / (data.length - 1)) * innerW);
  const y = (v) => pad.top + innerH - (v / max) * innerH;

  const line = data.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d[valueKey]).toFixed(1)}`).join("");
  const area = data.length ? `${line}L${x(data.length - 1)},${y(0)}L${x(0)},${y(0)}Z` : "";
  const ticks = [0, 1, 2, 3, 4].map((t) => (max / 4) * t);
  const labelIdx = data.length > 2 ? [0, Math.floor((data.length - 1) / 2), data.length - 1] : data.map((_, i) => i);

  function pick(clientX) {
    const box = ref.current.getBoundingClientRect();
    const rel = clientX - box.left - pad.left;
    const i = Math.round((rel / Math.max(innerW, 1)) * (data.length - 1));
    setActive(Math.min(data.length - 1, Math.max(0, i)));
  }

  function onKey(e) {
    if (e.key === "ArrowRight") setActive((i) => Math.min(data.length - 1, (i ?? -1) + 1));
    else if (e.key === "ArrowLeft") setActive((i) => Math.max(0, (i ?? data.length) - 1));
    else if (e.key === "Escape") setActive(null);
    else return;
    e.preventDefault();
  }

  const point = active != null ? data[active] : null;
  // Beside the crosshair, never on top of the point it describes; flips to
  // the left side near the right edge.
  const flip = point && x(active) > width - 190;
  const tipStyle = point
    ? { left: x(active) + (flip ? -12 : 12), top: pad.top, transform: flip ? "translateX(-100%)" : "none" }
    : null;

  return (
    <div className="viz trend" ref={ref} style={{ height }}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          tabIndex={0}
          aria-label="Trend chart — use the arrow keys to read each day"
          onPointerMove={(e) => pick(e.clientX)}
          onPointerLeave={() => setActive(null)}
          onKeyDown={onKey}
          onBlur={() => setActive(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line className="viz-grid" x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} />
              <text className="viz-axis" x={pad.left - 10} y={y(t)} dy="0.32em" textAnchor="end">
                {formatAxis(t)}
              </text>
            </g>
          ))}
          {labelIdx.map((i) => (
            <text key={i} className="viz-axis" x={x(i)} y={height - 8}
              textAnchor={i === 0 ? "start" : i === data.length - 1 ? "end" : "middle"}>
              {shortDate(data[i].date)}
            </text>
          ))}
          <path className="viz-area" d={area} />
          <path className="viz-line" d={line} />
          {point && (
            <>
              <line className="viz-crosshair" x1={x(active)} x2={x(active)} y1={pad.top} y2={pad.top + innerH} />
              <circle className="viz-dot" cx={x(active)} cy={y(point[valueKey])} r={4.5} />
            </>
          )}
        </svg>
      )}
      {point && (
        <div className="viz-tip" style={tipStyle}>
          <strong>{format(point[valueKey])}</strong>
          <span>{shortDate(point.date)}{secondary ? ` · ${secondary(point)}` : ""}</span>
        </div>
      )}
    </div>
  );
}

// Horizontal bars with the value at each bar's tip. rows: [{ key, label, value }]
export function BarList({ rows, format, emptyText = "No data yet." }) {
  const [active, setActive] = useState(null);
  const max = Math.max(0, ...rows.map((r) => r.value));
  const total = rows.reduce((sum, r) => sum + r.value, 0);

  if (rows.length === 0 || total === 0) return <div className="viz-empty">{emptyText}</div>;

  return (
    <div className="viz bars" onPointerLeave={() => setActive(null)}>
      {rows.map((r) => {
        const share = total ? Math.round((r.value / total) * 100) : 0;
        const on = active === r.key;
        return (
          <div
            key={r.key}
            className={`bar-row ${on ? "on" : ""}`}
            tabIndex={0}
            onPointerEnter={() => setActive(r.key)}
            onFocus={() => setActive(r.key)}
            onBlur={() => setActive(null)}
            aria-label={`${r.label}: ${format(r.value)} (${share}%)`}
          >
            <span className="bar-label" title={r.label}>{r.label}</span>
            <span className="bar-track">
              <span className="bar-fill" style={{ width: max ? `${Math.max((r.value / max) * 100, r.value ? 1.5 : 0)}%` : 0 }} />
              <span className="bar-value">{format(r.value)}</span>
            </span>
            {on && (
              <span className="viz-tip bar-tip">
                <strong>{format(r.value)}</strong>
                <span>{r.label} · {share}% of total</span>
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
