"use client";

import React from "react";

const PATHS = [
  {
    d: "M 310 200 H 250 Q 230 200 230 180 V 100 Q 230 80 210 80 H 150",
    delay: 0,
    duration: 2.8,
  },
  { d: "M 310 200 H 100", delay: 1.4, duration: 2.0 },
  {
    d: "M 310 200 H 250 Q 230 200 230 220 V 300 Q 230 320 210 320 H 150",
    delay: 0.7,
    duration: 2.4,
  },
  {
    d: "M 490 200 H 550 Q 570 200 570 180 V 100 Q 570 80 590 80 H 650",
    delay: 0.9,
    duration: 2.6,
  },
  { d: "M 490 200 H 700", delay: 0.4, duration: 2.1 },
  {
    d: "M 490 200 H 550 Q 570 200 570 220 V 300 Q 570 320 590 320 H 650",
    delay: 1.8,
    duration: 2.9,
  },
];

const Node = ({
  x,
  y,
  children,
}: {
  x: number;
  y: number;
  children: React.ReactNode;
}) => (
  <div
    className="absolute z-10 flex h-[68px] w-[68px] items-center justify-center rounded-full border bg-background transition-transform hover:scale-105"
    style={{ left: `${x}%`, top: `${y}%`, transform: "translate(-50%, -50%)" }}
  >
    {children}
  </div>
);

export default function App() {
  return (
    <div className="relative aspect-video w-full">
      <style>{`
            @keyframes flow-animation {
              0% { stroke-dashoffset: 25; opacity: 0; }
              5% { opacity: 1; }
              85% { opacity: 1; }
              100% { stroke-dashoffset: -400; opacity: 0; }
            }
            .animated-flow-line {
              stroke-dasharray: 25 400;
              stroke-dashoffset: 25;
              opacity: 0;
              animation: flow-animation linear infinite;
              filter: drop-shadow(0 0 5px rgba(56, 189, 248, 0.8));
              pointer-events: none;
            }
          `}</style>

      <svg
        className="absolute inset-0 h-full w-full"
        viewBox="0 0 800 400"
        preserveAspectRatio="xMidYMid meet"
      >
        <g
          stroke="var(--border)"
          strokeWidth="2.5"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          {PATHS.map((path, index) => (
            <path key={`static-${index}`} d={path.d} />
          ))}
        </g>
        <g
          stroke="var(--color-emerald-500)"
          strokeWidth="3.5"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          {PATHS.map((path, index) => (
            <path
              key={`animated-${index}`}
              d={path.d}
              className="animated-flow-line"
              style={{
                animationDelay: `${path.delay}s`,
                animationDuration: `${path.duration}s`,
              }}
            />
          ))}
        </g>
      </svg>

      <div className="absolute top-[50%] left-[50%] z-20 flex -translate-x-1/2 -translate-y-1/2 items-center rounded-full border px-8 py-3">
        <span className="text-muted-foreground text-sm">Integrations</span>
      </div>

      <Node x={(150 / 800) * 100} y={(80 / 400) * 100}>
        <svg viewBox="0 0 24 24" className="h-8 w-8">
          <path fill="#E01E5A" d="M9.2 4.4A2.6 2.6 0 006.6 7h2.6V4.4z" />
          <path
            fill="#E01E5A"
            d="M10.4 7a2.6 2.6 0 100 5H5a2.6 2.6 0 110-5h5.4z"
          />
          <path fill="#36C5F0" d="M19.6 9.2A2.6 2.6 0 0017 6.6v2.6h2.6z" />
          <path
            fill="#36C5F0"
            d="M17 10.4a2.6 2.6 0 10-5 0V19a2.6 2.6 0 115 0v-8.6z"
          />
          <path fill="#2EB67D" d="M14.8 19.6A2.6 2.6 0 0017.4 17h-2.6v2.6z" />
          <path
            fill="#2EB67D"
            d="M13.6 17a2.6 2.6 0 100-5H19a2.6 2.6 0 110 5h-5.4z"
          />
          <path fill="#ECB22E" d="M4.4 14.8A2.6 2.6 0 007 17.4v-2.6H4.4z" />
          <path
            fill="#ECB22E"
            d="M7 13.6a2.6 2.6 0 105 0V5a2.6 2.6 0 11-5 0v8.6z"
          />
        </svg>
      </Node>

      <Node x={(100 / 800) * 100} y={(200 / 400) * 100}>
        <div className="relative h-8 w-8">
          <div className="absolute top-0 left-1/2 h-3.5 w-3.5 -translate-x-1/2 rounded-full bg-[#F06A6A]"></div>
          <div className="absolute bottom-0 left-0 h-3.5 w-3.5 rounded-full bg-[#F89D8A]"></div>
          <div className="absolute right-0 bottom-0 h-3.5 w-3.5 rounded-full bg-[#F89D8A]"></div>
        </div>
      </Node>

      <Node x={(150 / 800) * 100} y={(320 / 400) * 100}>
        <svg viewBox="0 0 24 24" className="h-8 w-8" fill="none">
          <path d="M12.2 2L2 19h7l5.2-8.6L12.2 2z" fill="#2684FF" />
          <path d="M14.5 10l-5.4 9H22l-7.5-9z" fill="#0052CC" />
        </svg>
      </Node>

      <Node x={(650 / 800) * 100} y={(80 / 400) * 100}>
        <div className="flex h-[30px] w-[30px] items-center justify-center rounded-[6px] bg-black shadow-inner">
          <span className="mt-[2px] font-serif text-xl leading-none font-bold tracking-tighter text-white">
            N
          </span>
        </div>
      </Node>

      <Node x={(700 / 800) * 100} y={(200 / 400) * 100}>
        <svg viewBox="0 0 24 24" className="h-9 w-9" fill="#0061FF">
          <path d="M12 2l-6 4 6 4-6 4 6 4 6-4-6-4 6-4-6-4z" />
          <path d="M12 22l-6-4h12l-6 4z" />
        </svg>
      </Node>

      <Node x={(650 / 800) * 100} y={(320 / 400) * 100}>
        <svg
          viewBox="0 0 24 24"
          className="h-8 w-8 text-[#FF4F00]"
          stroke="currentColor"
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <line x1="12" y1="3" x2="12" y2="21" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="5.5" y1="5.5" x2="18.5" y2="18.5" />
          <line x1="18.5" y1="5.5" x2="5.5" y2="18.5" />
        </svg>
      </Node>
    </div>
  );
}
