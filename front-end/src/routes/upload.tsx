import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { motion } from "framer-motion";
import { ArrowRight, FileText, Home, MapPin, Upload as UploadIcon, X, Zap } from "lucide-react";
import { useRef, useState } from "react";
import { SiteFooter, SiteHeader } from "@/components/site-header";
import { WorkflowStepper } from "@/components/workflow-stepper";
import { startAssessment } from "@/lib/api";

export const Route = createFileRoute("/upload")({
  head: () => ({
    meta: [
      { title: "Upload — Helio" },
      { name: "description", content: "Upload your roof video, panel photo, and utility bill to start your free assessment." },
    ],
  }),
  component: UploadPage,
});

type SlotKey = "video" | "photo" | "bill";

const slots: { key: SlotKey; title: string; hint: string; accept: string; icon: typeof Home; color: string }[] = [
  { key: "video", title: "Roof video", hint: "MP4 or MOV · ~30s walk around the house", accept: "video/mp4,video/quicktime", icon: Home, color: "magenta" },
  { key: "photo", title: "Panel photo", hint: "JPG or PNG · clear shot of your fuse box", accept: "image/jpeg,image/png", icon: Zap, color: "violet" },
  { key: "bill", title: "Utility bill", hint: "PDF · most recent annual or monthly bill", accept: "application/pdf", icon: FileText, color: "cyan" },
];

function UploadPage() {
  const navigate = useNavigate();
  const [files, setFiles] = useState<Record<SlotKey, File | null>>({ video: null, photo: null, bill: null });
  const [location, setLocation] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const allReady = files.video && files.photo && files.bill;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!allReady) return;
    setSubmitting(true);

    const formData = new FormData();
    formData.append("video", files.video!);
    formData.append("photo", files.photo!);
    formData.append("bill", files.bill!);
    if (location.trim()) formData.append("location", location.trim());

    startAssessment(formData);
    void navigate({ to: "/processing" });
  };

  return (
    <div className="min-h-screen text-foreground">
      <SiteHeader />

      <div className="pt-10">
        <WorkflowStepper current={1} />
      </div>

      <section className="mx-auto max-w-4xl px-6 py-12 lg:px-10 lg:py-16">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-magenta">
            Step 01 — Upload
          </p>
          <h1 className="mt-3 font-serif text-5xl leading-[1.05] md:text-6xl">
            Hand us <span className="italic text-gradient-radiant">three files.</span>
          </h1>
          <p className="mt-4 max-w-xl text-muted-foreground">
            Everything stays private. Files are processed in a single run and discarded
            unless you choose to save the proposal.
          </p>
        </motion.div>

        <form onSubmit={handleSubmit} className="mt-12 space-y-4">
          {slots.map((slot, i) => (
            <DropSlot
              key={slot.key}
              title={slot.title}
              hint={slot.hint}
              accept={slot.accept}
              icon={slot.icon}
              index={i}
              color={slot.color}
              file={files[slot.key]}
              onChange={(f) => setFiles((s) => ({ ...s, [slot.key]: f }))}
            />
          ))}

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="rounded-3xl glass p-6"
          >
            <label className="flex items-center gap-2 text-sm font-medium">
              <MapPin className="h-4 w-4 text-cyan" strokeWidth={1.75} />
              Location <span className="font-normal text-muted-foreground">(optional)</span>
            </label>
            <input
              type="text"
              placeholder="Berlin, Germany"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              className="mt-3 w-full rounded-xl border border-border bg-background/50 px-4 py-3 text-sm placeholder:text-muted-foreground/60 focus:border-magenta focus:outline-none focus:ring-2 focus:ring-magenta/30"
            />
            <p className="mt-2 text-xs text-muted-foreground">
              We'll fetch 5 years of historical weather for your exact coordinates.
            </p>
          </motion.div>

          <div className="flex flex-col-reverse items-stretch justify-between gap-4 pt-4 sm:flex-row sm:items-center">
            <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
              {allReady
                ? "Ready · Est. ~5 min"
                : `${[files.video, files.photo, files.bill].filter(Boolean).length} of 3 uploaded`}
            </p>
            <button
              type="submit"
              disabled={!allReady || submitting}
              className="group inline-flex items-center justify-center gap-2 rounded-full gradient-radiant px-7 py-4 text-sm font-medium text-primary-foreground transition-all enabled:glow-magenta enabled:hover:scale-[1.02] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {submitting ? "Starting…" : "Continue to Step 2"}
              <ArrowRight className="h-4 w-4 transition-transform group-enabled:group-hover:translate-x-0.5" />
            </button>
          </div>
        </form>
      </section>

      <SiteFooter />
    </div>
  );
}

function DropSlot({
  title,
  hint,
  accept,
  icon: Icon,
  file,
  onChange,
  index,
  color,
}: {
  title: string;
  hint: string;
  accept: string;
  icon: typeof Home;
  file: File | null;
  onChange: (f: File | null) => void;
  index: number;
  color: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: index * 0.08 }}
    >
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          const f = e.dataTransfer.files?.[0];
          if (f) onChange(f);
        }}
        onClick={() => inputRef.current?.click()}
        className={`group relative flex cursor-pointer items-center gap-5 overflow-hidden rounded-3xl glass p-6 transition-all ${
          drag
            ? "ring-2 ring-magenta scale-[1.01]"
            : file
              ? "ring-1 ring-magenta/40"
              : "hover:-translate-y-0.5"
        }`}
      >
        <div
          className="pointer-events-none absolute -right-12 top-1/2 h-32 w-32 -translate-y-1/2 rounded-full opacity-25 blur-2xl transition-opacity group-hover:opacity-50"
          style={{ background: `radial-gradient(circle, var(--${color}) 0%, transparent 70%)` }}
        />
        <div
          className="flex h-14 w-14 flex-none items-center justify-center rounded-2xl text-primary-foreground transition-transform group-hover:scale-105"
          style={{
            background: file
              ? `linear-gradient(135deg, var(--${color}) 0%, var(--magenta) 120%)`
              : `linear-gradient(135deg, var(--${color}) 0%, transparent 130%)`,
          }}
        >
          <Icon className="h-6 w-6" strokeWidth={2} />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="font-serif text-xl">{title}</h3>
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              0{index + 1}
            </span>
          </div>
          {file ? (
            <p className="mt-0.5 truncate text-sm text-foreground">
              {file.name}{" "}
              <span className="text-muted-foreground">
                · {(file.size / 1024 / 1024).toFixed(1)} MB
              </span>
            </p>
          ) : (
            <p className="mt-0.5 text-sm text-muted-foreground">{hint}</p>
          )}
        </div>

        {file ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onChange(null);
            }}
            className="flex h-9 w-9 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-surface-elevated hover:text-foreground"
            aria-label="Remove file"
          >
            <X className="h-4 w-4" />
          </button>
        ) : (
          <div className="hidden items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider text-muted-foreground sm:flex">
            <UploadIcon className="h-3.5 w-3.5" />
            Drop · click
          </div>
        )}

        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="hidden"
          onChange={(e) => onChange(e.target.files?.[0] ?? null)}
        />
      </div>
    </motion.div>
  );
}
