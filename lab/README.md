# Module 2 Lab — CodeMender CI/CD Guardrail

Build a **security guardrail** into a CI/CD pipeline. When code is pushed, Google
**CodeMender** (the `cm` CLI) scans it, **verifies** whether the findings are real
by **reproducing the exploit** against the running app, publishes a
machine-readable report, **opens a pull request with CodeMender's fix**, and
**blocks the deployment** until a confirmed HIGH/CRITICAL vulnerability is
resolved. You stay in control — **a human reviews and merges** the fix PR.

Your target application is **OWASP Juice Shop** — a deliberately vulnerable web
app. CodeMender will surface several HIGH/CRITICAL bugs in `routes/` (SQL
injection, file-upload XXE / Zip-Slip, …), **prove** the top one is exploitable,
then **generate and build-test a patch** and open it as a PR.

---

## What you'll learn

- How an AI security agent (CodeMender) is wired into GitHub Actions as a
  **deployment gate**.
- The real CodeMender pipeline: `find` (scan) → `report` → **`find verify`**
  (reproduce the exploit).
- Provisioning and using **CI secrets** safely.
- **Fail-safe gating**: turning a scan result into a red/green deploy decision.
- **Vulnerability verification**: proving a finding is *real* (not a false
  positive) by building the app and firing a proof-of-concept exploit at it.
- **Autonomous remediation**: letting CodeMender generate and build-test a patch,
  then open a **pull request** you review and merge.

## How CodeMender actually works (read this first)

CodeMender is a **cloud service with a local executor**, not an on-device
scanner. The `cm` binary is a thin client:

- `cm find` **uploads your in-scope source** to CodeMender on Vertex AI
  (`aiplatform.googleapis.com`), where a server-side AI agent reasons about
  vulnerabilities.
- `cm verify <id>` runs the server-side agent again, but this time it
  **builds and RUNS the app on the CI runner** and fires a proof-of-concept
  exploit at it — so it needs the app's dependencies installed (the pipeline runs
  `npm install` for exactly this). The finding's status becomes **VERIFIED**
  (real) or **DISMISSED** (false positive).
- `cm fix <id>` generates a patch, **build-tests it, and re-runs the exploit** to
  confirm the fix holds — writing the change into the working tree. The pipeline
  collects those changes onto a branch and opens a **pull request** for review.

Practically:

- **Your code leaves the machine.** Only point `cm` at code you're allowed to
  share. (Juice Shop is open source, so we're fine.)
- Findings are stored locally in `~/.codemender/` and read back with `cm report`.
- The scan is scoped to **`routes/`** in this lab — small (well under cm's ~10 MB
  per-scan upload limit) and home to the login SQL injection.

---

## Prerequisites

This repository is your lab template. It already contains:

- `.github/workflows/codemender-pipeline.yml` — the guardrail workflow.
- `.github/scripts/cm_triage.py` — turns the JSON report into severity counts,
  the gate decision, and the top-N findings to verify.
- `.github/scripts/cm_select.py` — filters the report by finding status
  (VERIFIED / DISMISSED).
- The `cm` binary is **downloaded in CI from Google's Artifact Registry**
  (`gcloud artifacts generic download`), authenticated with the `GCP_SA_KEY`
  service account — no per-repo release to publish.

> If you're an instructor setting this up for students, see
> [`INSTRUCTOR.md`](./INSTRUCTOR.md) first — there's per-repo setup (the `cm`
> release) that must be done before students start.

---

## Step 1 — Initialize the work environment

1. Open your copy of this repository on GitHub.
2. Confirm the workflow directory exists and contains the pipeline:

   ```
   .github/
     workflows/
       codemender-pipeline.yml
     scripts/
       cm_triage.py
       cm_select.py
   ```

   That's the GitHub Actions structure GitHub auto-discovers — any `*.yml` under
   `.github/workflows/` becomes a pipeline.

## Step 2 — Provision the secrets

The pipeline authenticates to Google Cloud with a **service-account key** and
runs against a **CodeMender-entitled project** — your instructor provides both.
Add them under **Settings → Secrets and variables → Actions → New repository
secret**:

1. **`GCP_SA_KEY`** — the service-account JSON key.
   **→ Ask your instructor for the service account key**, then paste the entire
   JSON as the secret value.
2. **`CM_PROJECT`** — the Google Cloud project id.
   **→ Ask your instructor for the project id** (it must be the preview-entitled
   project).

> The service account authenticates both the `cm` binary download (from Google's
> Artifact Registry) and CodeMender's Vertex AI calls at runtime; `CM_PROJECT`
> selects the entitled project the scan / verify / fix run against.

One more repo setting is required, because the pipeline opens its fix PR with the
built-in `GITHUB_TOKEN`: go to **Settings → Actions → General → Workflow
permissions** and enable **"Allow GitHub Actions to create and approve pull
requests."** The workflow already requests `contents: write` +
`pull-requests: write`; without this repo toggle, the "Open Remediation PR" step
fails with *"GitHub Actions is not permitted to create or approve pull
requests."*

## Step 3 — Understand the guardrail

Open `.github/workflows/codemender-pipeline.yml`. It runs on every push to `main`
(and on manual dispatch). The steps map directly onto real `cm` commands:

| Stage | Command | What it does |
|---|---|---|
| **Authenticate** | `gcloud auth activate-service-account` | Activates the `GCP_SA_KEY` service account for `gcloud` (download) + exports it as ADC for `cm` (Vertex AI) |
| **Install cm** | `gcloud artifacts generic download` | Pulls the `cm` binary from Google's Artifact Registry (`cmoc-prod`) |
| **Install app** | `actions/setup-node` + `npm install` | Installs Juice Shop's dependencies so `cm verify` can **run** the app |
| **Init** | `cm init` | Mints the local CodeMender identity key |
| **Scan** | `cm find routes -y` | Uploads `routes/` and runs the server-side scan |
| **Report** | `cm report -f json` | Exports findings → uploaded as the **`codemender-report`** artifact |
| **Triage** | `cm_triage.py` | Counts HIGH/CRITICAL, ranks them, selects the top **N** (`VERIFY_LIMIT`, default 1) to verify |
| **Verify** | `cm verify <id>` (looped over top-N) | **Reproduces the exploit** against the running app; marks each finding VERIFIED or DISMISSED |
| **Fix** | `cm fix <id>` (looped over un-dismissed) | Generates + build-tests a patch, writing the change into the working tree |
| **Open PR** | `git push` + `gh pr create` | Commits the patches to a `codemender/fix-<run id>` branch and opens **one PR** for review |
| **Gate** | (exit 1 if un-dismissed HIGH/CRITICAL) | Turns the run **red** and blocks deployment until the fix is merged |

> **Why no `--fail-on=high,critical` flag?** The real `cm` has no such flag — a
> scan exits `0` whether or not it finds bugs. The **gate is something *you*
> build**: parse `cm report -f json` and fail the job on HIGH/CRITICAL. That's the
> `cm_triage.py` + "Security Gate" steps. This is the real, transferable pattern
> for wiring any scanner into a pipeline.

> **Why install the app?** Verification isn't static — CodeMender *runs* the app
> and attacks it. Without `npm install`, `cm verify` can't start the app, so
> it comes back inconclusive. Note the pipeline deliberately leaves `cm`'s git VCS
> **unconfigured**: a `git clean` reset would wipe `node_modules` before verify
> could use it.

## Step 4 — Trigger and test the agent

Trigger a run any of these ways:

- **Manual — UI (easiest):** **Actions** tab → **CodeMender CI/CD Guardrail** in
  the left sidebar → **Run workflow** ▸ → choose `main` → optionally set
  **`verify_limit`** → **Run workflow**. This is the `workflow_dispatch` trigger.
- **Manual — CLI:** with the [GitHub CLI](https://cli.github.com):
  ```bash
  gh workflow run codemender-pipeline.yml --repo <owner>/<repo> --ref main -f verify_limit=1
  ```
- **Push:** commit anything to `main` — the `on: push` trigger fires automatically.

> **`verify_limit`** controls how many of the top-ranked findings get verified
> (default **1**). Verification is slow — it builds and runs the app and fires
> exploits — so keep it low; each finding can take many minutes.

Then open the **Actions** tab and watch the run. Expect it to:

1. Install `cm`, install the app's dependencies, and initialize cleanly.
2. Scan `routes/` and surface multiple **HIGH/CRITICAL** findings (e.g. SQL
   injection in `routes/login.ts` / `routes/search.ts`, file-upload XXE / Zip-Slip
   in `routes/fileUpload.ts`).
3. Upload the `codemender-report` artifact.
4. **Verify** the top finding(s): boot Juice Shop and fire a proof-of-concept
   exploit — the **"Verify Findings"** step log shows the app starting and the
   exploit attempts, and the job **Summary** shows a **"CodeMender Verify"**
   section with the VERIFIED / DISMISSED / inconclusive tally.
5. **Remediate**: `cm fix` patches the un-dismissed finding(s), and the pipeline
   opens a **`codemender/fix-…` pull request** carrying the diff (the
   **"CodeMender Remediation"** summary links it).
6. **Fail red** at the Security Gate (correct — `main` stays blocked until the
   fix PR is reviewed and merged).

---

## ✅ Success criteria (what you must demonstrate)

| # | Criterion | Where the evidence is |
|---|---|---|
| 1 | **Workflow executes** — clean `cm` install + init | Actions run log: "Install CodeMender CLI" + "Initialize CodeMender Workspace" steps green |
| 2 | **Pipeline gating (fail-safe)** — a HIGH/CRITICAL bug turns the run red and blocks deploy | Run is **red**; "Security Gate" step shows `error::Deployment blocked` |
| 3 | **Artifact generation** — `codemender-report` with `cm-security-report.json` | Run **Summary** → Artifacts → `codemender-report` (downloadable) |
| 4 | **Vulnerability verification** — `cm verify` reproduces the exploit against the running app | "Verify Findings" step log shows the app booting + exploit attempts (e.g. a confirmed SQL-injection or Zip-Slip); the job **Summary → "CodeMender Verify"** reports the verdict, and the `codemender-verify-logs` artifact holds the full transcript |
| 5 | **Autonomous remediation** — `cm fix` produces a patch and the pipeline opens a PR | A **`codemender/fix-…`** branch and an open **pull request** whose diff patches the finding; the "Open Remediation PR" step log (and job **Summary → "CodeMender Remediation"**) shows the PR URL |

The job **Summary** also shows a "CodeMender Triage" table (severity counts + the
finding selected for verification) — a quick at-a-glance for grading.

> **Verdicts vary — that's expected.** Verification is a slow, server-side agent
> loop; a complex finding may reproduce its exploit but not finalize a `VERIFIED`
> stamp within the time-box, and land as *inconclusive*. The gate treats anything
> **not explicitly DISMISSED** as still-blocking, so an unfinished verify never
> lets a real vulnerability through. Criterion 4 is satisfied by the verify step
> **running and attempting a real reproduction**, not by a guaranteed green stamp.

---

## Part B (exploration) — observe the non-determinism

CodeMender runs **server-side**, so both the scan and the verification are
*probabilistic*: the exact set of findings, which one ranks #1, and whether a
given verify reaches a firm verdict can shift between runs. Make that visible:

1. Trigger the pipeline **3 times** (Actions → **Run workflow**, or push small commits).
2. From each run's **Summary**, download the **`codemender-report`** artifact and
   read the **"CodeMender Verify"** summary.
3. Compare them — note how the finding count, severities, the finding chosen for
   verification, and the verdict (VERIFIED / DISMISSED / inconclusive) vary
   run-to-run.

**Reflect:** why does an AI security agent return different results on identical
code? What does that imply for using one as a *blocking* deployment gate?
> Hint: the gate keys off **severity counts minus dismissed findings**, not a
> specific finding or a firm verdict — so it stays reliable as a fail-safe even as
> individual findings and verify outcomes shift.

## Troubleshooting

- **`Authenticate to Google Cloud` fails / `PERMISSION_DENIED` on the download**
  → the `GCP_SA_KEY` secret is missing, malformed, or its service account can't
  read the Artifact Registry download repo, or `CM_PROJECT` is wrong. Ask your
  instructor (see `INSTRUCTOR.md`).
- **"GitHub Actions is not permitted to create or approve pull requests"** → the
  "Open Remediation PR" step can't open the PR. Enable the repo toggle from Step 2
  (**Settings → Actions → General → Workflow permissions**).
- **Run is green with 0 findings** → the scan didn't surface a HIGH/CRITICAL.
  Confirm `SCAN_PATH` is `routes` and that `routes/login.ts` still contains the
  string-built SQL query. (CodeMender runs server-side, so exact findings can vary
  run-to-run.)
- **Verify is "inconclusive" / hit the time-box** → normal for complex findings;
  the agent runs a long exploit loop. The finding stays blocking. Lower
  `verify_limit`, or set `SCAN_PATH` to a single file (e.g. `routes/login.ts`) so
  the top finding is the simpler SQL injection, which verifies faster.
- **`RESOURCE_EXHAUSTED` / quota errors** → the whole cohort shares one entitled
  project (`CM_PROJECT`); stagger your runs or retry.
- **Run takes a while** → `cm find` is a multi-round server-side agent, and
  `cm verify` additionally builds and runs the app; **20–45 minutes** is
  normal. The job timeout is 90 minutes.

## Caveats to understand

- `cm find` / `cm verify` **upload source** to Google. Fine for Juice Shop;
  never point it at code you can't share.
- During a scan or verify, the server-side agent can run shell commands **on the
  runner** (inside a path sandbox) — and verify **starts the app and attacks it**.
  That's expected CodeMender behavior.
- This lab scans only `routes/`. Scanning the whole repo would exceed cm's ~10 MB
  upload limit and need chunking — out of scope here.
- This guardrail **proposes** code changes as a pull request (via `cm fix`) but
  never merges them — a human reviews and merges. It detects, confirms, patches,
  and blocks; the deploy stays blocked until the fix lands on `main`.
