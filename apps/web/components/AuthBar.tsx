"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useAuth } from "@/lib/auth";
import { LanguageSwitcher } from "@/lib/i18n";

export default function AuthBar() {
  const { user, ready, logout } = useAuth();
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
        <Link className="btn btn-sm" href="/login">{t("signIn")}</Link>
      )}
    </div>
  );
}
