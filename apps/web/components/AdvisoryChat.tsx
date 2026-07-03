"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { api, type ChatMessage } from "@/lib/api";

export default function AdvisoryChat({ context }: { context: unknown }) {
  const [open, setOpen] = useState(false);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const t = useTranslations("chat");

  useEffect(() => {
    if (open && configured === null) {
      api.advisoryStatus().then((s) => setConfigured(s.configured)).catch(() => setConfigured(false));
    }
  }, [open, configured]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [messages, busy]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    const next = [...messages, { role: "user" as const, content: text }];
    setMessages(next);
    setInput("");
    setBusy(true);
    try {
      const { reply } = await api.advisoryChat(next, context);
      setMessages([...next, { role: "assistant", content: reply }]);
    } catch {
      setMessages([...next, { role: "assistant", content: t("error") }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button className="chat-fab" onClick={() => setOpen((o) => !o)}
        title={t("title")}>
        {open ? "✕" : t("ask")}
      </button>
      {open && (
        <div className="chat-panel">
          <div className="chat-head">{t("title")}</div>
          <div className="chat-body" ref={bodyRef}>
            {configured === false && (
              <div className="chat-msg assistant">{t("notConfigured")}</div>
            )}
            {configured !== false && messages.length === 0 && (
              <div className="chat-msg assistant">{t("greeting")}</div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={"chat-msg " + m.role}>{m.content}</div>
            ))}
            {busy && <div className="chat-msg assistant">{t("thinking")}</div>}
          </div>
          <div className="chat-input">
            <input
              value={input}
              placeholder={t("placeholder")}
              disabled={configured === false}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") send(); }}
            />
            <button className="btn btn-sm" disabled={busy || configured === false}
              onClick={send}>{t("send")}</button>
          </div>
        </div>
      )}
    </>
  );
}
