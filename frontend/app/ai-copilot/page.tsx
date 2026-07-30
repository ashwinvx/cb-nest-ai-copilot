"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { ActionOutcome, ActionResultCard } from "@/components/ai/action-result-card";
import { ChatMessage, ChatPanel } from "@/components/ai/chat-panel";
import { SourceList } from "@/components/ai/source-list";
import { SqlResultTable } from "@/components/ai/sql-result-table";
import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ActionConfirmResult,
  ActionTurn,
  ApiEnvelope,
  PendingAction,
  PolicyAnswer,
  PolicySource,
  SqlAnswer,
  askPolicy,
  askSql,
  confirmChatAction,
  fetchProfile,
  sendChatAction,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type Mode = "policy" | "sql" | "actions";

/**
 * Everything a message renders is stored as data on the message itself,
 * including whether a proposed action has been resolved. Keeping the
 * outcome here (rather than inside ActionResultCard) is what makes a
 * confirmed or cancelled action stay resolved when the panel unmounts
 * and remounts — switching tabs, for example.
 */
type CopilotMessage = ChatMessage & {
  sources?: PolicySource[];
  sqlResult?: SqlAnswer;
  pendingAction?: PendingAction;
  outcome?: ActionOutcome;
};

const MODES: Array<{ key: Mode; label: string; blurb: string; placeholder: string }> = [
  {
    key: "policy",
    label: "HR Policies",
    blurb: "Ask about leave, attendance, work from home and other HR policies. Answers cite the policy documents they came from.",
    placeholder: "e.g. Can I take a half-day leave?",
  },
  {
    key: "sql",
    label: "HR Data",
    blurb: "Ask questions about HR data. Queries are read-only and scoped to what your role may see.",
    placeholder: "e.g. How many employees are in each department?",
  },
  {
    key: "actions",
    label: "Actions",
    blurb: "Check your leave balance or file a leave request. Anything that changes data asks you to confirm first.",
    placeholder: "e.g. Apply casual leave for 2026-09-20, reason: family function",
  },
];

let messageCounter = 0;
const nextId = () => `m${(messageCounter += 1)}`;

function unwrap<T>(body: unknown): T | null {
  if (!body || typeof body !== "object") return null;
  const record = body as Record<string, unknown>;
  if (record.success === true && "data" in record) {
    return (record as ApiEnvelope<T>).data;
  }
  return null;
}

function extractErrorMessage(body: unknown, fallback: string) {
  if (!body || typeof body !== "object") return fallback;
  const record = body as Record<string, unknown>;
  const detail = record.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const detailRecord = detail as Record<string, unknown>;
    const error = detailRecord.error;
    if (error && typeof error === "object") {
      const message = (error as Record<string, unknown>).message;
      if (typeof message === "string") return message;
    }
  }
  if (record.error && typeof record.error === "object") {
    const message = (record.error as Record<string, unknown>).message;
    if (typeof message === "string") return message;
  }
  return fallback;
}

export default function AiCopilotPage() {
  const [name, setName] = useState("User");
  const [role, setRole] = useState("EMPLOYEE");
  const [mode, setMode] = useState<Mode>("policy");
  const [threads, setThreads] = useState<Record<Mode, CopilotMessage[]>>({
    policy: [],
    sql: [],
    actions: [],
  });
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();

  const token = useMemo(() => {
    if (typeof window === "undefined") {
      return null;
    }
    return localStorage.getItem("hrms_access_token");
  }, []);

  useEffect(() => {
    if (!token) {
      router.replace("/login");
      return;
    }
    const load = async () => {
      const result = await fetchProfile(token);
      if (result.status === 401) {
        router.replace("/login");
        return;
      }
      const profile = unwrap<{ name: string; role: string }>(result.body);
      if (profile) {
        setName(profile.name);
        setRole(profile.role);
      }
    };
    void load();
  }, [router, token]);

  const append = (target: Mode, message: CopilotMessage) => {
    setThreads((current) => ({ ...current, [target]: [...current[target], message] }));
  };

  /**
   * Resolve a proposed action and record the outcome on the message
   * itself, so the resolution survives the panel unmounting (tab
   * switches) instead of living in the card's local state.
   */
  const decideAction = async (messageId: string, actionToken: string, approve: boolean) => {
    const settle = (outcome: ActionOutcome) => {
      setThreads((current) => ({
        ...current,
        actions: current.actions.map((message) =>
          message.id === messageId ? { ...message, outcome } : message
        ),
      }));
    };

    if (!token) {
      settle({ executed: false, approved: approve, message: "Your session has expired." });
      return;
    }
    const result = await confirmChatAction(token, actionToken, approve);
    const data = unwrap<ActionConfirmResult>(result.body);
    settle({
      executed: data?.executed ?? false,
      approved: approve,
      message:
        data?.message ??
        extractErrorMessage(result.body, "That confirmation could not be completed."),
    });
  };

  const send = async () => {
    const question = input.trim();
    if (!question || !token || busy) return;

    setError("");
    setInput("");
    const active = mode;
    append(active, { id: nextId(), role: "user", content: question });
    setBusy(true);

    try {
      if (active === "policy") {
        const result = await askPolicy(token, question);
        if (result.status === 401) return router.replace("/login");
        const data = unwrap<PolicyAnswer>(result.body);
        if (!data) {
          setError(extractErrorMessage(result.body, "Unable to answer that right now."));
          return;
        }
        append(active, {
          id: nextId(),
          role: "assistant",
          content: data.answer,
          sources: data.sources,
        });
      } else if (active === "sql") {
        const result = await askSql(token, question);
        if (result.status === 401) return router.replace("/login");
        const data = unwrap<SqlAnswer>(result.body);
        if (!data) {
          setError(extractErrorMessage(result.body, "Unable to answer that right now."));
          return;
        }
        // A role refusal comes back as a normal successful answer (with
        // routing suggestions) — it is correct behaviour, so it renders
        // as an assistant message, never as an error.
        append(active, {
          id: nextId(),
          role: "assistant",
          content: data.answer,
          sqlResult: data,
        });
      } else {
        const history = threads.actions.map((message) => ({
          role: message.role,
          content: message.content,
        }));
        const result = await sendChatAction(token, question, history);
        if (result.status === 401) return router.replace("/login");
        const data = unwrap<ActionTurn>(result.body);
        if (!data) {
          setError(extractErrorMessage(result.body, "Unable to answer that right now."));
          return;
        }
        append(active, {
          id: nextId(),
          role: "assistant",
          content: data.reply,
          pendingAction: data.pending_action ?? undefined,
        });
      }
    } catch {
      setError("Could not reach the assistant. Check that the API is running.");
    } finally {
      setBusy(false);
    }
  };

  const activeMode = MODES.find((item) => item.key === mode) ?? MODES[0];

  return (
    <main className="flex min-h-screen">
      <Sidebar />
      <section className="flex w-full flex-col">
        <Topbar name={name} title="AI Copilot" />
        <div className="space-y-4 p-6">
          {error ? <p className="text-sm text-red-600">{error}</p> : null}

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                AI Copilot
                {/* Role is shown because answers are role-scoped: the same
                    question returns different data for a manager and an admin. */}
                <Badge className="bg-indigo-100 text-indigo-700">{role}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-2">
                {MODES.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => setMode(item.key)}
                    className={cn(
                      "rounded-md border border-border px-3 py-2 text-sm transition",
                      mode === item.key
                        ? "bg-primary text-primary-foreground"
                        : "bg-white hover:bg-muted"
                    )}
                  >
                    {item.label}
                  </button>
                ))}
              </div>

              <p className="text-sm text-muted-foreground">{activeMode.blurb}</p>

              <ChatPanel
                messages={threads[mode]}
                input={input}
                onInputChange={setInput}
                onSend={send}
                busy={busy}
                placeholder={activeMode.placeholder}
                renderExtra={(message) => (
                  <>
                    {message.sources ? <SourceList sources={message.sources} /> : null}
                    {message.sqlResult ? <SqlResultTable result={message.sqlResult} /> : null}
                    {message.pendingAction ? (
                      <ActionResultCard
                        action={message.pendingAction}
                        outcome={message.outcome ?? null}
                        onDecide={(approve) =>
                          decideAction(message.id, message.pendingAction!.action_token, approve)
                        }
                      />
                    ) : null}
                  </>
                )}
                emptyHint={
                  <span>
                    Ask a question to get started — for example,{" "}
                    <span className="font-medium">{activeMode.placeholder.replace("e.g. ", "")}</span>
                  </span>
                }
              />
            </CardContent>
          </Card>
        </div>
      </section>
    </main>
  );
}
