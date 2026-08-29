"use client";

import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import {
  Brain,
  ShieldCheck,
  Sparkles,
  RefreshCw,
  Image as ImageIcon,
  Clapperboard,
  Send,
  Plug,
  ArrowRight,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Toaster } from "@/components/ui/sonner";
import { WaitlistForm } from "@/components/waitlist-form";
import IntegrationHub from "@/components/illustration5";
import StackMarquee from "@/components/illustration7";
import { Logo } from "@/components/logo";

/* ── motion helpers ─────────────────────────────────────────────── */
function Reveal({ children, delay = 0, className }: { children: React.ReactNode; delay?: number; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y: 22 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{ duration: 0.6, delay, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </motion.div>
  );
}

function LiveDot() {
  return (
    <span className="relative flex h-2 w-2">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-70" />
      <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
    </span>
  );
}

/* The autonomous loop, shown running. Motivated motion: it never stops. */
const LOOP = ["Recall", "Decide", "Create", "Publish", "Learn"] as const;
function AutonomousLoop() {
  const reduce = useReducedMotion();
  const [active, setActive] = useState(0);
  useEffect(() => {
    if (reduce) return;
    const t = setInterval(() => setActive((i) => (i + 1) % LOOP.length), 1400);
    return () => clearInterval(t);
  }, [reduce]);
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-5">
      <div className="mb-4 flex items-center gap-2 text-xs font-medium text-neutral-400">
        <LiveDot /> agent · running
      </div>
      <div className="grid grid-cols-5 gap-2">
        {LOOP.map((stage, i) => (
          <div key={stage} className="flex flex-col items-center gap-2">
            <div
              className={`h-1.5 w-full rounded-full transition-colors duration-500 ${
                i === active ? "bg-emerald-400" : "bg-white/10"
              }`}
            />
            <span
              className={`text-[11px] transition-colors duration-500 ${
                i === active ? "text-neutral-100" : "text-neutral-500"
              }`}
            >
              {stage}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── capabilities data ──────────────────────────────────────────── */
const CAPABILITIES = [
  { icon: ImageIcon, title: "Generates on-brand images", body: "Logos, ad creative, thumbnails, product shots across MUapi, HeyGen, and Higgsfield." },
  { icon: Clapperboard, title: "Produces video", body: "Seedance, Kling, and avatar / talking-head video from a single brief." },
  { icon: Send, title: "Publishes on schedule", body: "Buffer, Meta, and YouTube. It picks the moment; you set the rules." },
  { icon: Plug, title: "Connects to any tool", body: "Speaks MCP, so it plugs into the tools you already run and grows new skills." },
];

const BRAIN = [
  { icon: Brain, title: "Memory", body: "Per-brand facts and episodes, recalled semantically. It remembers what worked." },
  { icon: ShieldCheck, title: "Policy", body: "A deterministic gate checks every action before it runs. Nothing ships that you did not allow." },
  { icon: RefreshCw, title: "Learning", body: "A curator distills each run into durable lessons, so tomorrow starts smarter than today." },
];

export default function Page() {
  return (
    <main className="relative min-h-[100dvh] bg-neutral-950 text-neutral-200 antialiased">
      {/* ambient glow, fixed + non-interactive */}
      <div className="pointer-events-none fixed inset-0 z-0">
        <div className="absolute left-1/2 top-[-10%] h-[520px] w-[820px] -translate-x-1/2 rounded-full bg-emerald-500/10 blur-[140px]" />
      </div>

      {/* NAV */}
      <header className="sticky top-0 z-40 border-b border-white/5 bg-neutral-950/70 backdrop-blur-xl">
        <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <a href="#top" className="flex items-center gap-2.5">
            <Logo className="h-8 w-8 text-emerald-400" />
            <span className="font-heading text-lg tracking-tight text-neutral-50">Mesh Pilot</span>
          </a>
          <div className="hidden items-center gap-8 text-sm text-neutral-400 md:flex">
            <a href="#how" className="transition-colors hover:text-neutral-100">How it works</a>
            <a href="#capabilities" className="transition-colors hover:text-neutral-100">Capabilities</a>
            <a href="#brain" className="transition-colors hover:text-neutral-100">The brain</a>
          </div>
          <a href="#waitlist" className="rounded-lg bg-emerald-400 px-4 py-2 text-sm font-semibold text-neutral-950 transition-transform hover:-translate-y-px active:translate-y-0">
            Join waitlist
          </a>
        </nav>
      </header>

      <div id="top" className="relative z-10">
        {/* HERO */}
        <section className="mx-auto grid max-w-6xl items-center gap-14 px-6 pb-20 pt-16 md:grid-cols-2 md:pt-24">
          <div>
            <Reveal>
              <Badge variant="outline" className="mb-6 gap-2 border-white/10 bg-white/[0.03] text-neutral-300">
                <LiveDot /> Runs 24/7 · fully AI-native
              </Badge>
            </Reveal>
            <Reveal delay={0.05}>
              <h1 className="font-heading text-4xl leading-[1.05] tracking-tight text-neutral-50 md:text-6xl">
                A digital marketing agent that never clocks out.
              </h1>
            </Reveal>
            <Reveal delay={0.1}>
              <p className="mt-5 max-w-md text-lg leading-relaxed text-neutral-400">
                Mesh Pilot creates, decides, and ships marketing for your brands around the clock. One autonomous agent, not another dashboard.
              </p>
            </Reveal>
            <Reveal delay={0.15}>
              <div className="mt-8 flex flex-wrap items-center gap-4">
                <a href="#waitlist" className="group inline-flex items-center gap-2 rounded-lg bg-emerald-400 px-5 py-3 text-sm font-semibold text-neutral-950 transition-transform hover:-translate-y-px active:translate-y-0">
                  Join the waitlist
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" strokeWidth={2} />
                </a>
                <a href="#how" className="text-sm font-medium text-neutral-300 transition-colors hover:text-neutral-100">
                  See how it works
                </a>
              </div>
            </Reveal>
          </div>

          <Reveal delay={0.15} className="relative">
            <div className="rounded-3xl border border-white/10 bg-white/[0.02] p-4">
              <div className="overflow-hidden rounded-2xl">
                <IntegrationHub />
              </div>
            </div>
          </Reveal>
        </section>

        {/* POSITIONING STRIP */}
        <section className="border-y border-white/5 bg-white/[0.015]">
          <div className="mx-auto grid max-w-6xl grid-cols-2 gap-y-8 px-6 py-12 md:grid-cols-4">
            {[
              ["24/7", "always on, never idle"],
              ["Autonomous", "acts, then reports"],
              ["Multi-brand", "each with its own keys"],
              ["AI-native", "built as an agent, not bolted on"],
            ].map(([big, small], i) => (
              <Reveal key={big} delay={i * 0.05}>
                <div>
                  <div className="font-heading text-3xl tracking-tight text-neutral-50">{big}</div>
                  <div className="mt-1 text-sm text-neutral-500">{small}</div>
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        {/* HOW IT WORKS */}
        <section id="how" className="scroll-mt-24 mx-auto max-w-6xl px-6 py-24">
          <div className="grid gap-12 md:grid-cols-2 md:items-center">
            <div>
              <Reveal>
                <h2 className="font-heading text-3xl tracking-tight text-neutral-50 md:text-4xl">
                  It runs a loop, not a checklist.
                </h2>
              </Reveal>
              <Reveal delay={0.05}>
                <p className="mt-5 max-w-md text-neutral-400">
                  Every cycle, the agent recalls what it knows about your brand, decides the next move through a policy gate, creates the work, ships the safe ones, and records what happened. Then it learns and goes again.
                </p>
              </Reveal>
              <Reveal delay={0.1}>
                <p className="mt-4 max-w-md text-sm text-neutral-500">
                  Publishing stays off until you turn it on. The gate refuses anything you have not allowed.
                </p>
              </Reveal>
            </div>
            <Reveal delay={0.1}>
              <AutonomousLoop />
            </Reveal>
          </div>
        </section>

        {/* CAPABILITIES */}
        <section id="capabilities" className="scroll-mt-24 mx-auto max-w-6xl px-6 py-8">
          <Reveal>
            <h2 className="max-w-2xl font-heading text-3xl tracking-tight text-neutral-50 md:text-4xl">
              One agent for the whole content pipeline.
            </h2>
          </Reveal>
          <div className="mt-12 grid gap-4 md:grid-cols-2">
            {CAPABILITIES.map((c, i) => (
              <Reveal key={c.title} delay={i * 0.05}>
                <div className="group h-full rounded-2xl border border-white/10 bg-white/[0.02] p-7 transition-colors hover:border-emerald-400/30">
                  <c.icon className="h-6 w-6 text-emerald-400" strokeWidth={1.75} />
                  <h3 className="mt-5 text-lg font-medium text-neutral-100">{c.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-neutral-400">{c.body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        {/* STACK MARQUEE */}
        <section className="mx-auto max-w-6xl px-6 py-24">
          <Reveal>
            <div className="mb-10 flex items-center gap-3 text-sm text-neutral-500">
              <Sparkles className="h-4 w-4 text-emerald-400" strokeWidth={1.75} />
              Plugs into the tools you already run
            </div>
          </Reveal>
          <Reveal delay={0.05}>
            <div className="overflow-hidden rounded-3xl border border-white/10 bg-white/[0.02] py-8">
              <StackMarquee />
            </div>
          </Reveal>
        </section>

        {/* THE BRAIN */}
        <section id="brain" className="scroll-mt-24 border-y border-white/5 bg-white/[0.015]">
          <div className="mx-auto max-w-6xl px-6 py-24">
            <Reveal>
              <h2 className="max-w-2xl font-heading text-3xl tracking-tight text-neutral-50 md:text-4xl">
                What makes it an agent, not a script.
              </h2>
            </Reveal>
            <div className="mt-12 grid gap-px overflow-hidden rounded-2xl border border-white/10 bg-white/10 md:grid-cols-3">
              {BRAIN.map((b, i) => (
                <Reveal key={b.title} delay={i * 0.06} className="bg-neutral-950">
                  <div className="h-full p-8">
                    <b.icon className="h-6 w-6 text-emerald-400" strokeWidth={1.75} />
                    <h3 className="mt-5 text-lg font-medium text-neutral-100">{b.title}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-neutral-400">{b.body}</p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* CTA / WAITLIST */}
        <section id="waitlist" className="scroll-mt-24 mx-auto max-w-3xl px-6 py-28 text-center">
          <Reveal>
            <h2 className="font-heading text-3xl tracking-tight text-neutral-50 md:text-5xl">
              Give your marketing an agent that works while you sleep.
            </h2>
          </Reveal>
          <Reveal delay={0.05}>
            <p className="mx-auto mt-5 max-w-md text-neutral-400">
              Join the waitlist for early access. No spam, just the launch.
            </p>
          </Reveal>
          <Reveal delay={0.1}>
            <div className="mx-auto mt-9 max-w-md">
              <WaitlistForm />
            </div>
          </Reveal>
        </section>

        {/* FOOTER */}
        <footer className="border-t border-white/5">
          <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 py-10 text-sm text-neutral-500 sm:flex-row">
            <div className="flex items-center gap-2.5">
              <Logo className="h-7 w-7 text-neutral-400" nodes={false} />
              <span className="text-neutral-300">Mesh Pilot</span>
            </div>
            <Separator className="bg-white/10 sm:hidden" />
            <div className="flex items-center gap-6">
              <a href="/privacy" className="transition-colors hover:text-neutral-200">Privacy</a>
              <a href="/terms" className="transition-colors hover:text-neutral-200">Terms</a>
              <span className="text-neutral-600">© 2026</span>
            </div>
          </div>
        </footer>
      </div>

      <Toaster
        toastOptions={{
          style: { background: "rgb(10 10 10)", color: "white", border: "1px solid rgb(38 38 38)" },
          className: "rounded-xl",
          duration: 5000,
        }}
      />
    </main>
  );
}
