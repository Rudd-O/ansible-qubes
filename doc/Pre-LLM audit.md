# `bin/bombshell-client` — open items from the pre-LLM audit

**What this file is now.** This file used to hold the full pre-LLM audit of
`bin/bombshell-client`: purpose and execution model, the background-`tail -F`
incident, a 22-item line-numbered bug/corner-case review, the corner-case matrix,
ranked fix directions, and the post-audit design follow-up that produced the
threadless specification. Those recommendations **were implemented** — per
`docs/specs/Threadless algorithm.md` (decision IDs D1–D5, background and defect
classes B1–B12 restated there in §1.2/§1.3) — as the single-file threadless
rewrite now in `bin/bombshell-client` (2026-10-23, commit `6720aea`; wire format
byte-identical). A same-day follow-up, `4a2014f`, tightened the status convention:
a signalled process now reports the shell convention **128+signum** (130/137),
converted once at the single exit boundary (`_shell_status`, spec §7/§11.2), and
this file's open sections were re-checked against that commit. The full historical
analysis is recoverable from this file's git history through the threadless
commit (superseded pre-amend version `1697697`).

This file keeps only what that audit leaves **open**: recommendations never
implemented, gaps found while re-auditing the threadless implementation,
accepted-behavior records, and legacy notes the rewrite deliberately carried
over. Status key:

* **[O]** open work — recommended, not implemented;
* **[G]** gap in the committed implementation — the case exists, no policy row for it;
* **[A]** accepted behavior — a decision on record, not a defect;
* **[H]** hygiene — retained legacy, harmless, worth cleaning when convenient.

`B<n>` and `D<n>` below refer to the defect classes and adopted decisions defined
in the spec (§1.3, §1.2). The spec is the single source of truth for everything
implemented.

---

## 1. Disposition of the original recommendations

| Original item | Outcome |
|---|---|
| §7.5 recorded decisions (five) | Absorbed verbatim into the spec as **D1–D5** (§1.2) and implemented. |
| §5.1 the remote's `muxer.join()` block | Absorbed: nothing is joined; the loop ends on P5/P6 (incident regressions: local T3, Qubes T8). |
| §5.2 process-group kill on teardown | **Reversed** — no `killpg` anywhere (D1; spec §9.2); `start_new_session=True`; descendants are orphaned, never killed. |
| §5.3–§5.6 per-sink `EPIPE`, EOF/short-write plumbing, real framing loops, crash-path restriction | Absorbed by construction: P9/P15/P16/P12 per-sink demotion, the frame accumulator (spec §2.3), real partial-write loops (§4.2/§4.3), one `_main()` handler (no `os._exit`). |
| §5.7 winsize / SIGWINCH relay | **Open** — §2.1 below. |
| §5.8 shell one-liner acceptance | **Open** — §2.2 below. |
| §5.9 remove-or-wire the vestigial `-s` branch | Resolved: `-s` is wired as the remote-role entry point the local suites use (spec §11.1). Residue: the `-d` parse asymmetry, §3.3 below. |
| §5.10 document the handshake invariant | Done: spec §2.1; the single-threaded remote makes the invariant structural. |
| §7.1–§7.4 design follow-up (threaded companion set, waitable-end sketch, readiness design) | The waitable-end shape is the spec (§4.5, §5.2, §6.2). The readiness design's per-sink open/closed tables (gap A) arrived as `live_out`/`in_live` + demotion; its gap C (the only proposed wire change — **P2**, below) is the one piece left open, by decision. |

---

## 2. Open work **[O]**

### 2.1 WINSIZE / TTY geometry — the "pty work" family

* **No SIGWINCH relay, no `TIOCGWINSZ`/`TIOCSWINSZ`**: the remote child inherits the
  channel end's default geometry (typically 80×24). Full-screen programs in the
  remote (`less`, `top`, `vi`) never relayout on a local resize;
  `remote echo $COLUMNS` disagrees with the local terminal. (Matrix row 8.)
* **Local TTY modes are not mirrored** — cooked/raw, echo, `stty -a`: only the fixed
  signal list is relayed; mode changes on the local side do not affect the remote
  child (and vice versa).
* **GUI applications are not reachable at all** over the channel — no X11/Wayland
  forwarding, no `/dev/tty` on the wire. (Matrix row 22.)

All three are one feature family, not three bugs: a winsize handshake at session
start + SIGWINCH relay + mode mirroring (and pty plumbing behind it, which also
changes the orphan-failure profile that spec §9.2 parks on). Revisit together.

### 2.2 Shell one-liner acceptance

The command list is exec'ed **verbatim** — there is no shell involved.
`bombshell-client <vm> "ls -la /tmp"` fails with confirmation `127`
("cannot execute `ls -la /tmp`": one argv element), because the quoted string is
one word. Users must either split words (losing pipes/redirects) or wrap explicitly
(`bash -c '...'`) — the wrapping form being exactly the shape that fed the original
incident. The original audit called this the single largest user-confusion source
(matrix row 15).

Candidate fixes (wire-neutral UX change, no spec section yet): wrap in
`["bash", "-c", shlex.join(cmd)]` when the argv looks like a one-liner, or an
explicit `--shell` flag that opts into it.

### 2.3 Signal relay: whitelist gaps, receiver validation, startup window

* **Whitelist gaps [O]:** `HANDLED_SIGNALS` is the pre-rewrite eight-signal tuple kept
  verbatim (spec §4.6, by design). `SIGQUIT` (Ctrl-\) and `SIGHUP` are **not**
  relayed: Ctrl-\ kills the local bombshell instead of aborting the remote child
  (matrix row 7). Extending the whitelist means both ends move together.
* **No signum validation at the receiver [G→O]:** remote P11 does
  `p.send_signal(struct.unpack("!H", body))` on whatever the channel carries
  (spec §3.3). The master only emits whitelisted signums today, but the remote
  would honor e.g. `9` (SIGKILL on the child) or `0` from a corrupt or hostile
  frame. Suggested fix: validate `0 < signum < 32` (or membership in a shared
  whitelist) before `send_signal`.
* **Startup window [G — no policy]:** the relay handlers are installed only **after**
  a clean confirmation (spec §6.1 step 9 — intentional, matching the pre-rewrite
  order). A SIGINT between proxy spawn and confirmation hits the master with the
  default disposition: the master dies; its `qrexec-client-vm` child (its own
  process group, `preexec_fn=os.setpgrp`) survives holding the channel; the remote
  session and child keep running until that orphaned proxy dies — the matrix-row-21
  triangle through the startup path. The window now spans bootstrap only (no prompt
  is up yet), but spec has no row describing what is acceptable there.

### 2.4 Interactive session end with live descendants (P2)

D1 closed the incident in its blunt form: abandon, don't drain — descendants
EPIPE or linger (spec §9.2). The *polite* variant — the master telling the user
"child exited; the rest of its streams still hold the pipes; hang up, or keep
reading for T seconds" — was designed in the pre-LLM audit's §7.3 follow-up as
**gap C**: one extra `PACKFORMAT b` value (the only wire change ever proposed for
this program), riding on the per-sink readiness tables that the rewrite already
brought (`live_out`/`in_live` + P9/P15/P16 demotion). D1 explicitly leaves P2
**open**; it is deferred with the pty work (§2.1), because the prompt's UX depends
on where the pipes are held (pty vs. plain pipe changes the failure profile).

---

## 3. Gaps in the committed implementation **[G]**

### 3.1 The orphaned proxy after a killed master

`kill -9` on the master (or any master crash before P17) orphans the
`qrexec-client-vm` proxy in its own process group. It keeps the qrexec channel
open, so the remote session — child alive, stdin open — keeps running until the
proxy dies, at which point it ends cleanly (the P6 path; T10 proves the remote
half). Nobody reaps or kills the proxy: it is no longer anyone's child, so
dom0-side cleanup is manual (`pkill qrexec-client-vm` / `qvm-kill`). Same shape as
matrix row 21. §9.2's orphan decision covers the *remote child's* descendants; the
proxy side has no stated policy. One line — or a test — is due when the pty work
lands.

### 3.2 Exit-code discipline (minor)

* The remote still lumps `OSError` → **127** (ENOENT *and* EACCES indistinguishable)
  and other `BaseException` → **126** (pre-rewrite coarse distinction, matrix row 3;
  unchanged by design — spec §5.1 step 5).
* 125/126/127 are bare literals in both roles; no named constants.
* A garbage VM name exits with a clean **125** — the EOF-before-confirmation path
  (spec §3.4 "Domain absent", §6.2; pinned locally by M4 "refused-domain-125").
  The pre-rewrite row-24 observation (raw proxy status in place of 125) no longer
  applies to the committed code: the only other confirmation-phase exit is an
  early-proxy-death status (spec §6.4 D), signalled deaths from it included
  (§4, first item). The qrexec error text still prints raw nonetheless — the
  proxy's stderr is inherited (the "noisily" half of row 24).

### 3.3 CLI parse asymmetry (minor)

* `-d` is **positional** on the master (`args[0] == "-d"`) but **anywhere in argv**
  on the remote (`"-d" in sys.argv[1:]`). `bombshell-client <vm> -d <cmd>` is
  mis-parsed by the master (it becomes part of the command; the remote then fails
  with "cannot execute: -d", code 127), while `bombshell-client -d <vm> <cmd>`
  works. Carried over from the pre-rewrite parse; spec §6.1 step 1 keeps it
  verbatim on purpose, so a fix is a new decision, not a fix.
* `-s` is honored only at `sys.argv[1]` (the dispatch check is
  `"-s" in sys.argv[1:2]`); a later position is silently ignored.

---

## 4. Accepted behavior — decisions on record **[A]**

* **Orphans persist.** Descendants are never `killpg`'d; they EPIPE at their next
  write or linger (D1; spec §9.2). The Qubes matrix deliberately leaves
  `tail -F` / `sleep 300` remnants in the test VM; the suites never clean them.
* **Signal-death statuses follow the shell convention (128+signum).** Decision of
  record from `4a2014f`: a CPython wait status for a signalled process is negative
  (−signum) and, left raw, would surface as `(-N) & 0xFF = 256−N` (247 for SIGKILL,
  254 for SIGINT) — un-decodable by any caller. The implementation converts it
  **once, at the single exit boundary** (`_shell_status`, spec §7), and every exit
  path converges there — remote P5, master P17/P18, confirmation-phase
  early-proxy-death (spec §6.4 D). Accepted on both ends; the spec's §11.2 status
  note and the `tests/qubes_probe.py` / `tests/master_probe.py` headers record
  the values; the suites assert 130/137 **strictly** (the old un-converted
  247/254 readings can no longer occur and are failures), and the new local case
  `tsig` (`kill -9 $$` → 137) pins the convention without Qubes.
* **Backpressure has no timeouts.** Blocking writes + finite channel buffers: a
  permanently stuck local reader stalls the whole session (matrix row 25).
  Deliberate — the loops carry no `select` timeouts by design (D2).
* **Stream separation is incidental.** The local stdout/stderr sinks default to
  two handles of the *same* TTY fd; point the session's stdio elsewhere and the
  re-segregation follows the fds silently (pre-rewrite §3.10's first criticism —
  kept, though it is now single-writer-per-fd by construction).

---

## 5. Retained legacy hygiene **[H]**

* **The fd re-wrap helpers** (binary lines 35–55: `unset_cloexec`,
  `openfdforappend`, `openfdforread`; used at 391 — the master's `saved_stderr` —
  and 552–553 — the module-level `sys.stdin`/`sys.stdout` re-wrap at import time):
  `openfdforappend` still catches the legacy alias `IOError`, opens `"ab"` with an
  `ESPIPE` fallback into `"wb"` — which mode results depends on the runtime
  class of the fd (nobody trips on it because none of the actual consumers — a
  TTY, a pipe, a qrexec channel fd — care); `unset_cloexec` is only load-bearing if
  a future spawn drops `close_fds=True` — mark it so it is never "cleaned up";
  `buffering=0` is load-bearing for the framing contract (spec §2.3). The
  module-level `sys.stdin`/`sys.stdout` re-wrap at import time is a side effect
  before any logging exists. All kept verbatim per spec §7 — this is a cleanup
  list, not a defect report.
* **`set_proc_name`** — `cdll.LoadLibrary("libc.so.6")` hard-coded; on a
  non-glibc system it raises *before logging has started* in either role, and
  the prctl name is silently truncated at 15 bytes without a check
  (pre-rewrite §3.17; lines 24–32, called at 193 and 356).
* **The trust notes** — the command list crossed the channel as `pickle`
  (protocol 2, base64) — **superseded 2026-10-27: the carriage is now
  base64-JSON**.  `pickle.loads` *is* arbitrary Python, so the pickle
  carriage was, in principle, a code-execution primitive for whoever
  controls the payload, and no shape check could have rescued it after
  the fact; the remote now verifies the strict list-of-str shape before
  `Popen` and refuses anything else (a stale pickle payload from a
  mixed-version endpoint fails cleanly as 125).  The client's own source text — self-embedded into the
  helper one-liner — is the remote's program, with no integrity check on it. Inside the trust model (master and remote
  one user; qrexec policy authenticates the channel) this is fine; the design
  trades integrity for convenience. Document it if this file ever ships beyond a
  single-user trust domain (pre-rewrite §3.19; spec §1.1 keeps self-embedding as
  a non-goal by symmetry).

---

## 6. Cross-references

* `docs/specs/Threadless algorithm.md` — the full story of what was implemented
  (incident background §1.3, adopted decisions §1.2, wire contract §2, loops §5/§6,
  no-killpg §9.2, verification §11).
* `tests/probe.py` (T1–T7b + `tsig` + `p10`), `tests/master_probe.py` (M1–M5,
  M3's proxy-SIGKILL expectation strict on 137), `tests/qubes_probe.py` (T8–T15,
  T9/T10/T13 strict on 130/137 per the §11.2 status convention) — the suites;
  local 15/15 green at `4a2014f`; template quirks and observed deviations are
  recorded in the suite headers, not here.
* `bin/bombshell-client` — the implementation (589 lines, threadless, pure ASCII).
