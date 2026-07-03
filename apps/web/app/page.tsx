"use client";

import dynamic from "next/dynamic";
import { AuthProvider } from "@/lib/auth";
import AuthBar from "@/components/AuthBar";

// MapLibre touches `window`, so load the planner client-side only.
const Planner = dynamic(() => import("@/components/Planner"), { ssr: false });

export default function Home() {
  return (
    <AuthProvider>
      <AuthBar />
      <Planner />
    </AuthProvider>
  );
}
