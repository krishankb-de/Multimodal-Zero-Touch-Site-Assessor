"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { FinalProposal } from "@/lib/api";

// In a real app this would fetch from a list endpoint.
// For now we use localStorage to track known pipeline_run_ids.
export default function ProposalListPage() {
  const router = useRouter();
  const [proposals, setProposals] = useState<FinalProposal[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ids: string[] = JSON.parse(localStorage.getItem("proposal_ids") || "[]");
    if (ids.length === 0) {
      setLoading(false);
      return;
    }
    Promise.all(
      ids.map((id) =>
        fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/proposals/${id}`)
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null)
      )
    ).then((results) => {
      setProposals(results.filter(Boolean) as FinalProposal[]);
      setLoading(false);
    });
  }, []);

  const pending = proposals.filter((p) => p.human_signoff.status === "pending");

  return (
    <main className="min-h-screen bg-gray-50 p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Installer Dashboard</h1>
        <button
          onClick={() => router.push("/upload")}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"
        >
          + New Assessment
        </button>
      </div>
      <h2 className="text-lg font-semibold text-gray-700 mb-4">
        Pending Proposals ({pending.length})
      </h2>

      {loading && <p className="text-gray-500">Loading proposals…</p>}

      {!loading && pending.length === 0 && (
        <p className="text-gray-500">No pending proposals.</p>
      )}

      <ul className="space-y-4">
        {pending.map((proposal) => (
          <li
            key={proposal.metadata.pipeline_run_id}
            className="bg-white rounded-lg shadow p-6 flex items-center justify-between"
          >
            <div>
              <p className="font-mono text-sm text-gray-500">
                {proposal.metadata.pipeline_run_id}
              </p>
              <p className="text-gray-800 mt-1">
                {proposal.system_design.pv.total_kwp} kWp PV ·{" "}
                {proposal.system_design.battery.capacity_kwh} kWh battery ·{" "}
                {proposal.system_design.heat_pump.capacity_kw} kW heat pump
              </p>
              <p className="text-sm text-gray-500 mt-1">
                Generated: {new Date(proposal.metadata.generated_at).toLocaleString()}
              </p>
            </div>
            <Link
              href={`/proposals/${proposal.metadata.pipeline_run_id}`}
              className="ml-4 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm font-medium"
            >
              Review
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
