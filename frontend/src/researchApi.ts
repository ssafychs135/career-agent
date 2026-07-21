export async function postCompanyResearch(company: string, force = false) {
  const r = await fetch("/api/research/company", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ company, force }),
  });
  if (!r.ok) throw new Error("company research trigger failed");
  return r.json();
}

export async function postJobResearch(source: string, jobId: string, force = false) {
  const r = await fetch("/api/research/job", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, job_id: jobId, force }),
  });
  if (!r.ok) throw new Error("job research trigger failed");
  return r.json();
}
