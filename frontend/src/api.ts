export async function getHealth(): Promise<{ status: string }> {
  const r = await fetch("/api/health");
  if (!r.ok) throw new Error("health failed");
  return r.json();
}

export async function getClaudeCheck(): Promise<{ ok: boolean; reply: string }> {
  const r = await fetch("/api/claude-check");
  if (!r.ok) throw new Error("claude-check failed");
  return r.json();
}
