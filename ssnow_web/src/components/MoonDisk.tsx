/**
 * Moon phase disk with a proper terminator ellipse.
 *
 * illumination i in [0,1]: 0 = new, 1 = full. The lit limb side depends on
 * waxing/waning (right/left in the Northern Hemisphere convention).
 * Terminator ellipse semi-minor axis rx = r*|1-2i| bulges into the dark side
 * for gibbous phases and into the lit side for crescents.
 */
export function litPath(cx: number, cy: number, r: number, i: number, waxing: boolean): string {
  const top = `${cx},${cy - r}`;
  const bot = `${cx},${cy + r}`;
  const limb = waxing
    ? `M ${top} A ${r},${r} 0 0 1 ${bot}`   // right limb, top→bottom
    : `M ${top} A ${r},${r} 0 0 0 ${bot}`;  // left limb, top→bottom
  const rx = r * Math.abs(1 - 2 * i);
  // Gibbous: terminator bulges into the dark side (sweep 1 when waxing-dark=left).
  // Crescent: terminator bulges into the lit side.
  const gibbous = i >= 0.5;
  const sweep = waxing ? (gibbous ? 1 : 0) : (gibbous ? 0 : 1);
  const term = rx < 0.5 ? `L ${top}` : `A ${rx.toFixed(2)},${r} 0 0 ${sweep} ${top}`;
  return `${limb} ${term} Z`;
}

export default function MoonDisk({
  illumination,
  phaseName,
  size = 180,
}: {
  illumination: number | null;
  phaseName: string | null;
  size?: number;
}) {
  const i = Math.min(1, Math.max(0, illumination ?? 0));
  const name = (phaseName ?? '').toLowerCase();
  const waxing = !(name.includes('waning') || name.includes('last'));
  const r = size * 0.44;
  const c = size / 2;
  return (
    <svg width={size} height={size}>
      <defs>
        <radialGradient id="moonlit" cx="50%" cy="42%" r="65%">
          <stop offset="0%" stopColor="#f8fafc" />
          <stop offset="70%" stopColor="#e2e8f0" />
          <stop offset="100%" stopColor="#b6c2d4" />
        </radialGradient>
      </defs>
      <circle cx={c} cy={c} r={r} fill="#0f172a" stroke="#334155" strokeWidth={1.5} />
      <path d={litPath(c, c, r, i, waxing)} fill="url(#moonlit)" />
      <circle cx={c} cy={c} r={r} fill="none" stroke="#475569" strokeWidth={1} opacity={0.6} />
    </svg>
  );
}
