"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { api, type User } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { LanguageSwitcher } from "@/lib/i18n";

export default function AuthBar() {
  const { user, ready, login, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const t = useTranslations("auth");

  if (!ready) return null;

  return (
    <div className="authbar">
      <LanguageSwitcher />
      {user ? (
        <>
          <span className="authbar-user">👤 {user.email || user.phone}</span>
          <button className="btn btn-sm" onClick={logout}>{t("signOut")}</button>
        </>
      ) : (
        <button className="btn btn-sm" onClick={() => setOpen(true)}>{t("signIn")}</button>
      )}
      {open && (
        <LoginModal
          onClose={() => setOpen(false)}
          onSuccess={(token, u) => { login(token, u); setOpen(false); }}
        />
      )}
    </div>
  );
}

function LoginModal({
  onClose,
  onSuccess,
}: {
  onClose: () => void;
  onSuccess: (token: string, user: User) => void;
}) {
  const t = useTranslations("auth");
  const [tab, setTab] = useState<"email" | "phone">("email");

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{t("signIn")}</h3>
        <div className="tabs">
          <button className={"tab" + (tab === "email" ? " active" : "")}
            onClick={() => setTab("email")}>{t("tabEmail")}</button>
          <button className={"tab" + (tab === "phone" ? " active" : "")}
            onClick={() => setTab("phone")}>{t("tabPhone")}</button>
        </div>
        {tab === "email"
          ? <EmailForm onSuccess={onSuccess} />
          : <PhoneForm onSuccess={onSuccess} />}
      </div>
    </div>
  );
}

function EmailForm({ onSuccess }: { onSuccess: (t: string, u: User) => void }) {
  const t = useTranslations("auth");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true); setError(null);
    try {
      const res = mode === "register"
        ? await api.register(email.trim(), password, name.trim() || undefined)
        : await api.login(email.trim(), password);
      onSuccess(res.access_token, res.user);
    } catch {
      setError(t("emailError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <input className="input" type="email" placeholder={t("email")}
        value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
      {mode === "register" && (
        <input className="input" placeholder={t("name")}
          value={name} onChange={(e) => setName(e.target.value)} />
      )}
      <input className="input" type="password" placeholder={t("password")}
        value={password} onChange={(e) => setPassword(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
      <button className="btn" disabled={busy || !email.trim() || password.length < 6}
        onClick={submit}>
        {mode === "register" ? t("register") : t("loginBtn")}
      </button>
      <button className="btn-link"
        onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); }}>
        {mode === "login" ? t("toggleToRegister") : t("toggleToLogin")}
      </button>
      {error && <p className="error">{error}</p>}
    </>
  );
}

function PhoneForm({ onSuccess }: { onSuccess: (t: string, u: User) => void }) {
  const t = useTranslations("auth");
  const [step, setStep] = useState<"phone" | "code">("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [devHint, setDevHint] = useState<string | null>(null);

  async function requestCode() {
    setBusy(true); setError(null);
    try {
      const res = await api.requestOtp(phone.trim());
      if (res.dev_code) { setDevHint(res.dev_code); setCode(res.dev_code); }
      setStep("code");
    } catch {
      setError(t("sendError"));
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    setBusy(true); setError(null);
    try {
      const res = await api.verifyOtp(phone.trim(), code.trim());
      onSuccess(res.access_token, res.user);
    } catch {
      setError(t("codeError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {step === "phone" ? (
        <>
          <p className="hint">{t("phonePrompt")}</p>
          <input className="input" placeholder="+91 98765 43210"
            value={phone} onChange={(e) => setPhone(e.target.value)} autoFocus />
          <button className="btn" disabled={busy || phone.trim().length < 6}
            onClick={requestCode}>{busy ? t("sending") : t("sendCode")}</button>
        </>
      ) : (
        <>
          <p className="hint">{t("codePrompt", { phone })}</p>
          {devHint && <p className="dev-hint">{t("devCode")} <b>{devHint}</b></p>}
          <input className="input" placeholder="123456"
            value={code} onChange={(e) => setCode(e.target.value)} autoFocus />
          <button className="btn" disabled={busy || code.trim().length < 4}
            onClick={verify}>{busy ? t("verifying") : t("verify")}</button>
          <button className="btn-link" onClick={() => setStep("phone")}>
            {t("changeNumber")}
          </button>
        </>
      )}
      {error && <p className="error">{error}</p>}
    </>
  );
}
