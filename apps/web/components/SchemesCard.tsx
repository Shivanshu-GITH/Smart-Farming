"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { api, type SchemeResource } from "@/lib/api";

export default function SchemesCard({ state }: { state?: string }) {
  const t = useTranslations("schemes");
  const [items, setItems] = useState<SchemeResource[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.schemes(state).then((r) => setItems(r.resources)).catch(() => setItems([]));
  }, [state]);

  if (items.length === 0) return null;

  return (
    <div className="card">
      <h3 style={{ cursor: "pointer" }} onClick={() => setOpen((o) => !o)}>
        {t("title")} {open ? "▾" : "▸"}
      </h3>
      {open && items.map((r) => (
        <a className="scheme" key={r.id} href={r.url} target="_blank" rel="noreferrer">
          <div className="scheme-name">{r.name}</div>
          <div className="scheme-desc">{r.description}</div>
        </a>
      ))}
    </div>
  );
}
