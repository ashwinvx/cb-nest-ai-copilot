"use client";

import { useEffect, useRef } from "react";
import { Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** Rendered under the message bubble (sources, result table, action card). */
  extra?: React.ReactNode;
};

export function ChatPanel({
  messages,
  input,
  onInputChange,
  onSend,
  busy,
  placeholder,
  emptyHint,
}: {
  messages: ChatMessage[];
  input: string;
  onInputChange: (value: string) => void;
  onSend: () => void;
  busy: boolean;
  placeholder: string;
  emptyHint: React.ReactNode;
}) {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  return (
    <div className="flex min-h-[28rem] flex-col rounded-md border border-border bg-white">
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <div className="text-sm text-muted-foreground">{emptyHint}</div>
        ) : null}

        {messages.map((message) => (
          <div
            key={message.id}
            className={cn("flex", message.role === "user" ? "justify-end" : "justify-start")}
          >
            <div className={cn("max-w-[85%] space-y-2", message.role === "user" && "text-right")}>
              <div
                className={cn(
                  "inline-block whitespace-pre-wrap rounded-md px-3 py-2 text-sm",
                  message.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "border border-border bg-muted/40 text-left"
                )}
              >
                {message.content}
              </div>
              {message.extra ? <div className="text-left">{message.extra}</div> : null}
            </div>
          </div>
        ))}

        {busy ? (
          <div className="flex justify-start">
            <div className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
              Thinking…
            </div>
          </div>
        ) : null}
        <div ref={endRef} />
      </div>

      <form
        className="flex items-end gap-2 border-t border-border p-3"
        onSubmit={(event) => {
          event.preventDefault();
          onSend();
        }}
      >
        <textarea
          className="h-20 flex-1 resize-none rounded-md border border-border px-3 py-2 text-sm"
          placeholder={placeholder}
          value={input}
          disabled={busy}
          onChange={(event) => onInputChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onSend();
            }
          }}
        />
        <Button type="submit" disabled={busy || input.trim().length === 0}>
          <Send className="mr-2 h-4 w-4" />
          Send
        </Button>
      </form>
    </div>
  );
}
