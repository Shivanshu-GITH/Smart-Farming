"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { api, type ChatMessage } from "@/lib/api";

export default function AdvisoryChat({ context }: { context: unknown }) {
  const [open, setOpen] = useState(false);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const t = useTranslations("chat");
  const locale = useLocale();

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
      const { reply } = await api.advisoryChat(next, context, locale);
      setMessages([...next, { role: "assistant", content: reply }]);
    } catch {
      setMessages([...next, { role: "assistant", content: t("error") }]);
    } finally {
      setBusy(false);
    }
  }

  async function diagnosePhoto(file: File) {
    setBusy(true);
    setMessages((m) => [...m, { role: "user", content: t("photoSent") }]);
    try {
      const dataUrl: string = await new Promise((resolve, reject) => {
        const r = new FileReader();
        r.onload = () => resolve(r.result as string);
        r.onerror = reject;
        r.readAsDataURL(file);
      });
      const { reply } = await api.diagnose(dataUrl, file.type || "image/jpeg", input.trim() || undefined, context);
      setMessages((m) => [...m, { role: "assistant", content: reply }]);
      setInput("");
    } catch {
      setMessages((m) => [...m, { role: "assistant", content: t("error") }]);
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
            <button className="icon-btn" title={t("photo")}
              disabled={busy || configured === false}
              onClick={() => fileRef.current?.click()}>📷</button>
            <button className="btn btn-sm" disabled={busy || configured === false}
              onClick={send}>{t("send")}</button>
            <input ref={fileRef} type="file" accept="image/*" hidden
              onChange={(e) => { const f = e.target.files?.[0]; if (f) diagnosePhoto(f); e.target.value = ""; }} />
          </div>
        </div>
      )}
    </>
  );
}
