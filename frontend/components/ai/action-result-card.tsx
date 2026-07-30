"use client";

import { useState } from "react";
import { CheckCircle2, ShieldAlert, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PendingAction } from "@/lib/api";

type Outcome = { executed: boolean; approved: boolean; message: string };

/**
 * The confirmation gate. Nothing has been executed when this renders —
 * the agent proposed an action and the server is holding a signed token
 * until the user decides. Both outcomes are shown explicitly: confirming
 * reports what was done, declining reports that nothing was executed.
 */
export function ActionResultCard({
  action,
  onDecide,
}: {
  action: PendingAction;
  onDecide: (approve: boolean) => Promise<{ executed: boolean; message: string }>;
}) {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const decide = async (approve: boolean) => {
    setBusy(true);
    try {
      const result = await onDecide(approve);
      setOutcome({ executed: result.executed, approved: approve, message: result.message });
    } finally {
      setBusy(false);
    }
  };

  if (outcome) {
    const good = outcome.executed;
    return (
      <div
        className={`mt-2 rounded-md border p-3 ${
          good ? "border-emerald-200 bg-emerald-50" : "border-slate-200 bg-slate-50"
        }`}
      >
        <div className="flex items-center gap-2">
          {good ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
          ) : (
            <XCircle className="h-4 w-4 text-slate-500" />
          )}
          <Badge
            className={good ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-700"}
          >
            {good ? "Executed" : outcome.approved ? "Not executed" : "Cancelled — not executed"}
          </Badge>
        </div>
        <p className="mt-2 text-sm text-slate-700">{outcome.message}</p>
        {!good && !outcome.approved ? (
          <p className="mt-1 text-xs text-muted-foreground">
            Nothing was submitted. You can ask again if this was a mistake.
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-3">
      <div className="flex items-center gap-2">
        <ShieldAlert className="h-4 w-4 text-amber-600" />
        <Badge className="bg-amber-100 text-amber-800">Confirmation required</Badge>
      </div>

      <p className="mt-2 text-sm font-medium text-slate-800">{action.summary}</p>

      <dl className="mt-2 grid gap-1 text-xs text-slate-600">
        {Object.entries(action.arguments)
          .filter(([, value]) => value !== null && value !== undefined && value !== "")
          .map(([key, value]) => (
            <div className="flex gap-2" key={key}>
              <dt className="min-w-32 font-medium">{key.replace(/_/g, " ")}</dt>
              <dd>{String(value)}</dd>
            </div>
          ))}
      </dl>

      <p className="mt-2 text-xs text-muted-foreground">
        Nothing has been submitted yet. This request expires in {action.expires_in_minutes} minutes.
      </p>

      <div className="mt-3 flex gap-2">
        <Button size="sm" disabled={busy} onClick={() => decide(true)}>
          {busy ? "Working…" : "Confirm"}
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => decide(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
