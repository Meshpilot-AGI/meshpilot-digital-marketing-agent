"use client";

import React from "react";
import { motion } from "motion/react";
import {
  Sparkles,
  Wand2,
  Clapperboard,
  Film,
  CalendarClock,
  Facebook,
  Instagram,
  Youtube,
  Linkedin,
  Music2,
  Database,
  Plug,
} from "lucide-react";
import { cn } from "@/lib/utils";

const items = [
  { label: "Claude", icon: Sparkles, color: "text-emerald-500 dark:text-emerald-300", bg: "bg-emerald-50 dark:bg-emerald-950" },
  { label: "MUapi", icon: Wand2, color: "text-violet-500 dark:text-violet-300", bg: "bg-violet-50 dark:bg-violet-950" },
  { label: "HeyGen", icon: Clapperboard, color: "text-sky-500 dark:text-sky-300", bg: "bg-sky-50 dark:bg-sky-950" },
  { label: "Higgsfield", icon: Film, color: "text-orange-500 dark:text-orange-300", bg: "bg-orange-50 dark:bg-orange-950" },
  { label: "Buffer", icon: CalendarClock, color: "text-teal-500 dark:text-teal-300", bg: "bg-teal-50 dark:bg-teal-950" },
  { label: "Meta", icon: Facebook, color: "text-blue-500 dark:text-blue-300", bg: "bg-blue-50 dark:bg-blue-950" },
  { label: "Instagram", icon: Instagram, color: "text-pink-500 dark:text-pink-300", bg: "bg-pink-50 dark:bg-pink-950" },
  { label: "YouTube", icon: Youtube, color: "text-red-500 dark:text-red-300", bg: "bg-red-50 dark:bg-red-950" },
  { label: "TikTok", icon: Music2, color: "text-cyan-500 dark:text-cyan-300", bg: "bg-cyan-50 dark:bg-cyan-950" },
  { label: "LinkedIn", icon: Linkedin, color: "text-indigo-500 dark:text-indigo-300", bg: "bg-indigo-50 dark:bg-indigo-950" },
  { label: "Supabase", icon: Database, color: "text-green-500 dark:text-green-300", bg: "bg-green-50 dark:bg-green-950" },
  { label: "MCP tools", icon: Plug, color: "text-fuchsia-500 dark:text-fuchsia-300", bg: "bg-fuchsia-50 dark:bg-fuchsia-950" },
];

type TagItem = {
  label: string;
  icon: React.ElementType;
  color: string;
  bg: string;
};
const Tag = ({ item }: { item: TagItem }) => (
  <div className="bg-background mx-2 flex min-w-max items-center gap-3 rounded-xl border px-4 py-2 whitespace-nowrap transition-transform duration-300 hover:scale-105">
    <div
      className={`rounded-xl p-2 ${item.bg} flex items-center justify-center`}
    >
      <item.icon className={cn(item.color, "size-3")} />
    </div>
    <span className="text-muted-foreground text-xs font-semibold tracking-tight">
      {item.label}
    </span>
  </div>
);

const MarqueeRow = ({
  direction = "left",
  speed = 40,
  itemsList,
}: {
  direction?: "left" | "right";
  speed?: number;
  itemsList: TagItem[];
}) => {
  const duplicatedItems = [
    ...itemsList,
    ...itemsList,
    ...itemsList,
    ...itemsList,
  ];

  return (
    <div className="flex overflow-hidden py-2 select-none">
      <motion.div
        className="flex"
        animate={{
          x: direction === "left" ? [0, -1000] : [-1000, 0],
        }}
        transition={{
          duration: speed,
          repeat: Infinity,
          ease: "linear",
        }}
      >
        {duplicatedItems.map((item, idx) => (
          <Tag key={idx} item={item} />
        ))}
      </motion.div>
    </div>
  );
};

export default function App() {
  return (
    <div className="flex flex-col justify-center overflow-hidden">
      <div className="relative mx-auto w-full max-w-7xl mask-x-from-80% mask-x-to-90%">
        <MarqueeRow itemsList={items.slice(0, 6)} direction="left" speed={35} />
        <MarqueeRow
          itemsList={items.slice(6, 12)}
          direction="right"
          speed={45}
        />
        <MarqueeRow
          itemsList={[...items.slice(3, 7), ...items.slice(0, 2)]}
          direction="left"
          speed={40}
        />
        <MarqueeRow
          itemsList={[...items.slice(8, 12), ...items.slice(4, 6)]}
          direction="right"
          speed={38}
        />
      </div>
    </div>
  );
}
