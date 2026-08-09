// Neon Managed Better Auth — browser client.
//
// Uses better-auth's framework-agnostic React client. All auth traffic goes
// direct to Neon Auth (sign-in, session, sign-out); our FastAPI backend only
// verifies the resulting JWT.
import { createAuthClient } from "better-auth/react";

const NEON_AUTH_URL = process.env.REACT_APP_NEON_AUTH_URL;

if (!NEON_AUTH_URL) {
  console.error(
    "REACT_APP_NEON_AUTH_URL is not set — Neon Auth cannot be used."
  );
}

export const authClient = createAuthClient({
  baseURL: NEON_AUTH_URL,
  fetchOptions: { credentials: "include" },
});

// Fetch the current JWT (Neon's Better Auth JWT plugin). Returns null when
// the user is not signed in.
export async function getJwt() {
  try {
    const res = await authClient.$fetch("/token", { method: "GET" });
    // better-auth's $fetch resolves with { data, error } OR the raw JSON body
    // depending on the endpoint — accept both shapes.
    const payload = res?.data ?? res ?? null;
    if (!payload) return null;
    return payload.token || payload.jwt || payload.accessToken || null;
  } catch (_e) {
    return null;
  }
}

export async function signInWithGoogle() {
  const callbackURL = window.location.origin + "/";
  return authClient.signIn.social({ provider: "google", callbackURL });
}

export async function signOut() {
  try {
    await authClient.signOut();
  } catch (_) {
    /* noop */
  }
}
