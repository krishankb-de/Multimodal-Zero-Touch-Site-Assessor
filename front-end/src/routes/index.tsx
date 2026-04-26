import { createFileRoute, Link } from "@tanstack/react-router";
import { motion } from "framer-motion";
import {
  ArrowRight,
  Battery,
  CloudSun,
  FileText,
  Home,
  Leaf,
  Sparkles,
  Sun,
  ThermometerSun,
  Upload,
  Wind,
  Zap,
} from "lucide-react";
import { SiteFooter, SiteHeader } from "@/components/site-header";
import { EarthSunHero } from "@/components/earth-sun-hero";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Helio — Engineering-grade solar in minutes" },
      {
        name: "description",
        content:
          "Upload three files. Get a complete solar, battery, and heat pump proposal — designed by AI, signed off by a real installer.",
      },
    ],
  }),
  component: Index,
});

const inputs = [
  {
    icon: Home,
    title: "A roof video",
    detail: "30 seconds walking around your house.",
    tag: "MP4 · MOV",
    accent: "from-ember to-sun",
  },
  {
    icon: Zap,
    title: "Your fuse box",
    detail: "One photo of the electrical panel.",
    tag: "JPG · PNG",
    accent: "from-sun to-leaf",
  },
  {
    icon: FileText,
    title: "Last utility bill",
    detail: "So we know what you actually use.",
    tag: "PDF",
    accent: "from-leaf to-sky",
  },
];

const outputs = [
  {
    icon: Sun,
    title: "Solar PV design",
    desc: "Panel count, string config, exact placement on your roof geometry.",
  },
  {
    icon: Battery,
    title: "Battery sizing",
    desc: "Capacity tuned to your usage profile and tariff.",
  },
  {
    icon: ThermometerSun,
    title: "Heat pump",
    desc: "DIN EN 12831 heat-load calc, with the right kW for your envelope.",
  },
  {
    icon: CloudSun,
    title: "Local weather",
    desc: "5 years of historical irradiance for your exact coordinates.",
  },
];

const workflow = [
  {
    n: "01",
    t: "Upload",
    d: "Drop in three files. Add your address for hyper-local weather.",
    icon: Upload,
    color: "ember",
  },
  {
    n: "02",
    t: "Assess",
    d: "Eight specialized agents run in parallel. Watch every step live.",
    icon: Sparkles,
    color: "sun",
  },
  {
    n: "03",
    t: "Proposal",
    d: "Full engineering pack. Reviewed and signed by a real installer.",
    icon: Leaf,
    color: "leaf",
  },
];

function Index() {
  return (
    <div className="min-h-screen text-foreground">
      <SiteHeader />

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 grain" />
        <div className="pointer-events-none absolute inset-0 horizon-grid opacity-40" />
        <div
          className="pointer-events-none absolute -right-40 -top-40 h-[560px] w-[560px] rounded-full opacity-50 blur-3xl animate-drift"
          style={{ background: "radial-gradient(circle, var(--sun) 0%, transparent 70%)" }}
        />
        <div
          className="pointer-events-none absolute -left-32 top-1/2 h-[460px] w-[460px] rounded-full opacity-40 blur-3xl animate-drift"
          style={{
            background: "radial-gradient(circle, var(--leaf) 0%, transparent 70%)",
            animationDelay: "-6s",
          }}
        />
        <div className="mx-auto grid max-w-7xl items-center gap-12 px-6 pt-20 pb-28 lg:grid-cols-[1.2fr_1fr] lg:gap-8 lg:px-10 lg:pt-28 lg:pb-36">
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            className="max-w-2xl"
          >
            <div className="inline-flex items-center gap-2 rounded-full border border-border/60 glass px-3 py-1 text-xs text-muted-foreground">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-leaf opacity-70" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-leaf" />
              </span>
              <span className="font-mono uppercase tracking-wider">
                Renewable · Zero-touch
              </span>
            </div>

            <h1 className="mt-6 font-serif text-5xl leading-[1] tracking-tight md:text-6xl lg:text-7xl">
              Power your home
              <br />
              <span className="italic text-gradient-radiant">from the sun.</span>
              <br />
              No site visit.
            </h1>

            <p className="mt-8 max-w-xl text-lg leading-relaxed text-muted-foreground">
              A guided 3-step workflow turns a video, a photo, and a bill into a
              full solar, battery, and heat pump engineering proposal —
              designed by AI, signed by a human installer.
            </p>

            <div className="mt-10 flex flex-wrap items-center gap-4">
              <Link
                to="/upload"
                className="group relative inline-flex items-center gap-2 overflow-hidden rounded-full gradient-radiant px-7 py-4 text-sm font-medium text-primary-foreground glow-magenta transition-transform hover:scale-[1.02]"
              >
                Begin workflow
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </Link>
              <Link
                to="/how-it-works"
                className="inline-flex items-center gap-2 rounded-full border border-border/60 glass px-6 py-3.5 text-sm font-medium text-foreground transition-colors hover:bg-surface-elevated"
              >
                See the architecture
              </Link>
            </div>

            <div className="mt-14 flex flex-wrap items-center gap-x-6 gap-y-3 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <Sun className="h-3.5 w-3.5 text-sun" /> Solar
              </span>
              <span>·</span>
              <span className="flex items-center gap-1.5">
                <Leaf className="h-3.5 w-3.5 text-leaf" /> Carbon-free
              </span>
              <span>·</span>
              <span className="flex items-center gap-1.5">
                <Wind className="h-3.5 w-3.5 text-sky" /> Local weather
              </span>
              <span>·</span>
              <span>Human sign-off</span>
            </div>
          </motion.div>

          <div className="relative flex items-center justify-center">
            <EarthSunHero />
          </div>
        </div>
      </section>

      {/* Workflow — the spine of the experience */}
      <section className="border-t border-border/40">
        <div className="mx-auto max-w-7xl px-6 py-24 lg:px-10">
          <div className="flex items-end justify-between gap-8">
            <div>
              <p className="font-mono text-xs uppercase tracking-[0.2em] text-sun">
                The workflow
              </p>
              <h2 className="mt-3 max-w-2xl font-serif text-4xl leading-tight md:text-5xl">
                Three steps. Linear. <span className="italic text-gradient-radiant">Visible.</span>
              </h2>
            </div>
          </div>

          <div className="mt-14 grid gap-6 md:grid-cols-3">
            {workflow.map((w, i) => (
              <motion.div
                key={w.n}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-80px" }}
                transition={{ duration: 0.5, delay: i * 0.1 }}
                className="group relative overflow-hidden rounded-3xl glass p-8 transition-all hover:-translate-y-1"
              >
                <div
                  className="pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full opacity-30 blur-2xl transition-opacity group-hover:opacity-60"
                  style={{
                    background: `radial-gradient(circle, var(--${w.color}) 0%, transparent 70%)`,
                  }}
                />
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                    Step {w.n}
                  </span>
                  <div
                    className="flex h-11 w-11 items-center justify-center rounded-xl"
                    style={{
                      background: `linear-gradient(135deg, var(--${w.color}) 0%, transparent 120%)`,
                    }}
                  >
                    <w.icon className="h-5 w-5 text-foreground" strokeWidth={1.75} />
                  </div>
                </div>
                <h3 className="mt-10 font-serif text-3xl">{w.t}</h3>
                <p className="mt-3 text-sm text-muted-foreground">{w.d}</p>
              </motion.div>
            ))}
          </div>

          <div className="mt-10 flex flex-wrap items-center gap-4">
            <Link
              to="/upload"
              className="group inline-flex items-center gap-2 rounded-full gradient-radiant px-6 py-3.5 text-sm font-medium text-primary-foreground glow-magenta transition-transform hover:scale-[1.02]"
            >
              Begin Step 1 — Upload
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </Link>
          </div>
        </div>
      </section>

      {/* Inputs */}
      <section className="border-t border-border/40">
        <div className="mx-auto max-w-7xl px-6 py-24 lg:px-10">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-sky">
            What we need
          </p>
          <h2 className="mt-3 max-w-2xl font-serif text-4xl leading-tight md:text-5xl">
            Three files. <span className="italic text-gradient-radiant">That's the homework.</span>
          </h2>

          <div className="mt-14 grid gap-6 md:grid-cols-3">
            {inputs.map((input, i) => (
              <motion.div
                key={input.title}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-80px" }}
                transition={{ duration: 0.5, delay: i * 0.08 }}
                className="group relative overflow-hidden rounded-3xl glass p-8 transition-all hover:-translate-y-1"
              >
                <div className="flex items-start justify-between">
                  <div
                    className={`flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br ${input.accent} text-primary-foreground`}
                  >
                    <input.icon className="h-5 w-5" strokeWidth={2} />
                  </div>
                  <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    {input.tag}
                  </span>
                </div>
                <h3 className="mt-8 font-serif text-2xl">{input.title}</h3>
                <p className="mt-2 text-sm text-muted-foreground">{input.detail}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Outputs */}
      <section className="border-t border-border/40">
        <div className="mx-auto max-w-7xl px-6 py-24 lg:px-10">
          <div className="grid gap-16 lg:grid-cols-[1fr_2fr]">
            <div>
              <p className="font-mono text-xs uppercase tracking-[0.2em] text-leaf">
                What you get
              </p>
              <h2 className="mt-3 font-serif text-4xl leading-[1.05] md:text-5xl">
                A proposal
                <br />
                an engineer
                <br />
                <span className="italic text-gradient-radiant">would sign.</span>
              </h2>
              <p className="mt-6 max-w-sm text-sm text-muted-foreground">
                Not a marketing PDF. A real design — kWp, string voltages, COP,
                cable sizes, payback period, single-line diagram.
              </p>
            </div>

            <div className="grid gap-px overflow-hidden rounded-3xl border border-border/60 bg-border/40 sm:grid-cols-2">
              {outputs.map((o) => (
                <div
                  key={o.title}
                  className="group relative overflow-hidden bg-surface p-8 transition-colors hover:bg-surface-elevated"
                >
                  <o.icon
                    className="h-6 w-6 text-sun transition-transform group-hover:scale-110"
                    strokeWidth={1.75}
                  />
                  <h3 className="mt-6 font-serif text-xl">{o.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    {o.desc}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}
