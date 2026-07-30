"use client";

import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SqlAnswer } from "@/lib/api";

export function SqlResultTable({ result }: { result: SqlAnswer }) {
  if (result.row_count === 0 && result.columns.length === 0) {
    return null;
  }

  return (
    <div className="mt-2 space-y-2">
      <div className="flex items-center gap-2">
        <Badge className="bg-slate-100 text-slate-700">
          {result.row_count} row{result.row_count === 1 ? "" : "s"}
        </Badge>
        {result.truncated ? (
          <Badge className="bg-amber-100 text-amber-700">showing first 200</Badge>
        ) : null}
      </div>

      <div className="max-h-80 overflow-auto rounded-md border border-border bg-white">
        <Table>
          <TableHeader>
            <TableRow>
              {result.columns.map((column) => (
                <TableHead key={column}>{column}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {result.rows.map((row, rowIndex) => (
              <TableRow key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <TableCell key={cellIndex}>{cell === null ? "—" : String(cell)}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* The API omits `sql` for roles that may not view it, so the
          component simply respects what it was given. */}
      {result.sql ? (
        <details className="rounded-md border border-border bg-white p-3">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
            View SQL
          </summary>
          <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words text-xs text-slate-700">
            {result.sql}
          </pre>
        </details>
      ) : null}
    </div>
  );
}
