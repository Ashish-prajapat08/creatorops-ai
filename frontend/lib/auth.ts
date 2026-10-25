import { createClient, type SupabaseClient } from "@supabase/supabase-js";
let client: SupabaseClient | undefined;
export function auth() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) throw new Error("Configure Supabase Auth to sign in.");
  client ??= createClient(url, key);
  return client;
}
export async function token() {
  if (process.env.NEXT_PUBLIC_TEST_MODE === "true") {
    const testToken = sessionStorage.getItem("creatorops-test-token");
    return testToken || undefined;
  }
  const { data, error } = await auth().auth.getSession();
  if (error) throw error;
  return data.session?.access_token;
}
export async function signOut() {
  sessionStorage.removeItem("creatorops-test-token");
  if (process.env.NEXT_PUBLIC_SUPABASE_URL) await auth().auth.signOut();
  localStorage.removeItem("creatorops-agency");
}
