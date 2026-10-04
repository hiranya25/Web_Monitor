/* ------------------------------------------------------------------
   AI Website Health Monitor — dashboard logic
   Talks to the FastAPI backend on the same origin:
     POST /audit/run            -> {job_id, status}
     GET  /audit/status/{id}    -> {status, error}
     GET  /audit/latest         -> full AuditResult JSON
--------------------------------------------------------------------- */

const RUNNING_LABELS = [
  "Crawling amipi.com…",
  "Checking links and metadata…",
  "Scanning for missing ALT tags…",
  "Running SEO and performance checks…",
  "Asking Nemotron to prioritize findings...",
];

const els = {
  emptyState: document.getElementById("emptyState"),
  runningState: document.getElementById("runningState"),
  errorState: document.getElementById("errorState"),
  errorMessage: document.getElementById("errorMessage"),
  reportSection: document.getElementById("reportSection"),
  runningLabel: document.getElementById("runningLabel"),
  runAuditBtn: document.getElementById("runAuditBtn"),
  emptyRunBtn: document.getElementById("emptyRunBtn"),
  retryBtn: document.getElementById("retryBtn"),
  runStatus: document.getElementById("runStatus"),
  siteTarget: document.getElementById("siteTarget"),
  downloadPdfBtn: document.getElementById("downloadPdfBtn"),
  emailReportBtn: document.getElementById("emailReportBtn"),
  docsLink: document.getElementById("docsLink"),

  scoreNumber: document.getElementById("scoreNumber"),
  execSummary: document.getElementById("execSummary"),
  lastRun: document.getElementById("lastRun"),
  pagesCrawled: document.getElementById("pagesCrawled"),
  facetFrame: document.getElementById("facetFrame"),

  statCritical: document.getElementById("statCritical"),
  statMedium: document.getElementById("statMedium"),
  statLow: document.getElementById("statLow"),
  statTotal: document.getElementById("statTotal"),

  priorityList: document.getElementById("priorityList"),
  categoryTabs: document.getElementById("categoryTabs"),
  findingsBody: document.getElementById("findingsBody"),
  findingsEmpty: document.getElementById("findingsEmpty"),
};

let currentIssues = [];
let activeCategory = "all";
let labelInterval = null;

const APP_BASE_PATH = (() => {
  const path = window.location.pathname;
  if (path === "/") return "";
  if (path.endsWith("/")) return path.slice(0, -1);
  const lastSegment = path.split("/").pop() || "";
  if (lastSegment.includes(".")) return path.replace(/\/[^/]*$/, "");
  return path;
})();

function apiUrl(path) {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${APP_BASE_PATH}${cleanPath}`;
}

function showOnly(section) {
  [els.emptyState, els.runningState, els.errorState, els.reportSection].forEach((s) => {
    s.hidden = s !== section;
  });
}

function scoreBand(score) {
  if (score === "N/A" || score === null || score === undefined) return "medium";
  if (score >= 80) return "good";
  if (score >= 50) return "medium";
  return "critical";
}

function formatDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short", day: "numeric", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

async function fetchLatestReport() {
  const res = await fetch(apiUrl("/audit/latest"));
  if (!res.ok) throw new Error("No report available yet.");
  return res.json();
}

function renderReport(data) {
  const ai = data.ai_summary || {};
  const score = ai.overall_health_score ?? "—";
  const band = scoreBand(score);

  els.scoreNumber.textContent = score;
  els.facetFrame.closest(".hero__score").setAttribute("data-band", band);
  els.execSummary.textContent = ai.executive_summary || "No summary available for this run.";
  els.lastRun.textContent = `Last run: ${formatDate(data.finished_at)}`;
  els.pagesCrawled.textContent = `${data.pages_crawled} page${data.pages_crawled === 1 ? "" : "s"} crawled`;
  els.siteTarget.textContent = (data.site || "").replace(/^https?:\/\//, "");

  const counts = data.issue_counts || { critical: 0, medium: 0, low: 0 };
  els.statCritical.textContent = counts.critical ?? 0;
  els.statMedium.textContent = counts.medium ?? 0;
  els.statLow.textContent = counts.low ?? 0;
  els.statTotal.textContent = data.issues?.length ?? 0;

  // --- Top priorities ---
  els.priorityList.innerHTML = "";
  const priorities = ai.top_priorities || [];
  if (priorities.length === 0) {
    els.priorityList.innerHTML = `<li class="priority-item"><div class="priority-body"><p class="priority-rec">No priority actions surfaced — nothing urgent this run.</p></div></li>`;
  } else {
    priorities.forEach((p, i) => {
      const li = document.createElement("li");
      li.className = "priority-item";
      li.innerHTML = `
        <span class="priority-index">${String(i + 1).padStart(2, "0")}</span>
        <div class="priority-body">
          <div class="priority-issue">${escapeHtml(p.issue || "")}</div>
          <div class="priority-category">${escapeHtml(p.why_it_matters || "")}</div>
          <div class="priority-rec">${escapeHtml(p.recommendation || "")}</div>
        </div>`;
      els.priorityList.appendChild(li);
    });
  }

  // --- Category tabs + findings table ---
  currentIssues = data.issues || [];
  const categories = ["all", ...new Set(currentIssues.map((i) => i.category))];
  els.categoryTabs.innerHTML = "";
  categories.forEach((cat) => {
    const btn = document.createElement("button");
    btn.className = "tab" + (cat === activeCategory ? " tab--active" : "");
    btn.dataset.cat = cat;
    btn.textContent = cat === "all" ? "All" : cat;
    btn.addEventListener("click", () => {
      activeCategory = cat;
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("tab--active", t.dataset.cat === cat));
      renderFindingsTable();
    });
    els.categoryTabs.appendChild(btn);
  });

  renderFindingsTable();
  showOnly(els.reportSection);
}

function renderFindingsTable() {
  const filtered = activeCategory === "all"
    ? currentIssues
    : currentIssues.filter((i) => i.category === activeCategory);

  const severityOrder = { critical: 0, medium: 1, low: 2 };
  const sorted = [...filtered].sort((a, b) => (severityOrder[a.severity] ?? 3) - (severityOrder[b.severity] ?? 3));

  els.findingsBody.innerHTML = "";
  els.findingsEmpty.hidden = sorted.length !== 0;

  sorted.slice(0, 200).forEach((issue) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="sev-badge sev-${issue.severity}">${issue.severity}</span></td>
      <td class="page-url">${escapeHtml(shortenUrl(issue.page_url))}</td>
      <td>${escapeHtml(issue.message || "")}</td>
    `;
    els.findingsBody.appendChild(tr);
  });
}

function shortenUrl(url) {
  if (!url) return "—";
  return url.replace(/^https?:\/\//, "");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

/* ------------------------------------------------------------------
   Run flow: POST /audit/run -> poll /audit/status/{id} -> fetch latest
--------------------------------------------------------------------- */
async function runAudit() {
  showOnly(els.runningState);
  cycleRunningLabels();
  setButtonsDisabled(true);
  els.runStatus.hidden = false;
  els.runStatus.textContent = "Running…";

  try {
    const startRes = await fetch(apiUrl("/audit/run?send_email=false"), { method: "POST" });
    if (!startRes.ok) throw new Error("Could not start the audit.");
    const { job_id } = await startRes.json();

    await pollJob(job_id);

    const data = await fetchLatestReport();
    renderReport(data);
    els.runStatus.textContent = "Idle";
  } catch (err) {
    showOnly(els.errorState);
    els.errorMessage.textContent = err.message || "Something went wrong while running the audit.";
    els.runStatus.textContent = "Failed";
  } finally {
    setButtonsDisabled(false);
    stopCyclingLabels();
  }
}

function pollJob(jobId, intervalMs = 2000, timeoutMs = 30 * 60 * 1000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      if (Date.now() - start > timeoutMs) {
        reject(new Error("Audit timed out. It may still be running in the background — check back shortly."));
        return;
      }
      try {
        const res = await fetch(apiUrl(`/audit/status/${jobId}`));
        if (!res.ok) throw new Error("Lost track of the audit job.");
        const status = await res.json();
        if (status.status === "done") {
          resolve();
        } else if (status.status === "failed") {
          reject(new Error(status.error || "The audit failed."));
        } else {
          setTimeout(tick, intervalMs);
        }
      } catch (err) {
        reject(err);
      }
    };
    tick();
  });
}

function cycleRunningLabels() {
  let i = 0;
  els.runningLabel.textContent = RUNNING_LABELS[0];
  labelInterval = setInterval(() => {
    i = (i + 1) % RUNNING_LABELS.length;
    els.runningLabel.textContent = RUNNING_LABELS[i];
  }, 3200);
}
function stopCyclingLabels() {
  clearInterval(labelInterval);
}

function setButtonsDisabled(disabled) {
  els.runAuditBtn.disabled = disabled;
  els.emptyRunBtn.disabled = disabled;
  els.retryBtn.disabled = disabled;
}

/* ------------------------------------------------------------------
   Init
--------------------------------------------------------------------- */
els.runAuditBtn.addEventListener("click", runAudit);
els.emptyRunBtn.addEventListener("click", runAudit);
els.retryBtn.addEventListener("click", runAudit);

if (els.downloadPdfBtn) {
  els.downloadPdfBtn.addEventListener("click", () => {
    window.open(apiUrl("/audit/latest/pdf"), "_blank");
  });
}

if (els.emailReportBtn) {
  els.emailReportBtn.addEventListener("click", async () => {
    const btn = els.emailReportBtn;
    const originalText = btn.textContent;
    btn.textContent = "Sending...";
    btn.disabled = true;
    try {
      const res = await fetch(apiUrl("/audit/email"), { method: "POST" });
      if (!res.ok) throw new Error("Failed to send email");
      btn.textContent = "Sent!";
    } catch (err) {
      alert(err.message);
      btn.textContent = originalText;
    } finally {
      setTimeout(() => {
        btn.textContent = originalText;
        btn.disabled = false;
      }, 3000);
    }
  });
}

if (els.docsLink) {
  els.docsLink.href = apiUrl("/docs");
}

(async function init() {
  try {
    const data = await fetchLatestReport();
    renderReport(data);
  } catch {
    showOnly(els.emptyState);
  }
})();
