/**
 * Minimal dependency-free SVG sparkline with severity coloring.
 * Draws in a fixed viewBox; scales to container width via CSS.
 */
const W = 560;
const H = 64;

export default function Sparkline({
  values,
  color = '#38bdf8',
  max,
}: {
  values: number[];
  color?: string;
  max?: number;
}) {
  if (values.length < 2) {
    return <div className="h-16 flex items-center text-slate-600 text-sm">no data</div>;
  }
  const top = max ?? Math.max(...values, 1);
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * W;
      const y = H - (Math.min(Math.max(v, 0), top) / top) * (H - 6) - 3;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  const lastX = W;
  const lastY = H - (Math.min(Math.max(values[values.length - 1], 0), top) / top) * (H - 6) - 3;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-16" preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX - 2} cy={lastY} r={3.5} fill={color} />
    </svg>
  );
}
