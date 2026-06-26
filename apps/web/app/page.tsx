"use client";

import dynamic from "next/dynamic";

// MapLibre touches `window`, so load the planner client-side only.
const Planner = dynamic(() => import("@/components/Planner"), { ssr: false });

export default function Home() {
  return <Planner />;
}
