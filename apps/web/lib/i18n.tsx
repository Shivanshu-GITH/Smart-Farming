"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { NextIntlClientProvider } from "next-intl";
import en from "@/messages/en.json";
import hi from "@/messages/hi.json";
import te from "@/messages/te.json";

export const LOCALES = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
  { code: "te", label: "తెలుగు" },
] as const;

export type LocaleCode = (typeof LOCALES)[number]["code"];

const MESSAGES: Record<LocaleCode, typeof en> = { en, hi, te };
const STORE_KEY = "smartfarm_locale";

interface LocaleState { locale: LocaleCode; setLocale: (l: LocaleCode) => void; }
const LocaleContext = createContext<LocaleState | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<LocaleCode>("en");

  useEffect(() => {
    const saved = window.localStorage.getItem(STORE_KEY) as LocaleCode | null;
    if (saved && saved in MESSAGES) setLocaleState(saved);
  }, []);

  function setLocale(l: LocaleCode) {
    setLocaleState(l);
    window.localStorage.setItem(STORE_KEY, l);
  }

  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      <NextIntlClientProvider
        locale={locale}
        messages={MESSAGES[locale]}
        timeZone="Asia/Kolkata"
      >
        {children}
      </NextIntlClientProvider>
    </LocaleContext.Provider>
  );
}

export function useLocaleSwitcher(): LocaleState {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error("useLocaleSwitcher must be used within I18nProvider");
  return ctx;
}

export function LanguageSwitcher() {
  const { locale, setLocale } = useLocaleSwitcher();
  return (
    <select
      className="lang-select"
      value={locale}
      onChange={(e) => setLocale(e.target.value as LocaleCode)}
      aria-label="Language"
    >
      {LOCALES.map((l) => (
        <option key={l.code} value={l.code}>{l.label}</option>
      ))}
    </select>
  );
}
