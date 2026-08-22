import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "https://placeholder.supabase.co";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "placeholder-anon-key";

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

// Auth helpers
export async function getSession() {
  const { data: { session } } = await supabase.auth.getSession();
  return session;
}

export async function getUser() {
  const { data: { user } } = await supabase.auth.getUser();
  return user;
}

export async function signOut() {
  await supabase.auth.signOut();
}

export async function getAccessToken(): Promise<string | null> {
  const session = await getSession();
  return session?.access_token ?? null;
}

// Fetch all previously submitted URLs / analysis jobs for a specific user
export async function getUserJobs(userId: string, limit = 20): Promise<JobRow[]> {
  if (!userId) return [];
  try {
    const { data, error } = await supabase
      .from("analysis_jobs")
      .select("*")
      .eq("user_id", userId)
      .order("created_at", { ascending: false })
      .limit(limit);
    if (error) {
      console.error("[supabase] getUserJobs error:", error.message);
      return [];
    }
    return data || [];
  } catch (e) {
    console.error("[supabase] getUserJobs exception:", e);
    return [];
  }
}

// Types
export interface JobRow {
  id: string;
  user_id: string | null;
  repo_url: string;
  repo_name: string | null;
  framework: string | null;
  status: "running" | "done" | "stopped" | "error";
  error_message: string | null;
  health_score: number | null;
  created_at: string;
  completed_at: string | null;
}

export interface PrRow {
  id: string;
  job_id: string;
  user_id: string | null;
  repo_url: string;
  pr_url: string;
  pr_title: string | null;
  branch_name: string | null;
  files_changed: string[];
  bugs_fixed: number;
  created_at: string;
  analysis_jobs?: { repo_name: string | null; framework: string | null };
}
