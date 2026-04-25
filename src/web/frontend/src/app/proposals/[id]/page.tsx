"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getProposal, signoffProposal, type FinalProposal } from "@/lib/api";

export default function ProposalDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [proposal, setProposal] = useState<FinalProposal | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rejectNotes, setRejectNotes] = useState("");
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    getProposal(id)
      .then(setProposal)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  async function handleApprove() {
    if (!proposal) return;
    setActionLoading(true);
    setActionError(null);
    try {
      const updated = await signoffProposal(id, "approve");
      setProposal(updated);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleReject() {
    if (!proposal || !rejectNotes.trim()) {
      setActionError("Please provide rejection notes before rejecting.");
      return;
    }
    setActionLoading(true);
    setActionError(null);
    try {
      const updated = await signoffProposal(id, "reject", rejectNotes);
      setProposal(updated);
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : "Rejection failed");
    } finally {
      setActionLoading(false);
    }
  }

  if (loading) return <main className="p-8"><p>Loading…</p></main>;
  if (error) return <main className="p-8"><p className="text-red-600">{error}</p></main>;
  if (!proposal) return null;

  const isPending = proposal.human_signoff.status === "pending";

  return (
    <main className="min-h-screen bg-gray-50 p-8 max-w-4xl mx-auto">
      <button
        onClick={() => router.push("/")}
        className="text-blue-600 hover:underline mb-6 block text-sm"
      >
        ← Back to proposals
      </button>

      <h1 className="text-2xl font-bold text-gray-900 mb-2">Proposal Review</h1>
      <p className="font-mono text-sm text-gray-500 mb-6">{id}</p>

      {/* Status badge */}
      <div className="mb-6">
        <span
          className={`inline-block px-3 py-1 rounded-full text-sm font-medium ${
            proposal.human_signoff.status === "approved"
              ? "bg-green-100 text-green-800"
              : proposal.human_signoff.status === "rejected"
              ? "bg-red-100 text-red-800"
              : "bg-yellow-100 text-yellow-800"
          }`}
        >
          {proposal.human_signoff.status.toUpperCase()}
        </span>
        {!isPending && (
          <p className="text-sm text-gray-500 mt-1">
            This proposal has been {proposal.human_signoff.status} and cannot be delivered to the
            customer while status is pending.
          </p>
        )}
      </div>

      {/* System Design */}
      <section className="bg-white rounded-lg shadow p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-4">System Design</h2>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className="text-sm text-gray-500">PV System</p>
            <p className="font-medium">{proposal.system_design.pv.total_kwp} kWp</p>
            <p className="text-sm text-gray-600">{proposal.system_design.pv.panel_count} panels</p>
            <p className="text-sm text-gray-600">Inverter: {proposal.system_design.pv.inverter_type}</p>
          </div>
          <div>
            <p className="text-sm text-gray-500">Battery</p>
            <p className="font-medium">{proposal.system_design.battery.capacity_kwh} kWh</p>
          </div>
          <div>
            <p className="text-sm text-gray-500">Heat Pump</p>
            <p className="font-medium">{proposal.system_design.heat_pump.capacity_kw} kW</p>
            {proposal.system_design.heat_pump.type && (
              <p className="text-sm text-gray-600">{proposal.system_design.heat_pump.type}</p>
            )}
            {proposal.system_design.heat_pump.cop && (
              <p className="text-sm text-gray-600">COP: {proposal.system_design.heat_pump.cop}</p>
            )}
            {proposal.system_design.heat_pump.cylinder_litres && (
              <p className="text-sm text-gray-600">
                Cylinder: {proposal.system_design.heat_pump.cylinder_litres}L
              </p>
            )}
          </div>
        </div>
      </section>

      {/* Financial Summary */}
      <section className="bg-white rounded-lg shadow p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-4">Financial Summary</h2>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <p className="text-sm text-gray-500">Total Cost</p>
            <p className="font-medium text-lg">
              €{proposal.financial_summary.total_cost_eur.toLocaleString()}
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-500">Annual Savings</p>
            <p className="font-medium text-lg text-green-700">
              €{proposal.financial_summary.annual_savings_eur.toLocaleString()}/yr
            </p>
          </div>
          <div>
            <p className="text-sm text-gray-500">Payback Period</p>
            <p className="font-medium text-lg">
              {proposal.financial_summary.payback_years.toFixed(1)} years
            </p>
          </div>
        </div>
      </section>

      {/* Compliance */}
      <section className="bg-white rounded-lg shadow p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-4">Compliance</h2>
        {proposal.compliance.electrical_upgrades.length > 0 && (
          <div className="mb-3">
            <p className="text-sm font-medium text-gray-700 mb-1">Electrical Upgrades Required:</p>
            <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
              {proposal.compliance.electrical_upgrades.map((u, i) => (
                <li key={i}>{u}</li>
              ))}
            </ul>
          </div>
        )}
        {proposal.compliance.regulatory_notes.length > 0 && (
          <div>
            <p className="text-sm font-medium text-gray-700 mb-1">Regulatory Notes:</p>
            <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
              {proposal.compliance.regulatory_notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* Signoff Actions — only shown when pending */}
      {isPending && (
        <section className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">Installer Sign-off</h2>
          <p className="text-sm text-gray-600 mb-4">
            This proposal requires your review before it can be delivered to the customer.
          </p>

          {actionError && (
            <p className="text-red-600 text-sm mb-4">{actionError}</p>
          )}

          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Rejection Notes (required for rejection)
            </label>
            <textarea
              value={rejectNotes}
              onChange={(e) => setRejectNotes(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              rows={3}
              placeholder="Explain the reason for rejection…"
            />
          </div>

          <div className="flex gap-3">
            <button
              onClick={handleApprove}
              disabled={actionLoading}
              className="px-6 py-2 bg-green-600 text-white rounded hover:bg-green-700 font-medium disabled:opacity-50"
            >
              {actionLoading ? "Processing…" : "Approve"}
            </button>
            <button
              onClick={handleReject}
              disabled={actionLoading || !rejectNotes.trim()}
              className="px-6 py-2 bg-red-600 text-white rounded hover:bg-red-700 font-medium disabled:opacity-50"
            >
              {actionLoading ? "Processing…" : "Reject"}
            </button>
          </div>
        </section>
      )}

      {/* Show signoff details if already signed */}
      {!isPending && (
        <section className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-2">Sign-off Details</h2>
          <p className="text-sm text-gray-600">
            Installer: {proposal.human_signoff.installer_id || "—"}
          </p>
          <p className="text-sm text-gray-600">
            Signed at:{" "}
            {proposal.human_signoff.signed_at
              ? new Date(proposal.human_signoff.signed_at).toLocaleString()
              : "—"}
          </p>
          {proposal.human_signoff.notes && (
            <p className="text-sm text-gray-600 mt-1">
              Notes: {proposal.human_signoff.notes}
            </p>
          )}
        </section>
      )}
    </main>
  );
}
