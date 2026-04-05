import { useState, useRef, useCallback, useMemo, useId } from 'react';
import { TrendingUp } from 'lucide-react';
import type { SentinelRun } from '@/types';

/* ── Helpers ─────────────────────────────────────────────────── */

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function formatFullDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/* ── Constants ───────────────────────────────────────────────── */

const CHART_HEIGHT = 120;
const PADDING_TOP = 20;
const PADDING_BOTTOM = 24;
const PADDING_LEFT = 36;
const PADDING_RIGHT = 16;
const DOT_RADIUS = 4;
const DOT_HOVER_RADIUS = 6;
const EY_YELLOW = '#FFE600';
const EY_YELLOW_20 = 'rgba(255, 230, 0, 0.20)';
const EY_YELLOW_00 = 'rgba(255, 230, 0, 0)';
const RED_LINE = '#ef4444';
const GRID_COLOR = 'rgba(28, 28, 28, 0.8)';

/* ── Props ───────────────────────────────────────────────────── */

interface ComplianceTrendChartProps {
  runs: SentinelRun[];
}

/* ── Component ───────────────────────────────────────────────── */

export default function ComplianceTrendChart({ runs }: ComplianceTrendChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const gradientId = useId().replace(/:/g, '') + '-area-gradient';
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    compliance: number;
    date: string;
    delta: number | null;
  } | null>(null);

  /* Filter to completed runs with compliance data, sort chronologically */
  const dataPoints = useMemo(() => {
    return runs
      .filter((r) => r.compliance_current != null && r.started_at)
      .sort((a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime())
      .map((r) => ({
        compliance: r.compliance_current as number,
        date: r.started_at,
        delta: r.compliance_delta,
      }));
  }, [runs]);

  /* Check if any run has a negative compliance delta (regression) */
  const hasRegression = useMemo(
    () => dataPoints.some((p) => p.delta != null && p.delta < 0),
    [dataPoints],
  );

  /* Scale computation */
  const getScales = useCallback(
    (width: number) => {
      const plotW = width - PADDING_LEFT - PADDING_RIGHT;
      const plotH = CHART_HEIGHT - PADDING_TOP - PADDING_BOTTOM;

      const minY = 0;
      const maxY = 100;

      const xScale = (i: number) =>
        PADDING_LEFT +
        (dataPoints.length > 1 ? (i / (dataPoints.length - 1)) * plotW : plotW / 2);

      const yScale = (val: number) =>
        PADDING_TOP + plotH - ((val - minY) / (maxY - minY)) * plotH;

      return { xScale, yScale, plotW, plotH };
    },
    [dataPoints],
  );

  /* Mouse interaction */
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      const svg = svgRef.current;
      if (!svg || dataPoints.length < 2) return;

      const rect = svg.getBoundingClientRect();
      const svgWidth = 400; // matches viewBox width
      const mouseX = ((e.clientX - rect.left) / rect.width) * svgWidth;

      const { xScale } = getScales(svgWidth);

      /* Find closest point */
      let closest = 0;
      let closestDist = Infinity;
      for (let i = 0; i < dataPoints.length; i++) {
        const px = xScale(i);
        const dist = Math.abs(mouseX - px);
        if (dist < closestDist) {
          closestDist = dist;
          closest = i;
        }
      }

      if (closestDist < 30) {
        const { yScale } = getScales(svgWidth);
        const point = dataPoints[closest];
        setTooltip({
          x: xScale(closest),
          y: yScale(point.compliance),
          compliance: point.compliance,
          date: point.date,
          delta: point.delta,
        });
      } else {
        setTooltip(null);
      }
    },
    [dataPoints, getScales],
  );

  const handleMouseLeave = useCallback(() => setTooltip(null), []);

  /* ── Not enough data ────────────────────────────────────────── */
  if (dataPoints.length < 2) {
    return (
      <div className="rounded-xl border border-dark-border bg-dark-card p-5">
        <div className="flex items-center gap-2 mb-4">
          <TrendingUp className="h-4 w-4 text-ey-yellow" />
          <h3 className="text-sm font-semibold text-white uppercase tracking-wider">
            Compliance Trend
          </h3>
        </div>
        <div className="flex items-center justify-center py-6 border-2 border-dashed border-dark-border rounded-lg">
          <p className="text-xs text-dark-muted">
            Need at least 2 runs to show trend
          </p>
        </div>
      </div>
    );
  }

  /* ── Render SVG chart ───────────────────────────────────────── */
  return (
    <div className="rounded-xl border border-dark-border bg-dark-card p-5">
      <div className="flex items-center gap-2 mb-4">
        <TrendingUp className="h-4 w-4 text-ey-yellow" />
        <h3 className="text-sm font-semibold text-white uppercase tracking-wider">
          Compliance Trend
        </h3>
        <span className="ml-auto text-[10px] text-dark-muted font-medium">
          {dataPoints.length} run{dataPoints.length !== 1 ? 's' : ''}
        </span>
      </div>

      <div className="relative w-full" style={{ height: CHART_HEIGHT }}>
        <svg
          ref={svgRef}
          className="w-full"
          viewBox={`0 0 400 ${CHART_HEIGHT}`}
          preserveAspectRatio="none"
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          style={{ height: CHART_HEIGHT }}
        >
          <defs>
            {/* Area gradient */}
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={EY_YELLOW_20} />
              <stop offset="100%" stopColor={EY_YELLOW_00} />
            </linearGradient>
          </defs>

          {/* Y-axis grid lines + labels */}
          <ChartGrid height={CHART_HEIGHT} />

          {/* Regression threshold line */}
          {hasRegression && (
            <RegressionLine
              dataPoints={dataPoints}
              getScales={getScales}
              svgWidth={400}
            />
          )}

          {/* Area fill */}
          <AreaPath dataPoints={dataPoints} getScales={getScales} svgWidth={400} gradientId={gradientId} />

          {/* Line */}
          <LinePath dataPoints={dataPoints} getScales={getScales} svgWidth={400} />

          {/* Data point dots */}
          <DataDots
            dataPoints={dataPoints}
            getScales={getScales}
            svgWidth={400}
            hoveredIndex={
              tooltip
                ? dataPoints.findIndex(
                    (p) => p.date === tooltip.date && p.compliance === tooltip.compliance,
                  )
                : -1
            }
          />

          {/* X-axis labels */}
          <XAxisLabels dataPoints={dataPoints} getScales={getScales} svgWidth={400} />
        </svg>

        {/* Tooltip overlay */}
        {tooltip && (
          <ChartTooltip
            x={tooltip.x}
            y={tooltip.y}
            compliance={tooltip.compliance}
            date={tooltip.date}
            delta={tooltip.delta}
            svgWidth={400}
          />
        )}
      </div>
    </div>
  );
}

/* ── Sub-components ──────────────────────────────────────────── */

function ChartGrid({ height }: { height: number }) {
  const plotH = height - PADDING_TOP - PADDING_BOTTOM;
  const ticks = [0, 25, 50, 75, 100];

  return (
    <g>
      {ticks.map((val) => {
        const y = PADDING_TOP + plotH - (val / 100) * plotH;
        return (
          <g key={val}>
            <line
              x1={PADDING_LEFT}
              x2={400 - PADDING_RIGHT}
              y1={y}
              y2={y}
              stroke={GRID_COLOR}
              strokeWidth={0.5}
            />
            <text
              x={PADDING_LEFT - 4}
              y={y + 3}
              textAnchor="end"
              fill="#555555"
              fontSize={9}
              fontFamily="system-ui, sans-serif"
            >
              {val}
            </text>
          </g>
        );
      })}
    </g>
  );
}

interface ScalesGetter {
  (width: number): {
    xScale: (i: number) => number;
    yScale: (val: number) => number;
    plotW: number;
    plotH: number;
  };
}

interface DataPoint {
  compliance: number;
  date: string;
  delta: number | null;
}

function LinePath({
  dataPoints,
  getScales,
  svgWidth,
}: {
  dataPoints: DataPoint[];
  getScales: ScalesGetter;
  svgWidth: number;
}) {
  const { xScale, yScale } = getScales(svgWidth);
  const d = dataPoints
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${xScale(i)} ${yScale(p.compliance)}`)
    .join(' ');

  return (
    <path
      d={d}
      fill="none"
      stroke={EY_YELLOW}
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  );
}

function AreaPath({
  dataPoints,
  getScales,
  svgWidth,
  gradientId,
}: {
  dataPoints: DataPoint[];
  getScales: ScalesGetter;
  svgWidth: number;
  gradientId: string;
}) {
  const { xScale, yScale, plotH } = getScales(svgWidth);
  const bottomY = PADDING_TOP + plotH;

  const lineParts = dataPoints
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${xScale(i)} ${yScale(p.compliance)}`)
    .join(' ');

  const d = `${lineParts} L ${xScale(dataPoints.length - 1)} ${bottomY} L ${xScale(0)} ${bottomY} Z`;

  return <path d={d} fill={`url(#${gradientId})`} />;
}

function DataDots({
  dataPoints,
  getScales,
  svgWidth,
  hoveredIndex,
}: {
  dataPoints: DataPoint[];
  getScales: ScalesGetter;
  svgWidth: number;
  hoveredIndex: number;
}) {
  const { xScale, yScale } = getScales(svgWidth);

  return (
    <g>
      {dataPoints.map((p, i) => (
        <circle
          key={i}
          cx={xScale(i)}
          cy={yScale(p.compliance)}
          r={i === hoveredIndex ? DOT_HOVER_RADIUS : DOT_RADIUS}
          fill={i === hoveredIndex ? EY_YELLOW : '#0A0A0A'}
          stroke={EY_YELLOW}
          strokeWidth={2}
          style={{ transition: 'r 0.15s ease' }}
        />
      ))}
    </g>
  );
}

function XAxisLabels({
  dataPoints,
  getScales,
  svgWidth,
}: {
  dataPoints: DataPoint[];
  getScales: ScalesGetter;
  svgWidth: number;
}) {
  const { xScale } = getScales(svgWidth);

  /* Show at most ~6 labels to avoid crowding */
  const step = Math.max(1, Math.floor(dataPoints.length / 6));
  const indices: number[] = [];
  for (let i = 0; i < dataPoints.length; i += step) {
    indices.push(i);
  }
  if (!indices.includes(dataPoints.length - 1)) {
    indices.push(dataPoints.length - 1);
  }

  return (
    <g>
      {indices.map((i) => (
        <text
          key={i}
          x={xScale(i)}
          y={CHART_HEIGHT - 4}
          textAnchor="middle"
          fill="#555555"
          fontSize={8}
          fontFamily="system-ui, sans-serif"
        >
          {formatShortDate(dataPoints[i].date)}
        </text>
      ))}
    </g>
  );
}

function RegressionLine({
  dataPoints,
  getScales,
  svgWidth,
}: {
  dataPoints: DataPoint[];
  getScales: ScalesGetter;
  svgWidth: number;
}) {
  /* Find the lowest compliance value where a regression happened */
  const regressionPoints = dataPoints.filter((p) => p.delta != null && p.delta < 0);
  if (regressionPoints.length === 0) return null;

  const lowestRegression = Math.min(...regressionPoints.map((p) => p.compliance));
  const { yScale } = getScales(svgWidth);
  const y = yScale(lowestRegression);

  return (
    <line
      x1={PADDING_LEFT}
      x2={svgWidth - PADDING_RIGHT}
      y1={y}
      y2={y}
      stroke={RED_LINE}
      strokeWidth={1}
      strokeDasharray="4 3"
      opacity={0.5}
    />
  );
}

function ChartTooltip({
  x,
  y,
  compliance,
  date,
  delta,
  svgWidth,
}: {
  x: number;
  y: number;
  compliance: number;
  date: string;
  delta: number | null;
  svgWidth: number;
}) {
  /* Convert SVG coordinates to percentage-based positioning for responsive layout */
  const leftPct = (x / svgWidth) * 100;
  const topPct = (y / CHART_HEIGHT) * 100;

  /* Flip tooltip to the left if too close to right edge */
  const flipLeft = leftPct > 75;

  return (
    <div
      className="absolute pointer-events-none z-20"
      style={{
        left: `${leftPct}%`,
        top: `${topPct}%`,
        transform: `translate(${flipLeft ? 'calc(-100% - 12px)' : '12px'}, -50%)`,
      }}
    >
      <div className="rounded-lg bg-dark-overlay border border-dark-border px-3 py-2 shadow-xl">
        <div className="text-xs font-bold text-white">
          {compliance.toFixed(1)}%
        </div>
        <div className="text-[10px] text-dark-secondary mt-0.5">
          {formatFullDate(date)}
        </div>
        {delta != null && delta !== 0 && (
          <div
            className={`text-[10px] font-semibold mt-0.5 ${
              delta > 0 ? 'text-emerald-400' : 'text-red-400'
            }`}
          >
            {delta > 0 ? '+' : ''}
            {delta.toFixed(1)}%
          </div>
        )}
      </div>
    </div>
  );
}
