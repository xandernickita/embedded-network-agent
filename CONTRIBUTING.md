## Branch model

```
main      ← demo-ready only. Merged from develop at milestones (week 1 query, week 2 benchmarks, final demo).
develop   ← integration branch. Every topic branch merges here through a pull request.
<topic>   ← one branch per piece of work, cut from develop, deleted after merge.
```

Topic branch names say which part of the system they touch:

| Prefix | Use for | Example |
|---|---|---|
| `server/` | C++ agent on the Pi | `server/udp-echo` |
| `client/` | Python CLI and benchmarks | `client/latency-percentiles` |
| `bench/` | Benchmark runs, results, charts | `bench/wifi-vs-ethernet` |
| `deploy/` | Pi setup, systemd, netem scripts | `deploy/systemd-hardening` |
| `docs/` | Protocol contract, decisions, report | `docs/test-plan` |
| `chore/` | Repo plumbing, CI, tooling | `chore/ci` |

Personal scratch branches (`dev/<name>`) are fine for experiments, but nothing merges
from them. Move finished work onto a topic branch first.

## Rules

1. **No direct pushes to `main` or `develop`.** Open a pull request. Solo project, so
   self-review against the PR template checklist instead of a teammate approval.
2. **CI must pass before merge.** It builds the server with warnings as errors, runs the
   C++ unit tests (plain and under AddressSanitizer/UBSan), lints the client with ruff,
   and runs the Python unit and loopback integration tests.
3. **Pick the merge method by target branch.**
   - Topic branch → `develop`: **Squash and merge**, so `develop` reads as one commit per feature.
   - `develop` → `main`: **Create a merge commit**, never squash. Squashing copies develop's
     changes onto `main` as a new, unrelated commit, so the two branches stop sharing history
     and every later release PR re-applies old work (this happened once: PRs #2, #4, fixed by #5).
   - `develop` is the default branch, so new PRs target it automatically. Check the base
     dropdown anyway before opening one.
4. **Change the contract first.** If a message shape changes, edit `docs/PROTOCOL.md`
   in the same pull request as the server and client change.
5. **Never commit secrets or raw captures.** Wi-Fi passwords, SSH keys and `.env` files
   stay out of git. Large `.pcap` captures stay out too; commit the CSV summaries.

## Commit messages

`<area>: <what changed, lower case, present tense>` — the same style as IRIS.

```
server: poll loop handles partial frames and idle timeouts
client: udp-bench reports p50/p95/p99 and reorder count
```

## Getting started

```bash
git clone https://github.com/xandernickita/embedded-network-agent.git
cd embedded-network-agent
git switch develop
git switch -c server/my-change
```

See `README.md` for build and run steps.
