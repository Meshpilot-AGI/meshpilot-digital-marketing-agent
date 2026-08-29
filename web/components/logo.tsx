import { cn } from "@/lib/utils";

/**
 * Mesh Pilot mark — a flat-top hexagon with an "M", ringed by mesh/circuit nodes.
 * SVG recreation of the brand logo; uses currentColor so it inherits the theme.
 * To use the exact brand PNG instead, drop it at /public/mesh-pilot-logo.png and
 * swap this component for <img src="/mesh-pilot-logo.png" />.
 */
export function Logo({ className, nodes = true }: { className?: string; nodes?: boolean }) {
  // six hexagon edge midpoints where the mesh lines exit
  const spokes = [
    { x1: 100, y1: 26, x2: 100, y2: 8 },
    { x1: 164, y1: 63, x2: 182, y2: 52 },
    { x1: 164, y1: 137, x2: 182, y2: 148 },
    { x1: 100, y1: 174, x2: 100, y2: 192 },
    { x1: 36, y1: 137, x2: 18, y2: 148 },
    { x1: 36, y1: 63, x2: 18, y2: 52 },
  ];
  return (
    <svg viewBox="0 0 200 200" className={cn("text-current", className)} aria-hidden="true">
      <g fill="none" stroke="currentColor" strokeWidth={7} strokeLinejoin="round" strokeLinecap="round">
        {/* hexagon */}
        <polygon points="100,26 164,63 164,137 100,174 36,137 36,63" />
        {/* M */}
        <path d="M74 128 V78 L100 108 L126 78 V128" strokeWidth={9} />
        {nodes &&
          spokes.map((s, i) => (
            <g key={i}>
              <line x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2} strokeWidth={5} />
              <circle cx={s.x2} cy={s.y2} r={6} fill="currentColor" stroke="none" />
            </g>
          ))}
      </g>
    </svg>
  );
}
