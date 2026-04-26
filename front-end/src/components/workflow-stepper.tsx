import { Link } from "@tanstack/react-router";
import { Check } from "lucide-react";

const steps = [
  { n: 1, label: "Upload", path: "/upload" as const },
  { n: 2, label: "Assess", path: "/processing" as const },
  { n: 3, label: "Proposal", path: "/proposal" as const },
];

export function WorkflowStepper({ current }: { current: 1 | 2 | 3 }) {
  return (
    <div className="mx-auto w-full max-w-3xl px-6 lg:px-10">
      <ol className="flex items-center justify-between gap-2">
        {steps.map((s, i) => {
          const done = s.n < current;
          const active = s.n === current;
          const Comp: React.ElementType = done ? Link : "div";
          return (
            <div key={s.n} className="flex flex-1 items-center">
              <Comp
                {...(done ? { to: s.path } : {})}
                className={`group flex items-center gap-3 ${done ? "cursor-pointer" : ""}`}
              >
                <span
                  className={`relative flex h-9 w-9 flex-none items-center justify-center rounded-full text-xs font-medium transition-all ${
                    active
                      ? "gradient-radiant text-primary-foreground glow-magenta"
                      : done
                        ? "bg-primary/20 text-primary ring-1 ring-primary/40"
                        : "bg-surface text-muted-foreground ring-1 ring-border"
                  }`}
                >
                  {done ? <Check className="h-4 w-4" strokeWidth={2.5} /> : s.n}
                  {active && (
                    <span className="absolute inset-0 -z-10 animate-ping rounded-full bg-primary/40" />
                  )}
                </span>
                <span
                  className={`hidden text-sm font-medium sm:inline-block ${
                    active ? "text-foreground" : done ? "text-foreground/80" : "text-muted-foreground"
                  }`}
                >
                  {s.label}
                </span>
              </Comp>
              {i < steps.length - 1 && (
                <div className="mx-3 h-px flex-1 overflow-hidden rounded-full bg-border">
                  <div
                    className={`h-full transition-all duration-700 ${
                      s.n < current ? "w-full gradient-radiant" : "w-0"
                    }`}
                  />
                </div>
              )}
            </div>
          );
        })}
      </ol>
    </div>
  );
}