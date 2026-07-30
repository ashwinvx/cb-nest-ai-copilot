"use client";

import { Badge } from "@/components/ui/badge";
import { PolicySource } from "@/lib/api";

export function SourceList({ sources }: { sources: PolicySource[] }) {
  if (sources.length === 0) {
    return null;
  }

  return (
    <details className="mt-2 rounded-md border border-border bg-white p-3">
      <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
        Sources ({sources.length})
      </summary>
      <ul className="mt-3 space-y-3">
        {sources.map((source) => (
          <li key={source.id} className="rounded-md border border-border p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium">{source.title}</p>
              <Badge className="bg-indigo-100 text-indigo-700">
                {Math.round(source.score * 100)}% match
              </Badge>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{source.id}</p>
            <p className="mt-2 text-xs text-slate-600">{source.snippet}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}
