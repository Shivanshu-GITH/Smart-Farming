"use client";

import { createClient } from "@supabase/supabase-js";

// Supabase owns authentication (email + Google). These are public, browser-safe
// values baked in at build time; the anon key only allows what the project's
// row-level security lets an anonymous caller do.
const URL = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const ANON = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";

/** True when the project is configured — lets the UI degrade gracefully. */
export const supabaseConfigured = Boolean(URL && ANON);

export const supabase = createClient(URL, ANON, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    // Pick up the session from the URL hash after the Google OAuth redirect.
    detectSessionInUrl: true,
  },
});
