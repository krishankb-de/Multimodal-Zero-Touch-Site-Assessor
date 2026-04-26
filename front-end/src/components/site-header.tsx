import { Link } from "@tanstack/react-router";
import { Sun } from "lucide-react";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 w-full border-b border-border/40 bg-background/60 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6 lg:px-10">
        <Link to="/" className="flex items-center gap-2.5 group">
          <div className="relative flex h-9 w-9 items-center justify-center rounded-xl gradient-radiant text-primary-foreground glow-magenta transition-transform group-hover:rotate-12">
            <Sun className="h-4 w-4" strokeWidth={2.5} />
          </div>
          <div className="flex flex-col leading-none">
            <span className="font-serif text-xl tracking-tight">Helio</span>
            <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted-foreground">
              Site Assessor
            </span>
          </div>
        </Link>

        <nav className="hidden items-center gap-1 md:flex">
          {[
            { to: "/" as const, label: "Overview", exact: true },
            { to: "/how-it-works" as const, label: "How it works" },
            { to: "/proposal" as const, label: "Sample" },
          ].map((l) => (
            <Link
              key={l.to}
              to={l.to}
              {...(l.exact ? { activeOptions: { exact: true } } : {})}
              activeProps={{ className: "text-foreground bg-surface-elevated" }}
              className="rounded-full px-4 py-2 text-sm text-muted-foreground transition-colors hover:text-foreground hover:bg-surface-elevated/60"
            >
              {l.label}
            </Link>
          ))}
        </nav>

        <Link
          to="/upload"
          className="group relative inline-flex h-10 items-center justify-center overflow-hidden rounded-full gradient-radiant px-5 text-sm font-medium text-primary-foreground glow-magenta transition-transform hover:scale-[1.03]"
        >
          <span className="relative z-10">Start workflow</span>
        </Link>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="border-t border-border/40">
      <div className="mx-auto flex max-w-7xl flex-col items-start justify-between gap-4 px-6 py-10 md:flex-row md:items-center lg:px-10">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg gradient-radiant text-primary-foreground">
            <Sun className="h-3.5 w-3.5" strokeWidth={2.5} />
          </div>
          <span className="font-serif text-base">Helio</span>
          <span className="text-xs text-muted-foreground">
            · Engineering-grade solar in minutes
          </span>
        </div>
        <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
          © {new Date().getFullYear()} · Always human-signed
        </p>
      </div>
    </footer>
  );
}