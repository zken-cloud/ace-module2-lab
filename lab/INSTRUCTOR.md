# Instructor Guide — CodeMender CI/CD Guardrail (Module 2)

Everything you need to deploy this lab to students and grade it. Student-facing
instructions are in [`README.md`](./README.md).

This lab is a **scan → verify → fix → PR → gate** guardrail: CodeMender scans,
**reproduces the exploit** to confirm which findings are real, **generates a fix
and opens a pull request**, and blocks deployment until the fix lands. CodeMender
proposes the change; **a human reviews and merges** it.

---

## 0. What's in the repo

| Path | Purpose |
|---|---|
| `.github/workflows/codemender-pipeline.yml` | The guardrail pipeline (provided, working) |
| `.github/scripts/cm_triage.py` | Parses `cm report -f json` → severity counts + gate decision + the top-N findings to verify (`VERIFY_LIMIT`, default 1; fed to the script via `CM_FIX_LIMIT`) |
| `.github/scripts/cm_select.py` | Filters the report by finding status (VERIFIED / DISMISSED / not:DISMISSED), reusing `cm_triage`'s parser |
| `.github/scripts/extract_cm_diff.py` | **Unused** — the fix step applies `cm fix`'s changes straight from the working tree, so this stdout-diff parser isn't needed; kept for reference only |
| `lab/README.md` | Student lab guide |
| `lab/INSTRUCTOR.md` | This file |
| `lab/publish-cm-release.sh` | **Legacy** — published `cm` as a per-repo Release; unused now that CI pulls `cm` from Artifact Registry |

The target app is **OWASP Juice Shop**, imported as a single clean commit. The
16 upstream Juice Shop workflows were removed so the Actions tab shows **only**
the CodeMender guardrail.

---

## 1. The one non-obvious dependency: GCP access

The workflow installs `cm` from Google's **Artifact Registry** and runs it
against **Vertex AI**, so **every student repo needs a Google Cloud identity**.
You provide it as two repository secrets (students paste the values you hand out):

- **`GCP_SA_KEY`** — a **service-account JSON key**. The SA must have **read** on
  the `cmoc-prod` / `codemender-cli-production` Artifact Registry repo (the `cm`
  download) **and** CodeMender / `aiplatform` access on the entitled project.
- **`CM_PROJECT`** — the **CodeMender-entitled project id** (`<CM_PROJECT>`).
  Only a project entitled to CodeMender works; a non-entitled project returns
  `403 Unsupported agent interaction`.

**Do not mint one JSON key and hand it to the whole cohort.** A long-lived key
shared by every student cannot be attributed or revoked per person, and it will
leak. Prefer, in this order:

1. **Workload Identity Federation** — let each student repo's GitHub Actions
   OIDC token impersonate the SA (`google-github-actions/auth` with
   `workload_identity_provider` + `service_account`, scoped to the student's
   repo). No key exists at all. This needs the "Authenticate to Google Cloud"
   step swapped for that action and `id-token: write` in `permissions`.
2. **Per-student short-lived credentials** — one SA (or one key) per student,
   issued for the class window and deleted afterwards, so each `GCP_SA_KEY` is
   individually revocable.

Either way, the "Authenticate to Google Cloud" step (as shipped, or swapped for
the WIF action) is what exposes the identity to both `gcloud` (the download) and
ADC (cm's Vertex AI calls). If a cohort-wide key was ever distributed, delete/rotate it now. No
per-repo release to publish, and the built-in `GITHUB_TOKEN` is only used to
open the fix PR.

> **Confirm access before class:** the `cmoc-prod` download repo is gated to
> preview-entitled identities. Verify your SA can actually pull the binary —
> `gcloud artifacts generic download --project=cmoc-prod --location=us
> --repository=codemender-cli-production --package=cm --version=stable
> --name=cm-linux-amd64.zip --destination=.` while authenticated as the SA — and
> that `CM_PROJECT` is entitled, before handing the secrets out.

---

## 2. Per-repo setup checklist

For **each** repo students will use (or the template before distribution):

- [ ] Give students the **`GCP_SA_KEY`** (service-account JSON) and **`CM_PROJECT`**
      (entitled project id) values; they add both as repo secrets themselves.
- [ ] Enable **Allow GitHub Actions to create and approve pull requests**
      (**Settings → Actions → General → Workflow permissions**) so the fix PR can
      be opened.
- [ ] (Optional) Branch protection on `main` so the red gate actually blocks
      merges — makes the "deployment blocked" outcome tangible, and makes the fix
      PR the path back to green.

> **Workflow-permissions toggle IS required.** The pipeline opens a fix PR with
> the built-in `GITHUB_TOKEN`, so **Settings → Actions → General → Workflow
> permissions** must have **"Allow GitHub Actions to create and approve pull
> requests"** enabled. The workflow requests `contents: write` +
> `pull-requests: write`; without the repo toggle, the "Open Remediation PR" step
> errors.

> **Heads-up on shared quota:** the whole cohort runs against one entitled
> project (`CM_PROJECT`) via the shared service account, so they share its
> server-side quota. For a large cohort, expect occasional `RESOURCE_EXHAUSTED`;
> have students stagger runs or retry.

---

## 3. Grading rubric

One push to `main` (or a manual dispatch) should produce all four artifacts. Map
each criterion to concrete, checkable evidence:

| # | Criterion | Pass evidence | Points |
|---|---|---|---|
| 1 | **Workflow execution** | Actions run exists; "Install CodeMender CLI" + "Initialize CodeMender Workspace" + "CodeMender Scan" steps are green (clean install & auth) | 20 |
| 2 | **Pipeline gating (fail-safe)** | The run is **red** because of the **"Security Gate"** step (`::error ::Deployment blocked … HIGH/CRITICAL`). A *red from an earlier crash* does **not** count | 20 |
| 3 | **Artifact generation** | Run **Summary → Artifacts** has **`codemender-report`** containing `cm-security-report.json`, and it's non-empty JSON | 20 |
| 4 | **Vulnerability verification** | The **"Verify Findings"** step ran `cm verify` against the triaged finding(s): its log shows the app **starting** (e.g. `node build/app.js`) and **exploit attempts** against `localhost:3000` (e.g. a confirmed SQL-injection or Zip-Slip), and the job **Summary → "CodeMender Verify"** reports a verdict (VERIFIED / DISMISSED / inconclusive). Grade on the verify step **attempting a real reproduction** — a firm `VERIFIED` stamp is *not* required (see §4). | 20 |
| 5 | **Autonomous remediation** | The **"Remediate Findings"** step ran `cm fix`, and the **"Open Remediation PR"** step opened a **`codemender/fix-…`** pull request whose diff patches the finding(s). Grade on a PR being opened with a **real code diff** (job **Summary → "CodeMender Remediation"** links it) — a perfectly correct patch is *not* required. | 20 |

**Fast grading path:** open the run's **Summary** page — the "CodeMender Triage"
table shows severity counts and the finding chosen for verification, the
"CodeMender Verify" section shows the verdict, the "CodeMender Remediation"
section links the fix PR, and the Artifacts section has the report + the
`codemender-verify-logs` / `codemender-fix-logs` transcripts.

### Verify it via CLI (optional, for a TA)

```bash
R=<owner>/<repo>

# 1 & 2: latest run conclusion + that the Gate step failed
gh run list --repo "$R" --workflow "codemender-pipeline.yml" -L 1 \
  --json databaseId,conclusion,headBranch
RID=$(gh run list --repo "$R" -L 1 --json databaseId --jq '.[0].databaseId')

# 3: report artifact present
gh api "repos/$R/actions/runs/$RID/artifacts" --jq '.artifacts[].name'   # → codemender-report, codemender-verify-logs

# 4: the Verify step ran and attempted a reproduction
gh run view "$RID" --repo "$R" --log \
  | grep -E 'Verify Findings' | grep -iE 'localhost:3000|VERIFIED|DISMISS|Verified [0-9]+ / dismissed|confirmed' | head

# 5: a remediation PR was opened on a codemender/fix-* branch
gh pr list --repo "$R" --state all --json headRefName,url,createdAt \
  --jq '.[] | select(.headRefName|startswith("codemender/fix")) | .url'
```

---

## 4. Expected findings (so you know what "correct" looks like)

Scanning `routes/` reliably yields **~9–13 HIGH/CRITICAL** findings. The exact
set + ranking vary (server-side, non-deterministic); the pipeline verifies the
top **N** (default 1, `VERIFY_LIMIT`). The common ones:

- **SQL injection** in `routes/login.ts` / `routes/search.ts` — a string-built
  `sequelize.query(...)`. Verify confirms it by logging in with an `' OR 1=1 --`
  payload against the running app. This is the **fastest to verify** — set
  `SCAN_PATH=routes/login.ts` if you want a reliable, quick VERIFIED for a demo.
- **File-upload** XXE / Zip-Slip / YAML-DOS in `routes/fileUpload.ts` — verify
  uploads a crafted `.zip` / `.yaml` and checks for the traversal / RCE. These are
  the **slowest** to verify (the exploit loop is long) and most likely to land
  *inconclusive* if they hit the time-box.

**On verdicts:** `cm verify` is a slow, server-side agent that *runs* the app
and attacks it. A finding can have its exploit reproduced but still not finalize a
`VERIFIED` status within `PER_VERIFY_TIMEOUT` (default 2700s), landing as
**inconclusive**. The gate blocks on anything **not explicitly DISMISSED**, so an
inconclusive verify still fails the pipeline correctly. Grade criterion 4 on the
verify step **doing real work** (booting the app, firing exploits), not on the
label. `VERIFY_LIMIT` controls how many findings each run verifies (1 = minimal
lab; raise it and expect proportionally longer runs).

**Remediation targets** every **un-dismissed** finding (VERIFIED + inconclusive) —
the same set the gate blocks on — so a fix PR appears even when a verdict lands
inconclusive. `cm fix` writes its patch into the working tree and the "Open
Remediation PR" step commits everything except `node_modules` / a generated
`package-lock.json` onto the `codemender/fix-<run id>` branch.

---

## 5. Resetting between attempts

Each run opens a **`codemender/fix-<run id>`** branch and a PR. The branch name is
keyed to the run id, so reruns don't collide — but close the stale PRs between
attempts to keep the repo tidy:

```bash
gh pr list --repo <owner>/<repo> --state open
gh pr close <N> --repo <owner>/<repo> --delete-branch
```

Then re-run the workflow (Actions → **Run workflow**, or push a commit). Each run
is independent; findings, verdicts, and the generated patch will vary
(server-side non-determinism).

---

## 6. Cost / safety notes

- `cm find` / `cm verify` / `cm fix` **upload source** to Google and let a
  server-side agent run sandboxed shell commands on the runner — and **verify and
  fix start the app and attack it**. Fine for Juice Shop (open source); communicate
  this to students as a real property of cloud AI security tools.
- GitHub-hosted runner minutes: a full run installs the app and runs a slow
  server-side verify **and fix**, so **30–90 minutes** is typical (job timeout
  150 min). Budget accordingly for large cohorts, and keep `VERIFY_LIMIT` at 1
  unless you need more.
