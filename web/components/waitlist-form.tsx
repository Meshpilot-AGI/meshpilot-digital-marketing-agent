"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

// The site is a static export (no server), so signups POST to the FastAPI API which persists
// them (#99). Overridable at build time via NEXT_PUBLIC_API_BASE.
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "https://api.meshpilot.app";

export function WaitlistForm() {
  const [isPending, setIsPending] = useState(false);
  const [email, setEmail] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isPending) return;
    const value = email.trim();
    if (!value) return;
    setIsPending(true);
    try {
      const res = await fetch(`${API_BASE}/waitlist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: value, source: "landing" }),
      });
      if (!res.ok) {
        const msg =
          res.status === 422
            ? "Please enter a valid email."
            : "Something went wrong — please try again.";
        toast.error(msg);
        return;
      }
      toast.success("You're on the list — we'll be in touch!");
      setEmail("");
    } catch {
      toast.error("Network error — please try again.");
    } finally {
      setIsPending(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="w-full space-y-4 mb-8">
      <div className="flex overflow-hidden rounded-xl bg-white/5 p-1 ring-1 gap-1 ring-black/10 dark:ring-white/20 focus-within:ring-2 focus-within:ring-blue-500!">
        <Input
          id="email"
          name="email"
          type="email"
          placeholder="Enter your email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full border-0 rounded-lg bg-transparent placeholder:text-muted-foreground focus:ring-0 focus:border-transparent focus-visible:border-transparent focus:outline-none active:ring-0 active:outline-none focus-visible:ring-0 focus-visible:outline-none active:border-transparent focus-visible:ring-offset-0"
        />
        <Button type="submit" className="rounded-lg" disabled={isPending}>
          {isPending ? <Loader2 className="animate-spin" /> : "Get Notified"}
        </Button>
      </div>
    </form>
  );
}
