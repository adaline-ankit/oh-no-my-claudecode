"use strict";

async function renderDashboard() {
  const response = await fetch("/api/dashboard");
  if (!response.ok) throw new Error(`Dashboard request failed: ${response.status}`);
  const payload = await response.json();
  document.title = `${payload.repo.name} | ONMC`;
  document.querySelector("#loading").textContent = `${payload.summary.memories} memories indexed`;
}

renderDashboard().catch((error) => {
  document.querySelector("#loading").textContent = error.message;
});
