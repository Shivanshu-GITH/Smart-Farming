"use client";

import dynamic from "next/dynamic";
import { AuthProvider } from "@/lib/auth";
import { I18nProvider } from "@/lib/i18n";
import AuthBar from "@/components/AuthBar";

// MapLibre touches `window`, so load the planner client-side only.
const Planner = dynamic(() => import("@/components/Planner"), { ssr: false });

export default function Home() {
  return (
    <I18nProvider>
      <AuthProvider>
        <AuthBar />
        <Planner />
      </AuthProvider>
    </I18nProvider>
  );
}
