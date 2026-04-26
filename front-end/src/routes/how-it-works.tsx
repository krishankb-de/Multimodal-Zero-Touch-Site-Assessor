import { createFileRoute, Link } from "@tanstack/react-router";
import { motion } from "framer-motion";
import { ArrowRight, Shield } from "lucide-react";
import { SiteFooter, SiteHeader } from "@/components/site-header";

export const Route = createFileRoute("/how-it-works")({
  head: () => ({
    meta: [
      { title: "How it works — Helio" },
      {
        name: "description",
        content:
          "Eight specialized AI agents, three safety gates, and a human installer. Here's how Helio designs your solar system.",
      },
      { property: "og:title", content: "How Helio works" },
      {
        property: "og:description",
        content: "Eight AI agents, three safety gates, one human installer.",
      },
    ],
  }),
  component: HowItWorks,
});

const agents = [
  { n: "Ingestion", d: "Multimodal Gemini parses video frames, panel photo, bill PDF." },
  { n: "Reconstruction", d: "4-tier 3D mesh: SfM → Pioneer SLM → depth → 2D fallback." },
  { n: "Structural", d: "Bin-packs panels onto roof faces. Sutherland–Hodgman clipping." },
  { n: "Thermodynamic", d: "DIN EN 12831 heat-load calc, dimension-aware." },
  { n: "Electrical", d: "Reads breaker inventory, computes upgrade need." },
  { n: "Behavioral", d: "Occupancy profile, battery sizing, TOU arbitrage." },
  { n: "Synthesis", d: "Pioneer SLM pricing on Reonic historical projects." },
  { n: "Safety", d: "Intercepts every handoff. Halts on violation. No exceptions." },
];

function HowItWorks() {
  return (
    <div className="min-h-screen text-foreground">
      <SiteHeader />

      <section className="relative mx-auto max-w-4xl px-6 py-20 lg:px-10 lg:py-28">
        <div
          className="pointer-events-none absolute right-0 top-20 h-96 w-96 rounded-full opacity-30 blur-3xl animate-drift"
          style={{ background: "radial-gradient(circle, var(--violet) 0%, transparent 70%)" }}
        />
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="relative"
        >
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-magenta">
            Architecture
          </p>
          <h1 className="mt-3 font-serif text-5xl leading-[1.02] md:text-7xl">
            Eight agents.
            <br />
            <span className="italic text-gradient-radiant">Three gates.</span>
            <br />
            One human.
          </h1>
          <p className="mt-6 max-w-2xl text-lg text-muted-foreground">
            Every step in the pipeline is small, specialized, and inspected. The
            Safety Agent sits between every handoff — and a real installer signs
            off before anything reaches you.
          </p>
        </motion.div>

        <div className="relative mt-16 space-y-px overflow-hidden rounded-3xl border border-border/60 bg-border/40">
          {agents.map((a, i) => (
            <motion.div
              key={a.n}
              initial={{ opacity: 0, x: -12 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.4, delay: i * 0.04 }}
              className="group relative flex items-center gap-6 bg-surface p-6 transition-all hover:bg-surface-elevated"
            >
              <span className="font-mono text-xs text-magenta">
                0{i + 1}
              </span>
              <div className="flex-1">
                <h3 className="font-serif text-2xl">{a.n}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{a.d}</p>
              </div>
              <span className="hidden h-1.5 w-1.5 rounded-full bg-magenta opacity-0 transition-opacity group-hover:opacity-100 sm:block" />
            </motion.div>
          ))}
        </div>

        <div className="relative mt-12 flex items-start gap-4 overflow-hidden rounded-3xl ring-radiant p-6">
          <div
            className="pointer-events-none absolute -right-20 -top-20 h-56 w-56 rounded-full opacity-30 blur-3xl"
            style={{ background: "radial-gradient(circle, var(--magenta) 0%, transparent 70%)" }}
          />
          <Shield className="relative mt-0.5 h-5 w-5 flex-none text-magenta" strokeWidth={1.75} />
          <div>
            <h4 className="font-medium">Hard guardrails, in code</h4>
            <p className="mt-1 text-sm text-muted-foreground">
              DC string voltage ≤ 1000 V · roof density ≤ 0.22 kWp/m² · COP between
              1.0 and 7.0 · Gemini confidence ≥ 0.6 · human sign-off mandatory.
              Violations halt the pipeline.
            </p>
          </div>
        </div>

        <div className="mt-12">
          <Link
            to="/upload"
            className="group inline-flex items-center gap-2 rounded-full gradient-radiant px-7 py-4 text-sm font-medium text-primary-foreground glow-magenta transition-transform hover:scale-[1.02]"
          >
            Begin the workflow
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}
