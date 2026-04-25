"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { uploadMedia } from "@/lib/api";

type Step = 1 | 2 | 3 | 4;

interface StepFile {
  file: File | null;
  preview: string;
}

const STEPS: { step: Step; label: string; sublabel: string; accept: string; hint: string }[] = [
  {
    step: 1,
    label: "Roofline Video",
    sublabel: "Walk around the roof perimeter",
    accept: "video/mp4,video/quicktime,video/webm",
    hint: "MP4, MOV or WebM · max 100 MB",
  },
  {
    step: 2,
    label: "Electrical Panel Photo",
    sublabel: "Open consumer unit showing all breakers",
    accept: "image/jpeg,image/png,image/heic",
    hint: "JPG, PNG or HEIC · max 100 MB",
  },
  {
    step: 3,
    label: "Utility Bill",
    sublabel: "Most recent 12-month electricity bill",
    accept: "application/pdf",
    hint: "PDF · max 100 MB",
  },
];

function FileDropZone({
  accept,
  hint,
  file,
  onChange,
}: {
  accept: string;
  hint: string;
  file: File | null;
  onChange: (f: File) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) onChange(f);
  }

  return (
    <div
      onDrop={handleDrop}
      onDragOver={(e) => e.preventDefault()}
      onClick={() => ref.current?.click()}
      className="border-2 border-dashed border-gray-300 rounded-lg p-8 flex flex-col items-center justify-center cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition-colors"
    >
      <input
        ref={ref}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onChange(f);
        }}
      />
      {file ? (
        <>
          <svg className="w-8 h-8 text-green-500 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          <p className="text-sm font-medium text-gray-800 text-center break-all">{file.name}</p>
          <p className="text-xs text-gray-400 mt-1">{(file.size / 1024 / 1024).toFixed(1)} MB · click to replace</p>
        </>
      ) : (
        <>
          <svg className="w-8 h-8 text-gray-400 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
          </svg>
          <p className="text-sm text-gray-500">Drag & drop or click to choose</p>
          <p className="text-xs text-gray-400 mt-1">{hint}</p>
        </>
      )}
    </div>
  );
}

function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-2 mb-8">
      {Array.from({ length: total }, (_, i) => i + 1).map((n) => (
        <div key={n} className="flex items-center gap-2">
          <div
            className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold ${
              n < current
                ? "bg-green-500 text-white"
                : n === current
                ? "bg-blue-600 text-white"
                : "bg-gray-200 text-gray-500"
            }`}
          >
            {n < current ? (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
              </svg>
            ) : n}
          </div>
          {n < total && <div className={`h-0.5 w-6 ${n < current ? "bg-green-500" : "bg-gray-200"}`} />}
        </div>
      ))}
    </div>
  );
}

export default function UploadPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>(1);
  const [files, setFiles] = useState<{ video: File | null; photo: File | null; bill: File | null }>({
    video: null,
    photo: null,
    bill: null,
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);

  const fileKeys = ["video", "photo", "bill"] as const;
  const currentKey = fileKeys[step - 1];
  const currentStepMeta = STEPS[step - 1];

  function setFile(key: typeof fileKeys[number], file: File) {
    setFiles((prev) => ({ ...prev, [key]: file }));
  }

  async function handleSubmit() {
    if (!files.video || !files.photo || !files.bill) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await uploadMedia(files.video, files.photo, files.bill);
      // Persist run ID so the proposals dashboard can find it
      const existing: string[] = JSON.parse(localStorage.getItem("proposal_ids") || "[]");
      if (!existing.includes(result.pipeline_run_id)) {
        localStorage.setItem("proposal_ids", JSON.stringify([result.pipeline_run_id, ...existing]));
      }
      setRunId(result.pipeline_run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Submission failed");
      setSubmitting(false);
    }
  }

  // Success screen
  if (runId) {
    return (
      <main className="min-h-screen bg-gray-50 flex items-center justify-center p-8">
        <div className="bg-white rounded-xl shadow-lg p-10 max-w-md w-full text-center">
          <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-gray-900 mb-2">Assessment complete</h1>
          <p className="text-sm text-gray-500 mb-4">Your proposal has been generated and is awaiting installer review.</p>
          <p className="font-mono text-xs text-gray-400 bg-gray-50 rounded px-3 py-2 mb-6 break-all">{runId}</p>
          <div className="flex flex-col gap-3">
            <button
              onClick={() => router.push(`/proposals/${runId}`)}
              className="w-full px-6 py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700"
            >
              View Proposal
            </button>
            <button
              onClick={() => router.push("/")}
              className="w-full px-6 py-3 border border-gray-200 text-gray-700 rounded-lg font-medium hover:bg-gray-50"
            >
              Back to Dashboard
            </button>
          </div>
        </div>
      </main>
    );
  }

  // Submission in progress
  if (submitting) {
    return (
      <main className="min-h-screen bg-gray-50 flex items-center justify-center p-8">
        <div className="bg-white rounded-xl shadow-lg p-10 max-w-md w-full text-center">
          <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4 animate-pulse">
            <svg className="w-8 h-8 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-gray-900 mb-2">Analysing your home…</h1>
          <p className="text-sm text-gray-500 mb-1">Running multimodal assessment pipeline</p>
          <p className="text-xs text-gray-400">This takes 30–90 seconds. Please keep this tab open.</p>
        </div>
      </main>
    );
  }

  // Review screen (step 4)
  if (step === 4) {
    return (
      <main className="min-h-screen bg-gray-50 p-8 max-w-xl mx-auto">
        <StepIndicator current={4} total={4} />
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Review & Submit</h1>
        <p className="text-gray-500 text-sm mb-8">Confirm all three files before running the assessment.</p>

        <div className="bg-white rounded-xl shadow p-6 mb-6 space-y-4">
          {STEPS.map(({ label }, i) => {
            const f = files[fileKeys[i]];
            return (
              <div key={i} className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center ${f ? "bg-green-500" : "bg-gray-200"}`}>
                    {f && (
                      <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </div>
                  <span className="text-sm font-medium text-gray-700">{label}</span>
                </div>
                <span className="text-xs text-gray-400 truncate max-w-[160px]">
                  {f ? f.name : <span className="text-red-400">missing</span>}
                </span>
              </div>
            );
          })}
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 mb-4">
            <p className="text-sm text-red-700">{error}</p>
          </div>
        )}

        <div className="flex gap-3">
          <button
            onClick={() => setStep(3)}
            className="px-5 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50"
          >
            Back
          </button>
          <button
            onClick={handleSubmit}
            disabled={!files.video || !files.photo || !files.bill}
            className="flex-1 px-5 py-2.5 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Run Assessment
          </button>
        </div>
      </main>
    );
  }

  // File upload steps 1–3
  const canAdvance = !!files[currentKey];

  return (
    <main className="min-h-screen bg-gray-50 p-8 max-w-xl mx-auto">
      <StepIndicator current={step} total={4} />

      <div className="mb-6">
        <p className="text-xs font-semibold text-blue-600 uppercase tracking-wide mb-1">
          Step {step} of 3
        </p>
        <h1 className="text-2xl font-bold text-gray-900">{currentStepMeta.label}</h1>
        <p className="text-gray-500 text-sm mt-1">{currentStepMeta.sublabel}</p>
      </div>

      <FileDropZone
        accept={currentStepMeta.accept}
        hint={currentStepMeta.hint}
        file={files[currentKey]}
        onChange={(f) => setFile(currentKey, f)}
      />

      <div className="flex gap-3 mt-6">
        {step > 1 && (
          <button
            onClick={() => setStep((s) => (s - 1) as Step)}
            className="px-5 py-2.5 border border-gray-300 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-50"
          >
            Back
          </button>
        )}
        <button
          onClick={() => setStep((s) => (s + 1) as Step)}
          disabled={!canAdvance}
          className="flex-1 px-5 py-2.5 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {step === 3 ? "Review" : "Next"}
        </button>
      </div>
    </main>
  );
}
