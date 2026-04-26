import { createFileRoute } from "@tanstack/react-router";
import { motion } from "framer-motion";
import {
  Battery,
  Check,
  CloudSun,
  Download,
  Loader2,
  MessageSquare,
  Sun,
  ThermometerSun,
  TrendingUp,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { SiteFooter, SiteHeader } from "@/components/site-header";
import { WorkflowStepper } from "@/components/workflow-stepper";
import {
  type FinalProposal,
  type WeatherProfile,
  artifactUrl,
  fetchProposal,
  fetchWeather,
  signoffProposal,
} from "@/lib/api";

export const Route = createFileRoute("/proposal")({
  validateSearch: (search: Record<string, unknown>) => ({
    runId: typeof search.runId === "string" ? search.runId : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Your proposal — Helio" },
      { name: "description", content: "Engineering-grade solar and heat pump proposal." },
    ],
  }),
  component: Proposal,
});

const SEASONAL = [0.25, 0.38, 0.62, 0.82, 0.95, 1.0, 0.98, 0.88, 0.7, 0.45, 0.28, 0.2];
const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function fmt(n: number, decimals = 0) {
  return n.toFixed(decimals).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

function heatPumpLabel(type: string) {
  return type === "air_source" ? "Air-source" : type === "ground_source" ? "Ground-source" : "Water-source";
}

function useProposal(runId: string | undefined) {
  const [data, setData] = useState<FinalProposal | null>(null);
  const [loading, setLoading] = useState(!!runId);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    setLoading(true);
    fetchProposal(runId)
      .then((p) => { if (!cancelled) { setData(p); setLoading(false); } })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load proposal.");
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [runId]);

  return { data, loading, error, setData };
}

function useWeather(runId: string | undefined) {
  const [weather, setWeather] = useState<WeatherProfile | null>(null);
  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    fetchWeather(runId)
      .then((w) => { if (!cancelled) setWeather(w); })
      .catch(() => { /* optional — keep null */ });
    return () => { cancelled = true; };
  }, [runId]);
  return weather;
}

// ── 3D Roof Viewer ────────────────────────────────────────────────────────────

function RoofViewer({ runId, panelCount, inverterType }: {
  runId: string | undefined;
  panelCount: number | undefined;
  inverterType: string | undefined;
}) {
  useEffect(() => {
    import("@google/model-viewer");
  }, []);

  const [meshFailed, setMeshFailed] = useState(false);
  const meshUri = runId ? artifactUrl(runId, "mesh.glb") : null;
  const showModel = meshUri && !meshFailed;

  return (
    <div className="mt-8 flex aspect-[16/9] items-center justify-center overflow-hidden rounded-2xl border border-border/40 bg-background/40">
      {showModel ? (
        <model-viewer
          src={meshUri}
          alt="3D roof reconstruction"
          camera-controls=""
          auto-rotate=""
          shadow-intensity="1"
          exposure="0.8"
          style={{ width: "100%", height: "100%" }}
          onError={() => setMeshFailed(true)}
        />
      ) : (
        <div className="relative flex flex-col items-center justify-center gap-4">
          <svg viewBox="0 0 200 140" className="h-40 w-auto">
            <defs>
              <linearGradient id="roofL" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="oklch(0.84 0.18 78)" />
                <stop offset="1" stopColor="oklch(0.72 0.27 340)" />
              </linearGradient>
            </defs>
            <polygon points="100,10 180,50 100,90 20,50" fill="url(#roofL)" stroke="oklch(0.97 0.01 280)" strokeWidth="0.5" opacity="0.9" />
            <polygon points="20,50 100,90 100,130 20,90" fill="oklch(0.32 0.12 290)" opacity="0.8" />
            <polygon points="180,50 100,90 100,130 180,90" fill="oklch(0.22 0.08 280)" opacity="0.8" />
            {[0, 1, 2].map((r) =>
              [0, 1, 2, 3].map((c) => (
                <rect key={`${r}-${c}`} x={45 + c * 14} y={28 + r * 12} width="11" height="9"
                  fill="oklch(0.82 0.16 200)" stroke="oklch(0.97 0.01 280)" strokeWidth="0.3"
                  transform={`skewX(-30) translate(${15 + r * 8}, 0)`} opacity="0.85" />
              ))
            )}
          </svg>
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            {panelCount ? `${panelCount} panels · ${inverterType?.replace("_", " ")}` : "21 panels · south-east facing · 32° tilt"}
          </p>
        </div>
      )}
    </div>
  );
}

// ── Signoff Panel ─────────────────────────────────────────────────────────────

function SignoffPanel({ runId, initialStatus, onUpdate }: {
  runId: string | undefined;
  initialStatus: string;
  onUpdate: (updated: FinalProposal) => void;
}) {
  const [status, setStatus] = useState(initialStatus);
  const [showNotes, setShowNotes] = useState(false);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(action: "approve" | "reject") {
    if (!runId) return;
    setBusy(true);
    setErr(null);
    try {
      const updated = await signoffProposal(runId, action, notes || undefined);
      setStatus(updated.human_signoff.status);
      onUpdate(updated);
      setShowNotes(false);
      setNotes("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Sign-off failed.");
    } finally {
      setBusy(false);
    }
  }

  if (status === "approved") {
    return (
      <div className="flex items-center gap-3 rounded-full bg-emerald-500/15 px-5 py-3 text-sm text-emerald-400">
        <Check className="h-4 w-4" strokeWidth={2.5} /> Approved by installer
      </div>
    );
  }

  if (status === "rejected") {
    return (
      <div className="flex items-center gap-3 rounded-full bg-destructive/15 px-5 py-3 text-sm text-destructive">
        <X className="h-4 w-4" /> Rejected — revision requested
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {showNotes && (
        <div className="flex flex-col gap-2">
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Describe what needs to change…"
            rows={3}
            className="w-full rounded-xl border border-border bg-background/50 px-4 py-3 text-sm placeholder:text-muted-foreground/60 focus:border-magenta focus:outline-none focus:ring-2 focus:ring-magenta/30"
          />
          <div className="flex gap-2">
            <button
              onClick={() => submit("reject")}
              disabled={busy || !notes.trim()}
              className="inline-flex items-center gap-2 rounded-full bg-destructive px-5 py-2.5 text-sm font-medium text-white transition-opacity enabled:hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
              Send rejection
            </button>
            <button onClick={() => { setShowNotes(false); setNotes(""); }} className="rounded-full glass px-5 py-2.5 text-sm font-medium">
              Cancel
            </button>
          </div>
        </div>
      )}
      {!showNotes && (
        <div className="flex flex-wrap gap-3">
          <button
            onClick={() => setShowNotes(true)}
            className="inline-flex items-center gap-2 rounded-full glass px-5 py-2.5 text-sm font-medium transition-colors hover:bg-surface-elevated"
          >
            <MessageSquare className="h-4 w-4" /> Request changes
          </button>
          <button
            onClick={() => submit("approve")}
            disabled={busy}
            className="inline-flex items-center gap-2 rounded-full gradient-radiant px-5 py-2.5 text-sm font-medium text-primary-foreground glow-magenta transition-transform enabled:hover:scale-[1.02] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            Approve
          </button>
        </div>
      )}
      {err && <p className="text-sm text-destructive">{err}</p>}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

function Proposal() {
  const { runId } = Route.useSearch();
  const { data, loading, error, setData } = useProposal(runId);
  const weather = useWeather(runId);
  const printRef = useRef<HTMLDivElement>(null);

  function exportPdf() {
    window.print();
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-foreground">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-10 w-10 animate-spin text-magenta" />
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            Loading proposal…
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center px-6 text-foreground">
        <div className="text-center">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-destructive">Error</p>
          <h1 className="mt-3 font-serif text-4xl">Could not load proposal.</h1>
          <p className="mt-2 text-sm text-muted-foreground">{error}</p>
        </div>
      </div>
    );
  }

  const pv = data?.system_design.pv;
  const battery = data?.system_design.battery;
  const hp = data?.system_design.heat_pump;
  const fin = data?.financial_summary;
  const comp = data?.compliance;

  const panelUpgradeLabel = comp?.electrical_upgrades.length
    ? comp.electrical_upgrades[0]
    : "Not required";

  const system = [
    {
      icon: Sun,
      label: "Solar PV",
      value: pv ? `${fmt(pv.total_kwp, 1)} kWp` : "8.4 kWp",
      sub: pv ? `${pv.panel_count} panels · ${pv.inverter_type.replace("_", " ")}` : "21 panels · 2 strings",
    },
    {
      icon: Battery,
      label: "Battery",
      value: battery ? `${fmt(battery.capacity_kwh, 0)} kWh` : "10 kWh",
      sub: battery?.model ?? "Lithium iron phosphate",
    },
    {
      icon: ThermometerSun,
      label: "Heat pump",
      value: hp ? `${fmt(hp.capacity_kw, 0)} kW` : "9 kW",
      sub: hp ? `${heatPumpLabel(hp.type)} · COP ${hp.cop?.toFixed(1) ?? "—"}` : "Air-source · COP 4.2",
    },
    {
      icon: Zap,
      label: "Panel upgrade",
      value: panelUpgradeLabel,
      sub: comp?.electrical_upgrades.length ? "Upgrade required" : "Existing board sufficient",
    },
  ];

  const finance = [
    { label: "Total system cost", value: fin ? `€ ${fmt(fin.total_cost_eur)}` : "€ 28,400" },
    { label: "Annual savings", value: fin ? `€ ${fmt(fin.annual_savings_eur)}` : "€ 3,180" },
    { label: "Payback period", value: fin ? `${fin.payback_years.toFixed(1)} yrs` : "8.9 yrs" },
    {
      label: "20-year net benefit",
      value: fin ? `€ ${fmt(fin.annual_savings_eur * 20 - fin.total_cost_eur)}` : "€ 38,200",
    },
  ];

  const annualYield = pv?.annual_yield_kwh ?? 8400;
  const rawFactors = weather
    ? weather.monthly_sunshine_hours
    : SEASONAL.map((v) => v * 10);
  const factorMax = Math.max(...rawFactors);
  const months = rawFactors.map((h, i) => ({
    m: MONTH_LABELS[i],
    kwh: Math.round((h / rawFactors.reduce((a, b) => a + b, 0)) * annualYield),
    v: factorMax > 0 ? h / factorMax : 0,
  }));

  const runId2 = data?.metadata.pipeline_run_id ?? runId;
  const signoffStatus = data?.human_signoff.status ?? "pending";

  return (
    <div className="min-h-screen text-foreground" ref={printRef}>
      <SiteHeader />

      <div className="pt-10 print:hidden">
        <WorkflowStepper current={3} />
      </div>

      <section className="mx-auto max-w-7xl px-6 py-12 lg:px-10 lg:py-16">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="flex flex-wrap items-end justify-between gap-6"
        >
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-magenta">
              Step 03 — Proposal
            </p>
            <h1 className="mt-3 font-serif text-5xl leading-[1.05] md:text-6xl">
              Your <span className="italic text-gradient-radiant">proposal.</span>
            </h1>
            <div className="mt-3 flex flex-wrap items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-sun/15 px-2.5 py-1 text-sun">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-sun" />
                All safety gates passed
              </span>
              {runId2 && (
                <span className="rounded-full bg-surface px-2.5 py-1">
                  run {runId2.slice(0, 8)}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={exportPdf}
            className="print:hidden inline-flex items-center gap-2 rounded-full glass px-5 py-2.5 text-sm font-medium transition-colors hover:bg-surface-elevated"
          >
            <Download className="h-4 w-4" /> Export PDF
          </button>
        </motion.div>

        {/* System grid */}
        <div className="mt-10 grid gap-px overflow-hidden rounded-3xl border border-border/60 bg-border/40 sm:grid-cols-2 lg:grid-cols-4">
          {system.map((s, i) => (
            <motion.div
              key={s.label}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: i * 0.05 }}
              className="group relative overflow-hidden bg-surface p-6 transition-colors hover:bg-surface-elevated"
            >
              <div className="flex items-center gap-2 text-muted-foreground">
                <s.icon className="h-4 w-4" strokeWidth={1.75} />
                <span className="font-mono text-[10px] uppercase tracking-wider">{s.label}</span>
              </div>
              <p className="mt-3 font-serif text-4xl text-gradient-radiant">{s.value}</p>
              <p className="mt-1 text-xs text-muted-foreground">{s.sub}</p>
            </motion.div>
          ))}
        </div>

        {/* 3D viewer + financials */}
        <div className="mt-6 grid gap-6 lg:grid-cols-3">
          <div className="relative overflow-hidden rounded-3xl glass p-8 lg:col-span-2">
            <div
              className="pointer-events-none absolute -right-20 -top-20 h-72 w-72 rounded-full opacity-50 blur-3xl animate-drift"
              style={{ background: "radial-gradient(circle, var(--magenta) 0%, transparent 70%)" }}
            />
            <div
              className="pointer-events-none absolute -bottom-20 -left-10 h-56 w-56 rounded-full opacity-40 blur-3xl animate-drift"
              style={{ background: "radial-gradient(circle, var(--cyan) 0%, transparent 70%)", animationDelay: "-6s" }}
            />
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-cyan">
              3D roof reconstruction
            </p>
            <h2 className="mt-2 font-serif text-4xl">
              Your roof, <span className="italic text-gradient-radiant">modeled.</span>
            </h2>
            <RoofViewer
              runId={runId2}
              panelCount={pv?.panel_count}
              inverterType={pv?.inverter_type}
            />
          </div>

          <div className="rounded-3xl glass p-8">
            <div className="flex items-center gap-2 text-muted-foreground">
              <TrendingUp className="h-4 w-4 text-lime" />
              <span className="font-mono text-[10px] uppercase tracking-wider">Financials</span>
            </div>
            <dl className="mt-6 divide-y divide-border/40">
              {finance.map((f) => (
                <div key={f.label} className="flex items-baseline justify-between py-4">
                  <dt className="text-sm text-muted-foreground">{f.label}</dt>
                  <dd className="font-serif text-2xl">{f.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>

        {/* Monthly yield + weather */}
        <div className="mt-6 grid gap-6 lg:grid-cols-3">
          <div className="rounded-3xl glass p-8 lg:col-span-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Sun className="h-4 w-4 text-sun" />
                <span className="font-mono text-[10px] uppercase tracking-wider">
                  Estimated monthly yield
                </span>
              </div>
              <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                kWh · {fmt(annualYield)} / yr
              </span>
            </div>
            <div className="mt-8 flex h-40 items-end gap-2">
              {months.map((m, i) => (
                <motion.div
                  key={m.m}
                  initial={{ scaleY: 0, originY: 1 }}
                  whileInView={{ scaleY: 1 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.6, delay: i * 0.04, ease: [0.22, 1, 0.36, 1] }}
                  className="flex flex-1 flex-col items-center justify-end gap-2"
                >
                  <div
                    className="w-full rounded-t-md bg-gradient-to-t from-magenta via-violet to-sun"
                    style={{ height: `${m.v * 100}%` }}
                  />
                  <span className="font-mono text-[10px] text-muted-foreground">{m.m}</span>
                </motion.div>
              ))}
            </div>
          </div>

          <div className="rounded-3xl glass p-8">
            <div className="flex items-center gap-2 text-muted-foreground">
              <CloudSun className="h-4 w-4 text-cyan" />
              <span className="font-mono text-[10px] uppercase tracking-wider">Local climate</span>
            </div>
            <p className="mt-6 font-serif text-4xl text-gradient-radiant">
              {weather ? `${Math.round(weather.annual_irradiance_kwh_m2)} kWh/m²` : "960 kWh/m²"}
            </p>
            <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              Annual irradiance ·{" "}
              {weather
                ? `${weather.date_range_start.slice(0, 4)}–${weather.date_range_end.slice(0, 4)}`
                : "5yr avg"}
            </p>
            <div className="mt-6 space-y-3 text-sm">
              <Row label="Sunny days / yr" value={weather ? `${weather.sunny_days_per_year}` : "142"} />
              <Row
                label="Avg cloud cover"
                value={weather
                  ? `${Math.round(weather.monthly_cloud_cover_pct.reduce((a, b) => a + b, 0) / 12)}%`
                  : "61%"}
              />
              <Row label="Best install Q" value={weather ? `Q${weather.optimal_installation_quarter}` : "Q2"} />
              <Row
                label="Design temp"
                value={weather
                  ? `${Math.min(...weather.monthly_avg_temperature_c).toFixed(1)} °C`
                  : "−12 °C"}
              />
            </div>
          </div>
        </div>

        {/* Electrical upgrades */}
        {comp && comp.electrical_upgrades.length > 0 && (
          <div className="mt-6 rounded-3xl glass p-8">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-amber-400">
              Electrical upgrades required
            </p>
            <ul className="mt-4 space-y-2">
              {comp.electrical_upgrades.map((u) => (
                <li key={u} className="flex items-start gap-3 text-sm">
                  <span className="mt-0.5 h-4 w-4 flex-none rounded-full bg-amber-400/20 text-center text-[10px] leading-4 text-amber-400">
                    !
                  </span>
                  {u}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Sign-off */}
        <div className="relative mt-6 overflow-hidden rounded-3xl ring-radiant p-8 sm:p-10">
          <div
            className="pointer-events-none absolute -right-32 -top-32 h-80 w-80 rounded-full opacity-30 blur-3xl"
            style={{ background: "radial-gradient(circle, var(--magenta) 0%, transparent 70%)" }}
          />
          <div className="relative grid gap-6 sm:grid-cols-[1fr_auto] sm:items-center">
            <div>
              <p className="font-mono text-xs uppercase tracking-[0.2em] text-gradient-radiant">
                Human sign-off required
              </p>
              <h3 className="mt-2 font-serif text-3xl">
                A licensed installer reviews this proposal before it ships.
              </h3>
              <p className="mt-2 max-w-xl text-sm text-muted-foreground">
                All safety gates passed. Final compliance check and approval is the installer's
                call — never the AI's.
              </p>
            </div>
            <SignoffPanel
              runId={runId2}
              initialStatus={signoffStatus}
              onUpdate={setData}
            />
          </div>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-border/40 pb-2 last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
