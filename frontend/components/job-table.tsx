"use client";

import { useMemo, useState } from "react";
import {
  type ColumnDef,
  type VisibilityState,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { Columns3 } from "lucide-react";
import type { Job } from "@/lib/api";
import { experience, place, salary, sourceLabel, timeAgo } from "@/lib/format";
import { Badge, Button } from "@/components/ui/primitives";
import { Checkbox } from "@/components/ui/controls";

export function JobTable({
  jobs,
  selectedId,
  onSelect,
}: {
  jobs: Job[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const [visible, setVisible] = useState<VisibilityState>({ department: false, employment_type: false });
  const [picker, setPicker] = useState(false);

  const columns = useMemo<ColumnDef<Job>[]>(
    () => [
      {
        id: "title",
        header: "Title",
        accessorKey: "title",
        cell: ({ row }) => (
          <span className="flex items-center gap-1.5">
            <span className="truncate font-medium">{row.original.title}</span>
            {row.original.is_new && row.original.status === "active" && <Badge variant="success">NEW</Badge>}
          </span>
        ),
      },
      { id: "company", header: "Company", accessorFn: (j) => j.company_name ?? "—" },
      { id: "location", header: "Location", accessorFn: (j) => place(j) },
      { id: "work_arrangement", header: "Mode", accessorFn: (j) => j.work_arrangement ?? "—" },
      { id: "employment_type", header: "Type", accessorFn: (j) => j.employment_type ?? "—" },
      { id: "department", header: "Department", accessorFn: (j) => j.department ?? "—" },
      { id: "exp", header: "Exp", accessorFn: (j) => experience(j) ?? "—" },
      {
        id: "salary",
        header: "Salary",
        accessorFn: (j) => salary(j) ?? "—",
        cell: ({ getValue }) => <span className="tabular">{getValue() as string}</span>,
      },
      {
        id: "skills",
        header: "Skills",
        cell: ({ row }) => (
          <span className="flex gap-1 overflow-hidden">
            {row.original.skills.slice(0, 2).map((s) => (
              <Badge key={s} variant="secondary" className="shrink-0">
                {s}
              </Badge>
            ))}
            {row.original.skills.length > 2 && <Badge variant="outline">+{row.original.skills.length - 2}</Badge>}
          </span>
        ),
      },
      { id: "source", header: "Source", accessorFn: (j) => sourceLabel(j.source) },
      {
        id: "posted",
        header: "Posted",
        accessorFn: (j) => timeAgo(j.posted_at ?? j.first_seen_at),
        cell: ({ getValue }) => <span className="whitespace-nowrap tabular">{getValue() as string}</span>,
      },
      {
        id: "match",
        header: "Match",
        accessorFn: (j) => j.match_score,
        cell: ({ getValue }) => {
          const v = getValue() as number | null;
          return <span className="tabular">{v == null ? "—" : `${Math.round(v * 100)}%`}</span>;
        },
      },
    ],
    [],
  );

  const table = useReactTable({
    data: jobs,
    columns,
    state: { columnVisibility: visible },
    onColumnVisibilityChange: setVisible,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="relative">
      <div className="sticky top-0 z-10 flex justify-end border-b bg-background px-2 py-1">
        <div className="relative">
          <Button variant="ghost" size="sm" onClick={() => setPicker((p) => !p)}>
            <Columns3 />
            Columns
          </Button>
          {picker && (
            <div className="absolute right-0 z-20 mt-1 w-44 rounded-md border bg-popover p-1 shadow-md">
              {table.getAllLeafColumns().map((col) => (
                <label key={col.id} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm hover:bg-accent">
                  <Checkbox checked={col.getIsVisible()} onCheckedChange={() => col.toggleVisibility()} />
                  <span className="capitalize">{col.id.replace(/_/g, " ")}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* The dense view carries more columns than the pane is wide — let it scroll sideways. */}
      <div className="overflow-x-auto">
      <table className="w-max min-w-full text-sm">
        <thead className="sticky top-9 z-10 bg-background">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="border-b">
              {hg.headers.map((h) => (
                <th key={h.id} className="whitespace-nowrap px-3 py-2 text-left text-xs font-medium text-muted-foreground">
                  {flexRender(h.column.columnDef.header, h.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr
              key={row.id}
              onClick={() => onSelect(row.original.id)}
              className={`cursor-pointer border-b transition-colors hover:bg-accent/50 ${
                selectedId === row.original.id ? "bg-accent" : ""
              } ${row.original.status === "closed" ? "opacity-60" : ""}`}
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="max-w-[26ch] truncate whitespace-nowrap px-3 py-1.5">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
