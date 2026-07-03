"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { api, getToken, setToken, type User } from "@/lib/api";

interface AuthState {
  user: User | null;
  ready: boolean; // finished restoring session from storage
  login: (token: string, user: User) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  // Restore a session from a stored token on first load.
  useEffect(() => {
    const token = getToken();
    if (!token) {
      setReady(true);
      return;
    }
    api.me()
      .then(setUser)
      .catch(() => setToken(null)) // stale/invalid token
      .finally(() => setReady(true));
  }, []);

  function login(token: string, u: User) {
    setToken(token);
    setUser(u);
  }

  function logout() {
    setToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, ready, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
