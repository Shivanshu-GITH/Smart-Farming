"use client";

import { createContext, useContext, useEffect, useState } from "react";
import type { Session, User as SupabaseUser } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase";
import type { User } from "@/lib/api";

interface AuthState {
  user: User | null;
  ready: boolean; // finished restoring the session
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

/** Map a Supabase user onto the shape the rest of the app already expects. */
function toUser(u: SupabaseUser): User {
  const meta = u.user_metadata || {};
  return {
    id: u.id,
    email: u.email ?? null,
    phone: u.phone ?? null,
    name: (meta.full_name as string) || (meta.name as string) || null,
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Restore any existing session (localStorage / OAuth redirect), then follow
    // sign-in / sign-out / token-refresh events for the rest of the page's life.
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => {
      setSession(s);
      setReady(true);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  const user = session?.user ? toUser(session.user) : null;

  async function signOut() {
    await supabase.auth.signOut();
  }

  return (
    <AuthContext.Provider value={{ user, ready, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
