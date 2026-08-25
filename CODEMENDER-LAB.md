# CodeMender CI/CD Guardrail — Module 2 Lab

This repository is a hands-on lab: wire **Google CodeMender** into a CI/CD
pipeline as a security guardrail that **scans** for vulnerabilities, **verifies**
whether they are real by **reproducing the exploit** against the running app,
**proposes a fix as a pull request**, and **blocks deployment on HIGH/CRITICAL
bugs**. The target app is **OWASP Juice Shop** (intentionally vulnerable).
CodeMender opens the fix PR, but **a human reviews and merges it** — the gate
stays red until the fix lands on `main`.

➡️ **Students start here:** [`lab/README.md`](./lab/README.md)
➡️ **Instructors / graders:** [`lab/INSTRUCTOR.md`](./lab/INSTRUCTOR.md)

The pipeline lives at
[`.github/workflows/codemender-pipeline.yml`](./.github/workflows/codemender-pipeline.yml).
