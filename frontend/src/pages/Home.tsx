import { useEffect, useState } from "react";
import { getHealth, getClaudeCheck } from "../api";

export default function Home() {
  const [health, setHealth] = useState("…");
  const [claude, setClaude] = useState("…");

  useEffect(() => {
    getHealth()
      .then((r) => setHealth(r.status))
      .catch(() => setHealth("error"));
    getClaudeCheck()
      .then((r) => setClaude(r.reply))
      .catch(() => setClaude("error"));
  }, []);

  return (
    <main style={{ fontFamily: "sans-serif", padding: 24 }}>
      <h1>career-agent</h1>
      <p>
        API health: <span data-testid="health">{health}</span>
      </p>
      <p>
        claude: <span data-testid="claude">{claude}</span>
      </p>
    </main>
  );
}
