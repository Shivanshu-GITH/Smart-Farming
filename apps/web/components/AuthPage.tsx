"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { supabase } from "@/lib/supabase";
import { useAuth } from "@/lib/auth";
import { LanguageSwitcher } from "@/lib/i18n";

/** Full-page sign in / sign up backed by Supabase. Google is offered first, with
 *  email + password below. On sign-up the project requires email confirmation,
 *  so we show a "check your inbox" state instead of a (non-existent) session. */
export default function AuthPage({ mode }: { mode: "login" | "signup" }) {
  const t = useTranslations("auth");
  const router = useRouter();
  const { user, ready } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState<"email" | "google" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  // Already signed in (or just completed the OAuth redirect) → leave the page.
  useEffect(() => {
    if (ready && user) router.replace("/");
  }, [ready, user, router]);

  const origin = typeof window !== "undefined" ? window.location.origin : undefined;

  async function submitEmail() {
    if (!email.trim() || password.length < 6) return;
    setBusy("email");
    setError(null);
    try {
      if (mode === "signup") {
        const { data, error } = await supabase.auth.signUp({
          email: email.trim(),
          password,
          options: {
            data: name.trim() ? { full_name: name.trim() } : undefined,
            emailRedirectTo: origin,
          },
        });
        if (error) throw error;
        // Confirmation on → no session yet; confirmation off → the auth effect
        // above redirects on the new session.
        if (!data.session) setSent(true);
      } else {
        const { error } = await supabase.auth.signInWithPassword({
          email: email.trim(),
          password,
        });
        if (error) throw error;
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function google() {
    setBusy("google");
    setError(null);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: origin },
    });
    // On success the browser navigates to Google, so nothing below runs.
    if (error) {
      setError(t("googleError"));
      setBusy(null);
    }
  }

  if (sent) {
    return (
      <div className="auth-page">
        <div className="auth-lang"><LanguageSwitcher /></div>
        <div className="auth-card">
          <div className="brand auth-brand"><span className="leaf">🌱</span><h1>SmartFarm</h1></div>
          <h2 className="auth-title">{t("checkEmailTitle")}</h2>
          <p className="hint auth-sub">{t("checkEmailBody", { email: email.trim() })}</p>
          <p className="auth-alt"><Link href="/login">{t("goLogin")}</Link></p>
          <p className="auth-alt"><Link href="/">{t("backToApp")}</Link></p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-lang"><LanguageSwitcher /></div>
      <div className="auth-card">
        <div className="brand auth-brand"><span className="leaf">🌱</span><h1>SmartFarm</h1></div>
        <h2 className="auth-title">
          {mode === "login" ? t("pageLoginTitle") : t("pageSignupTitle")}
        </h2>
        <p className="hint auth-sub">
          {mode === "login" ? t("pageLoginSub") : t("pageSignupSub")}
        </p>

        <button className="google-btn" disabled={busy !== null} onClick={google}>
          <GoogleGlyph />
          {busy === "google" ? t("signingIn") : t("continueWithGoogle")}
        </button>

        <div className="divider"><span>{t("or")}</span></div>

        {mode === "signup" && (
          <input className="input" placeholder={t("name")} autoComplete="name"
            value={name} onChange={(e) => setName(e.target.value)} />
        )}
        <input className="input" type="email" placeholder={t("email")} autoComplete="email"
          value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className="input" type="password" placeholder={t("password")}
          autoComplete={mode === "signup" ? "new-password" : "current-password"}
          value={password} onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submitEmail(); }} />
        <button className="btn auth-btn" onClick={submitEmail}
          disabled={busy !== null || !email.trim() || password.length < 6}>
          {busy === "email"
            ? (mode === "signup" ? t("creatingAccount") : t("signingIn"))
            : (mode === "signup" ? t("register") : t("loginBtn"))}
        </button>
        {error && <p className="error">{error}</p>}

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

/** Official Google "G" mark for the sign-in button. */
function GoogleGlyph() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.71-1.57 2.68-3.88 2.68-6.62z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.83.86-3.04.86-2.34 0-4.32-1.58-5.03-3.71H.96v2.33A9 9 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.97 10.71a5.4 5.4 0 0 1 0-3.42V4.96H.96a9 9 0 0 0 0 8.08l3.01-2.33z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.59C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.96l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z" />
    </svg>
  );
}
