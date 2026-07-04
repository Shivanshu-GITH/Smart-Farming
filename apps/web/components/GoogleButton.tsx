"use client";

import { useEffect, useRef, useState } from "react";
import { api, type User } from "@/lib/api";

const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

declare global {
  interface Window { google?: any }
}

/** Renders the official Google Identity Services button when a client id is
 *  configured; hidden otherwise so the app works without Google setup. */
export default function GoogleButton({
  onSuccess, onError,
}: {
  onSuccess: (token: string, user: User) => void;
  onError: (message: string) => void;
}) {
  const slot = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!CLIENT_ID || !slot.current) return;

    const render = () => {
      if (!window.google || !slot.current) return;
      window.google.accounts.id.initialize({
        client_id: CLIENT_ID,
        callback: async (res: { credential: string }) => {
          try {
            const out = await api.googleAuth(res.credential);
            onSuccess(out.access_token, out.user);
          } catch {
            onError("google");
          }
        },
      });
      window.google.accounts.id.renderButton(slot.current, {
        theme: "outline", size: "large", width: 320, text: "continue_with",
      });
    };

    if (window.google?.accounts?.id) {
      render();
      return;
    }
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = render;
    script.onerror = () => setFailed(true);
    document.head.appendChild(script);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!CLIENT_ID || failed) return null;
  return <div ref={slot} className="google-slot" />;
}
