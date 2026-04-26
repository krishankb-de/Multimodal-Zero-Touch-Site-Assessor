import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { motion } from "framer-motion";
import { AlertCircle, Check, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { SiteHeader } from "@/components/site-header";
import { WorkflowStepper } from "@/components/workflow-stepper";
import { consumePendingAssessment } from "@/lib/api";

export const Route = createFileRoute("/processing")({
  head: () => ({
    meta: [{ title: "Assessing — Helio" }],
  }),
  component: Processing,
});

const stages = [
  { t: "Ingesting media", d: "Parsing video frames, panel photo, and bill text." },
  { t: "Reconstructing roof", d: "Building 3D mesh from keyframes." },
  { t: "Engineering analysis", d: "Structural · thermal · electrical agents." },
  { t: "Synthesizing proposal", d: "Pricing components, drafting SLD." },
  { t: "Safety gates", d: "Validating every handoff before sign-off." },
];

function Processing() {
  const navigate = useNavigate();
  // which stage index is currently "active" (animates up to last stage and waits there)
  const [animStep, setAnimStep] = useState(0);
  const [allDone, setAllDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // prevent double-consuming the promise if the component re-renders
  const promiseRef = useRef<Promise<unknown> | null>(null);

  // Advance stage animation; pause at the last stage until the pipeline resolves
  useEffect(() => {
    if (allDone || error || animStep >= stages.length - 1) return;
    const t = setTimeout(() => setAnimStep((s) => s + 1), 1200);
    return () => clearTimeout(t);
  }, [animStep, allDone, error]);

  // Wire up the real pipeline promise on mount
  useEffect(() => {
    if (promiseRef.current) return; // already wired
    const pending = consumePendingAssessment();

    if (!pending) {
      // User refreshed — check if we already have a completed run in sessionStorage
      const storedRunId = sessionStorage.getItem("helio_run_id");
      if (storedRunId) {
        void navigate({ to: "/proposal", search: { runId: storedRunId } });
      } else {
        void navigate({ to: "/upload" });
      }
      return;
    }

    promiseRef.current = pending;

    pending
      .then((result) => {
        sessionStorage.setItem("helio_run_id", result.pipeline_run_id);
        if (result.mesh_uri) sessionStorage.setItem("helio_mesh_uri", result.mesh_uri);
        setAllDone(true);
        setTimeout(
          () => void navigate({ to: "/proposal", search: { runId: result.pipeline_run_id } }),
          800,
        );
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "Pipeline failed. Please try again.";
        setError(msg);
      });
  }, [navigate]);

  const progress = allDone
    ? 100
    : error
      ? ((animStep + 1) / stages.length) * 100
      : ((animStep + 0.5) / stages.length) * 100;

  if (error) {
    return (
      <div className="min-h-screen text-foreground">
        <SiteHeader />
        <div className="pt-10">
          <WorkflowStepper current={2} />
        </div>
        <section className="mx-auto max-w-3xl px-6 py-12 lg:px-10 lg:py-24">
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="flex flex-col items-center gap-6 text-center"
          >
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-destructive/10">
              <AlertCircle className="h-8 w-8 text-destructive" strokeWidth={1.75} />
            </div>
            <div>
              <p className="font-mono text-xs uppercase tracking-[0.2em] text-destructive">
                Pipeline error
              </p>
              <h1 className="mt-3 font-serif text-4xl">Something went wrong.</h1>
              <p className="mt-3 max-w-md text-sm text-muted-foreground">{error}</p>
            </div>
            <button
              onClick={() => void navigate({ to: "/upload" })}
              className="inline-flex items-center gap-2 rounded-full gradient-radiant px-6 py-3 text-sm font-medium text-primary-foreground glow-magenta transition-transform hover:scale-[1.02]"
            >
              Try again
            </button>
          </motion.div>
        </section>
      </div>
    );
  }

  return (
    <div className="min-h-screen text-foreground">
      <SiteHeader />

      <div className="pt-10">
        <WorkflowStepper current={2} />
      </div>

      <section className="relative mx-auto max-w-3xl px-6 py-12 lg:px-10 lg:py-16">
        <div
          className="pointer-events-none absolute -right-20 top-20 h-96 w-96 rounded-full opacity-30 blur-3xl animate-drift"
          style={{ background: "radial-gradient(circle, var(--magenta) 0%, transparent 70%)" }}
        />
        <div
          className="pointer-events-none absolute -left-20 bottom-20 h-80 w-80 rounded-full opacity-30 blur-3xl animate-drift"
          style={{
            background: "radial-gradient(circle, var(--cyan) 0%, transparent 70%)",
            animationDelay: "-8s",
          }}
        />

        <p className="font-mono text-xs uppercase tracking-[0.2em] text-magenta">
          Step 02 — Assess
        </p>
        <h1 className="mt-3 font-serif text-5xl leading-[1.05] md:text-6xl">
          Designing your <span className="italic text-gradient-radiant">system…</span>
        </h1>
        <p className="mt-3 text-muted-foreground">
          Eight agents working in concert. Usually 3–5 minutes.
        </p>

        {/* Progress bar */}
        <div className="mt-8 flex items-center gap-4">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface">
            <motion.div
              className="h-full gradient-radiant animate-shimmer"
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.6, ease: "easeOut" }}
            />
          </div>
          <span className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {Math.round(progress)}%
          </span>
        </div>

        <ol className="mt-10 space-y-3">
          {stages.map((s, i) => {
            const done = allDone || i < animStep;
            const active = !allDone && i === animStep;
            return (
              <motion.li
                key={s.t}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.35, delay: i * 0.05 }}
                className={`relative flex items-start gap-4 overflow-hidden rounded-2xl p-5 transition-all ${
                  active
                    ? "glass ring-1 ring-magenta/60"
                    : done
                      ? "glass opacity-90"
                      : "border border-border/40 bg-transparent"
                }`}
              >
                {active && (
                  <span className="pointer-events-none absolute inset-0 -z-10 opacity-30 blur-2xl gradient-radiant" />
                )}
                <div
                  className={`mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-full transition-all ${
                    done
                      ? "gradient-radiant text-primary-foreground"
                      : active
                        ? "gradient-radiant text-primary-foreground glow-magenta"
                        : "bg-surface text-muted-foreground"
                  }`}
                >
                  {done ? (
                    <Check className="h-4 w-4" strokeWidth={2.5} />
                  ) : active ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <span className="font-mono text-[10px]">{i + 1}</span>
                  )}
                </div>
                <div className="flex-1">
                  <p
                    className={`font-medium ${
                      active || done ? "text-foreground" : "text-muted-foreground"
                    }`}
                  >
                    {s.t}
                  </p>
                  <p className="mt-0.5 text-sm text-muted-foreground">{s.d}</p>
                </div>
                {active && (
                  <span className="font-mono text-[10px] uppercase tracking-wider text-magenta">
                    Running
                  </span>
                )}
              </motion.li>
            );
          })}
        </ol>
      </section>
    </div>
  );
}
