"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { api, type User } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { LanguageSwitcher } from "@/lib/i18n";
import GoogleButton from "@/components/GoogleButton";

/** Full-page login / signup used by the /login and /signup routes.
 *  Email + password is primary; phone OTP and Google are alternatives. */
export default function AuthPage({ mode }: { mode: "login" | "signup" }) {
  const t = useTranslations("auth");
  const router = useRouter();
  const { login } = useAuth();
  const [method, setMethod] = useState<"email" | "phone">("email");
  const [error, setError] = useState<string | null>(null);

  function done(token: string, user: User) {
    login(token, user);
    router.push("/");
  }

  return (
    <div className="auth-page">
      <div className="auth-lang"><LanguageSwitcher /></div>
      <div className="auth-card">
        <div className="brand auth-brand">
          <span className="leaf">🌱</span>
          <h1>SmartFarm</h1>
        </div>
        <h2 className="auth-title">
          {mode === "login" ? t("pageLoginTitle") : t("pageSignupTitle")}
        </h2>
        <p className="hint auth-sub">
          {mode === "login" ? t("pageLoginSub") : t("pageSignupSub")}
        </p>

        <div className="tabs">
          <button className={"tab" + (method === "email" ? " active" : "")}
            onClick={() => { setMethod("email"); setError(null); }}>
            {t("tabEmail")}
          </button>
          <button className={"tab" + (method === "phone" ? " active" : "")}
            onClick={() => { setMethod("phone"); setError(null); }}>
            {t("tabPhone")}
          </button>
        </div>

        {method === "email"
          ? <EmailForm mode={mode} onSuccess={done} error={error} setError={setError} />
          : <PhoneForm onSuccess={done} />}

        <div className="divider"><span>{t("or")}</span></div>
        <GoogleButton onSuccess={done} onError={() => setError(t("emailError"))} />

        <p className="auth-alt">
          {mode === "login"
            ? <Link href="/signup">{t("goSignup")}</Link>
            : <Link href="/login">{t("goLogin")}</Link>}
        </p>
        <p className="auth-alt"><Link href="/">{t("backToApp")}</Link></p>
      </div>
    </div>
  );
}

function EmailForm({ mode, onSuccess, error, setError }: {
  mode: "login" | "signup";
  onSuccess: (t: string, u: User) => void;
  error: string | null;
  setError: (e: string | null) => void;
}) {
  const t = useTranslations("auth");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!email.trim() || password.length < 6) return;
    setBusy(true); setError(null);
    try {
      const res = mode === "signup"
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
      {mode === "signup" && (
        <input className="input" placeholder={t("name")}
          value={name} onChange={(e) => setName(e.target.value)} />
      )}
      <input className="input" type="password" placeholder={t("password")}
        value={password} onChange={(e) => setPassword(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
      <button className="btn auth-btn" disabled={busy || !email.trim() || password.length < 6}
        onClick={submit}>
        {mode === "signup" ? t("register") : t("loginBtn")}
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
          <button className="btn auth-btn" disabled={busy || phone.trim().length < 6}
            onClick={requestCode}>{busy ? t("sending") : t("sendCode")}</button>
        </>
      ) : (
        <>
          <p className="hint">{t("codePrompt", { phone })}</p>
          {devHint && <p className="dev-hint">{t("devCode")} <b>{devHint}</b></p>}
          <input className="input" placeholder="123456"
            value={code} onChange={(e) => setCode(e.target.value)} autoFocus />
          <button className="btn auth-btn" disabled={busy || code.trim().length < 4}
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
