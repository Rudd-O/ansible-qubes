# Threadless rewrite of `bin/bombshell-client` — implementation specification

Status: **implemented and verified (2026-10-23)**. The port described below is in
`bin/bombshell-client` (572 lines, threadless) and the test suites under `tests/` are
green — local 14/14 (`probe.py`, including the `p10` channel-loss regression case,
plus `master_probe.py`), Qubes matrix 18/18 vs a disposable VM
(`make test` / `make test-qubes VM=<vm>`). Observed deviations are recorded where
they bite an expectation (the §11.2 notes, the `tests/qubes_probe.py` header); the
pre-rewrite audit's *unimplemented* recommendations live in `docs/Pre-LLM audit.md`.

This document is self-contained: the background it needs from the pre-rewrite state
(incident mechanism, replaced defect classes, adopted decisions D1–D5) is restated
below (§1.3, §1.2) rather than borrowed from another document. Where it conflicts
with anything else, this specification wins.

Date: 2026-10-22
Target file: `bin/bombshell-client` (492 lines audited; all line numbers below refer to the pre-rewrite file)
Python floor: CPython 3.x as found on Qubes hosts (`os.set_blocking` needs 3.5+)

---

## 1. Objective

Rewrite `bin/bombshell-client` so that **each end (master and remote) is one `select()`
loop with no threads**. Process termination is a *waitable* event (SIGCHLD self-pipe), and
**the session ends exactly when the watched child exits — descendants are abandoned
(never drained, never awaited)**:

1. **One loop per end.** No `threading`, no `Queue`, no daemon threads, no `join()`. The
   headline incident from §1.3 (background `tail -F` + `exit` hangs the session at the
   remote `muxer.join()`, pre-rewrite line 482) becomes structurally impossible: nothing is
   joined — the loop `break`s on child death.
2. **Child/proxy death is waitable, not polled.** Each end grows a SIGCHLD self-pipe:
   handler writes one byte to a non-blocking pipe; the pipe read-end is a fourth fd in
   `select()`. No `select()` timeout, no per-iteration `p.poll()`, no
   `Popen.wait(timeout)` anywhere in either loop (decision, D2).
3. **Abandon, don't drain.** On the death wake the loop services the two output pipes
   *first* (final lines are delivered before the end), then breaks. Grand-children
   holding the child's pipe write-ends are abandoned — and **not killed** (decision
   2026-10-22: **no `killpg`**; revisit with the pty work, §9.2): they EPIPE on their
   next write, or, if they stay quiet, linger on accepted (D1).
4. **Wire compatibility is preserved** (§1.1): this rewrite interops byte-for-byte with
   the current framing; no format change.

### 1.1 Non-goals — things that must NOT change

| Invariant | Detail |
|---|---|
| Wire format | `MAX_MUX_READ = 128*1024` (line 29), `PACKLEN = 8` (30), `PACKFORMAT = "!HbIx"` (31) — values byte-identical; no new frame `active` values. |
| Bootstrap | helper-text one-liner streamed into `qubes.VMShell` (lines 347–362); `base64(pickle(command))` payload; unframed confirmation `!H` ret + `!I` len + msg (lines 110–122 / 125–140) — byte-identical. |
| Stream numbering | master→remote #0 = user keyboard, #1 = relayed signals; remote→master #0 = child stdout, #1 = child stderr (normative table, §2.2). The producer/consumer list **order** fixes the numbers — keep two-element lists in the same order everywhere. |
| CLI & dispatch | `bombshell-client [-d] <vm> <cmd...>`; the `__file__`/`-s` dispatch guard (line 489); remote argv layout (`-u -c` text, optional `-d`, b64 command). |
| Process names | `set_proc_name()` outputs (lines 331, 424) stay recognizable. |
| Logging | syslog via `LoggingEmu` (73–104), `-d` flag semantics, `%.3f` offset prefix. |
| Helpers to reuse | `quotedargs`, `quotedargs_ellipsized`, `set_proc_name`, `unset_cloexec`, `openfdforappend`, `openfdforread`, `send_confirmation`, `anypython` helper-text build, `saved_stderr` construction (364). |
| Master proxy spawn | `Popen(["qrexec-client-vm", <vm>, "qubes.VMShell"], …, preexec_fn=os.setpgrp, bufsize=0)` (367–374) unchanged — the master SIGCHLD-watches it like any other child. |
| Error codes kept | 125 (no confirmation / domain absent), 127 (cannot execute), 126 (other spawn failure), child exit status on clean termination. |

### 1.2 Adopted decisions D1–D5 (the pre-LLM audit's recorded decisions, absorbed)

| # | Decision | Consequence here |
|---|---|---|
| D1 | **Abandon, don't drain** (P0-sharpened). P1 (drain window) rejected; P2 (interactive prompt) open. | One visible `break`/`return` per loop; no windows, no deadlines, no prompts. |
| D2 | **End-of-process is waitable, not polled.** SIGCHLD self-pipe on both ends (remote: child; master: `qrexec-client-vm` proxy). Exactly four uniformly-ready fds per loop; no timeout, no per-iteration `poll()`. `signalfd(2)` was noted as the Linux-native alternative and rejected (process-wide mask surgery, batched delivery, no stdlib decode). | §4.5, §5, §6 loop bodies. |
| D3 | **Wake order = drain order.** Remote: child stdout → child stderr → death event → channel. Master: channel demux → proxy-death event → signal out → keyboard out. Last lines are always delivered before the session ends. | Wake branches ordered as shown in §5.2/§6.3. |
| D4 | **Reaping and status live in the loop, never in the handler.** Handler writes exactly one byte to a non-blocking pipe; `waitpid(WNOHANG)` (`p.poll()`) happens in exactly one place per end, the death branch. Handler installed **before** `Popen`; defensive `p.poll()` immediately after spawn. | §4.5 invariants, wiring in §5.1/§6.1. |
| D5 | **The single loop is the target shape**; the threaded companion set is a fallback, out of scope for this port. | The whole specification. |

### 1.3 Background: the pre-rewrite implementation and the incident

The pre-rewrite file (492 lines, Python 2/3) did the same job in a different shape:
one file, two roles (master in the source VM, remote in the target VM — the master
streams a helper one-liner that self-embeds the file and re-execs it as the remote).
Each role was **threaded**: the main thread spawned the child, exchanged the
confirmation, and `p.wait()`ed; dedicated worker threads — *muxers* (sources →
channel), *demuxers* (channel → sinks by stream number), and *signalers* (signal
self-pipe → `p.send_signal`) — did the rest. The remote's main thread finished with
`p.wait()` → `muxer.join()`; the end blocked at that join until every worker's
sources reached EOF.

**The incident** (why this rewrite exists): an in-session `tail -F x &`, then
`exit`. Steps 4–7 are the parts the new code makes unreachable (spec §13):

1. `tail` forks from the remote's bash and **inherits** bash's fd1/fd2 — the pipes
   the remote's muxer reads — so tail holds their write-ends.
2. `exit` → the bash child exits; the remote's `p.wait()` returns; the main thread
   reaches `muxer.join()`.
3. The muxer's sources are still *open*: a pipe reader ends at EOF, and EOF needs
   **every** write-end closed.
4. the muxer blocks in `read()` forever, and the main thread's `muxer.join()`
   blocks with it.
5. the remote process never exits, and the channel stays open;
6. the master is stuck in `p.wait()` — its proxy can't end while the remote lives:
   **hang**.
7. any later local keystroke is relayed as a framed write into the dead child's
   stdin → `BrokenPipeError` in the master's demuxer → `os._exit(124)`: the session
   not only hangs, it then **crashes**.

(And the descendant that held the pipes now has no owner: it can be neither
reaped nor cleanly killed — the motivation behind the §9.2 discussion.)

**Defect classes this rewrite replaces** (pre-rewrite `B<n>`, used throughout this
spec):

| # | Defect (pre-rewrite) | Replaced by |
|---|---|---|
| B1 | worker-thread exceptions funnel into `MyThread.run`'s fatal `os._exit(124)` | no threads; one `_main()` handler → exit 1 + syslog traceback (§7) |
| B2 | unprotected sink writes: `EPIPE` on *any* sink (channel, child stdin, local sink) aborts the whole end | per-sink demotion: P9 (child stdin), P15/P16 (local sinks), P12 (proxy stdin) — drop the sink, continue |
| B3 | source EOF treated as fatal: `copy()` crashed the end on a 0-byte read | channel EOF is an *event* (P6 remote / P18 master) with a defined status |
| B4 | `write()`'s partial-write loop dead: mis-treats an unbuffered short write as fatal and never advances | real partial-write loops `write_all_file` / `writev_all` (§4.2/§4.3) |
| B5 | short-read framing: "read 8 bytes, then read `ln`" assumes exact framing | the frame accumulator (§2.3) — a whole frame exists before any `struct.unpack` |
| B6 | header and payload left as **adjacent separate syscalls**: a torn frame (lost counterpart) is undetectable | header + payload leave in one `os.writev` (§2.3, §4.4) |
| B7 | `join()` omitted where it was needed: the incident's step 4 — child dead, end still joining the stale workers | no threads, no joins; the loop `break`s on child death (P5/P17) |
| B8 | signal handlers touching a non-thread-safe `queue.put` / `logging` from signal context | one-byte `os.write` self-pipe, async-signal-safe (§4.5/§4.6) |
| B9 | child not in its own session: Ctrl-C hit only the child shell; no clean kill target existed | **reversed:** `start_new_session=True` + no `killpg` at all — relay is frame-only, descendants orphaned (§9.1/§9.2) |
| B10 | the unframed confirmation read without accumulation: partial/short reads could feed the parser a torn handshake | select-gated accumulating confirmation on the master (§6.2); the invariant documented in §2.1 |
| B11 | the hang class of incident steps 4–7 above, plus the `kill -9`-the-master triangle and the proxy-death mid-session crash | both ends end on the single waitable event: child death (P5/P17) or channel EOF (P6/P18) |
| B12 | receive-side asserts: `ln > MAX_MUX_READ` crashed; the `select` exception list could assert-crash the end | the receiver accumulates before checking (§2.3); `select` gets `[]` for its third argument |

(Pre-rewrite line numbers refer to the audited 492-line file. The detailed
pre-rewrite analysis — thread-topology diagrams, the 22-item line-numbered audit,
the corner-case matrix — preceded this spec and is recoverable from git history of
`docs/Pre-LLM audit.md`; that file now holds only the recommendations the rewrite
left **unimplemented**.)

---

## 2. Wire contract (unchanged — reference for implementers)

### 2.1 Bootstrap handshake (before any multiplexing)

The remote writes, **unframed**, on its stdout:

```
struct.pack("!H", retval)          # 2 bytes
struct.pack("!I", len(msg))        # 4 bytes
msg                                # exactly len(msg) bytes
```

(`send_confirmation`, lines 110–122.) The master consumes exactly `6 + len(msg)` bytes
before any frame exists on the channel. Master semantics preserved verbatim:

- EOF before 2 bytes ⇒ treat as ret `125`, message `"domain does not exist"` (128–132);
- `retval != 0` ⇒ log the errmsg, terminate with `retval` (384–386);
- `retval == 0` ⇒ normal session.

### 2.2 Multiplex frames

`PACKFORMAT = "!HbIx"` ⇒ 8 bytes: stream number `n` (`!H`), `active` flag (`!b`, 1 = data,
0 = "close your sink `n`"), payload length `ln` (`!I`), one pad byte.

- `active=1` ⇒ exactly `ln` payload bytes follow;
- `active=0` ⇒ no payload; the consumer closes — and drops — sink `n`. A close frame is
  sent **at most once per stream** and no data frame may follow it on the same stream.

Stream numbering (producer/consumer list order):

| Direction | Stream 0 | Stream 1 |
|---|---|---|
| master → remote | user keyboard (`sys.stdin`) | relayed signals (one `!H` payload per frame) |
| remote → master | child **stdout** | child **stderr** |

Byte-level example, master sending one keystroke `\n`:

```
00 00 | 01 | 00 00 00 00 01 | 00 | 0a
  !H   !b     !I            !x   payload
```

Stream-0 close frame: `00 00 | 00 | 00 00 00 00 00 | 00`
Stream-1 signal frame for SIGINT(2): `00 01 | 01 | 00 00 00 00 02 | 00 | 00 02`

### 2.3 Framing rules (mandatory)

- **Header + payload leave in one `os.writev`** with a partial-write loop (§4.3, §4.4).
  Adjacent separate syscalls are rejected as the pre-rewrite tear class (B6, §1.3);
  paired writev plus the bounded loops (§5/§6) makes a missing counterpart
  bounded by the death event, never by an indefinite wait.
- **Reception is the frame accumulator below**, never "read 8 bytes, then read `ln`":
  one `select` + `read(MAX_MUX_READ)` may return any number of bytes, possibly straddling
  frame boundaries (B5, §1.3). The accumulator guarantees a whole frame before
  any `struct.unpack`.
- **Capped handling of close frames:** treat repeatedly arriving close frames (or data
  after close) for the same stream as no-ops, never as errors (§3.3).
- **One writer per fd, enforced by construction:** every out-going edge on each end
  (channel write, child stdin, local sinks) is touched by exactly one code path per
  wake.

---

## 3. Target architecture

### 3.1 Topology

```
master                                          remote
─────                                           ──────
user TTY (r)         ──┐    channel stdin (r) ──┐
signal self-pipe (r)   ┘                        ├──> child stdin      (frame #0)
            loop:                                └──> p.send_signal()  (frame #1)
            read:  p.stdout, chld_rd,
                   sig_rd, sys.stdin
            write: p.stdin, sys.stdout,
                   saved_stderr
child = qrexec-client-vm                          child = user command (own session)
                chld (r) death self-pipe                   chld (r) death self-pipe
```

Compared to the pre-rewrite topology (§1.3): the four thread classes (143–317) disappear; their
work folds into the two loops. The remote's `pairofpipes()` signaler pair (463) vanishes —
signal frames are handled inline. The master's signal pipe (398) becomes a plain
self-pipe read by the loop; each end *adds* its own child-death self-pipe.

### 3.2 Per-end fd inventory

| End | fd | R/W | alive while |
|---|---|---|---|
| remote | channel stdin (`sys.stdin`) | R | whole session |
| remote | channel stdout (`sys.stdout`) | W | whole session |
| remote | child stdout (`p.stdout`) | R | until EOF → close frame emitted |
| remote | child stderr (`p.stderr`) | R | until EOF → close frame emitted |
| remote | child stdin (`p.stdin`) | W | until close frame #0 or EPIPE |
| remote | child death pipe (`chld_rd`) | R | whole session |
| master | user TTY (`sys.stdin`) | R | until EOF (Ctrl-D → close frame #0) |
| master | channel = proxy stdout (`p.stdout`) | R | until EOF (then excluded) |
| master | proxy stdin (`p.stdin`) | W | until proxy dead |
| master | local stdout (`sys.stdout`) | W | until close frame #0 or EPIPE |
| master | saved stderr (`saved_stderr`) | W | until close frame #1 or EPIPE |
| master | signal self-pipe (`sig_rd`) | R | whole session |
| master | proxy death pipe (`chld_rd`) | R | whole session |

(Write ends of self-pipes are touched only by the installed handlers; they never enter
the `select` lists.)

### 3.3 Event → policy table (the state machine)

Every external event maps to exactly one row. "Wake" = one return from `select()`.

| # | Event | End | Action |
|---|---|---|---|
| P1 | child stdout ready, data | remote | `readinto(buf)` up to `MAX_MUX_READ`; emit frame (`n=0, active=1`) via `send_frame` (§4.4). |
| P2 | child stdout ready, EOF | remote | `close()` the fd; drop stream 0 from the outward live table; emit the stream-0 close frame once. If the send itself fails (channel dead) go to P10's termination. |
| P3 | child stderr ready, data | remote | P1 with `n=1`. |
| P4 | child stderr ready, EOF | remote | P2 with `n=1`. |
| P5 | **child death** (byte in `chld_rd`) | remote | `os.read(chld_rd, 64)` to drain wake bytes; `p.poll()` — the one and only reaping site; log status; **`return p.returncode`** out of the loop. Abandonment: no drain, no drain-then-break; grand-children are **not killed** (no killpg — decision 2026-10-22, §9.2): they EPIPE on their next write, or linger on accepted (D1). |
| P6 | channel EOF while child alive | remote | log "channel closed, child still alive"; **`return 1`** — the child and its subtree are orphaned (no killpg, §9.2); after the channel's read ends die, they EPIPE at their next write. (Today this case leaks: the remote keeps pumping into a dead channel until the muxer crashed out with `os._exit(124)` — pre-rewrite B3/B11, §1.3.) |
| P7 | close frame `n=0` (peer) arrives | remote | `p.stdin.close()`; drop sink 0; later `n=0` frames are dropped, not errors. |
| P8 | close frame `n=1` arrives | remote | nothing to close (signals are stateless); drop; later `n=1` frames dropped. |
| P9 | `EPIPE`/`OSError` writing `p.stdin` | remote | debug-log; `p.stdin.close()`; drop sink 0; **continue** — the death wake arrives (no later than) the next `select` and ends the session. This is the incident's crash line (B2, §1.3), converted from fatal to per-sink. |
| P10 | `EPIPE`/`OSError` sending a frame *to the channel* | remote | error-log; set `channel_dead` — a **per-wake** flag (reset at the top of every loop iteration; §5.2 reference + note 1): it skips the death and channel branches only for the *rest of this wake*. The next wake re-tests: stream EOF + child death ends via P5, channel EOF ends via P6 (return 1 — no group kill, §9.2; the child subtree is orphaned). Do not keep framing into the dead channel. |
| P11 | channel frame `n=1, active=1` (ln=2) | remote | `struct.unpack("!H", body)` → `p.send_signal(sig)` in `try/except OSError` (debug-log; emit if the child died in the same wake). |
| P12 | TTY data | master | `send_frame` stream-0 data frame to proxy stdin; `EPIPE` ⇒ debug-log, continue (the proxy's death wake is imminent — P17 catches it). |
| P13 | TTY EOF (Ctrl-D / hangup) | master | emit stream-0 close frame to proxy stdin (once); remove the TTY from the read list; loop continues on the remaining fds. |
| P14 | one of `HANDLED_SIGNALS` arrives locally | master | installed handler writes the signum byte to the signal self-pipe; the loop reads the pipe (all bytes in one wake), sending one stream-1 frame per byte; `EPIPE` ⇒ debug-log, stop the rest of this wake's signal frames. |
| P15 | channel data | master | read into the accumulator; emit every whole frame: `n=0` → `write_all(sys.stdout, body)`; `n=1` → `write_all(saved_stderr, body)`. `OSError` on a sink ⇒ close+drop that sink, debug-log, continue. |
| P16 | close frame `n=k` arrives | master | close sink `k` (`sys.stdout` / `saved_stderr`), drop it; idempotent (a second close is a no-op). |
| P17 | **proxy death** (byte in `chld_rd`) | master | `os.read(chld_rd, 64)`; `p.poll()` — one reaping site; `rc = p.returncode`; **return `rc`**. This is the whole master-side session-end detector; on it, the loop stops feeding `p.stdin` before an EPIPE is possible (the pre-rewrite mirror crash — the master writing into the dead proxy's stdin, B2 — becomes unrepresentable). |
| P18 | channel EOF | master | parse/emit any whole frames still accumulated (final lines first, per wake order), exclude `p.stdout` from further reads, **break**; then close out: `p.poll()`, and if the proxy has not reaped yet, `p.wait()` (the proxy exits when the channel dies — verify in T10); return the returned status. |

In-wake branch ordering (mandatory): **remote** stdout → stderr →
death → channel (D3). **Master**: channel → death → signal → keyboard.
Consequences: on the wake that ends the session, buffered final lines are delivered
*before* the `return`/`break`; on that same wake, no further keystrokes are ever framed.

### 3.4 Session-end status flow

- **Clean exit:** remote child exits `rc` → remote P5 (`return rc`) → channel closed →
  `qrexec-client-vm` exits with the same code → master P17 → `return rc` →
  `sys.exit(rc)`. *T9 verifies that the proxy propagates the remote exit code
  (qrexec behavior — §3.4).*
- **Remote died violently** (killed, OOM): proxy exits → master P17/P18 → returns the
  proxy code.
- **Domain absent:** no confirmation; EOF path returns 125 (§2.1).

---

## 4. Shared helpers (exact code)

Implement verbatim. All operate on unbuffered file objects / raw fds; both ends import
them.

### 4.1 `read_exact`

```python
def read_exact(f, n):
    """Blocking read of exactly n bytes. Returns None on EOF.
    Successor to the fragile 2/4/lc reads of recv_confirmation (lines 127-138)."""
    buf = b""
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf
```

Usage note: `read_exact` is *not* used by the loops themselves (the loops read through
`select`); it is offered for out-of-loop utilities. The confirmation phase (§6.2) needs
select-gated accumulation *and* therefore does its own chunked accumulation — see §6.2.

### 4.2 `write_all_file`

```python
def write_all_file(f, data):
    """Real partial-write loop for file objects. Returns bytes written.
    EPIPE/OSError propagate — callers apply per-sink policy (P9/P15/P12; the pre-rewrite
    row-E case is B2, §1.3)."""
    mv = memoryview(data)
    written = 0
    while len(mv):
        k = f.write(mv)
        if k is None or k < 1:
            raise OSError(errno.EIO, "short write on %s" % f)
        written += k
        mv = mv[k:]
    return written
```

That replaces the defective `write()` at lines 215–224, which mis-treats a
`None`/zero result of an unbuffered `write` as fatal and never advances on partial
writes (B4, §1.3).

### 4.3 `writev_all`

```python
def writev_all(fd, buffers):
    """Loop os.writev until every buffer is fully written. A safe EPIPE raises.
    The header/payload pair of a frame leaves through here — one logical unit
    (B6, §1.3: the pre-rewrite end's adjacent-syscall tear class)."""
    views = [memoryview(b) for b in buffers if b]
    total = sum(len(v) for v in views)
    done = 0
    while done < total:
        k = os.writev(fd, views)
        if k <= 0:
            raise OSError(errno.EIO, "writev did not advance")
        done += k
        i = 0
        while k and i < len(views):
            take = min(k, len(views[i]))
            views[i] = views[i][take:]
            k -= take
            i += 1
        while views and not len(views[0]):
            views.pop(0)
    return total
```

### 4.4 `send_frame`

```python
def send_frame(fd, stream, active, payload=b""):
    """One multiplex frame: 8-byte header + payload, one writev.
    close == active False, payload empty."""
    header = struct.pack(PACKFORMAT, stream, active, len(payload))
    if payload:
        writev_all(fd, [header, payload])
    else:
        os.write(fd, header)
```

### 4.5 The SIGCHLD self-pipe (the waitable end-of-process)

One byte per event in a pipe, made selectable by `select`. The invariants below are
the contract (recorded in the pre-rewrite design follow-up, absorbed here):

1. **Install before `Popen`**, and run one defensive `p.poll()` immediately after spawn.
   The child can die at `exec` (bad argv, early abort) before anything else is in
   flight; miss that, and you wait on the silent pipe forever — a select with nothing
   in it is just the thread hang repackaged.
2. **The handler is the minimal possible handle.** It does exactly one thing — write one
   byte to the non-blocking pipe — nothing else: no `Queue`, no logging, no `waitpid`,
   nothing reentrant. Dissolving and status decoding live *only* in the loop, exactly
   one place per end (P5/P17).
3. **No wake is ever lost.** The byte is persistent: a SIGCHLD delivered *inside*
   `select` interrupts it (`EINTR`; PEP 475 runs the handler then re-enters `select`),
   and after either path the byte is there when the loop wakes. A plain `child_dead`
   flag would have lost-wake races; a pipe byte does not.
4. **Scope is precisely *direct children only*:** `SIGCHLD` fires when our child
   terminates — by exit or by signal — and never fires for grand-children. That is
   exactly the intent: "did the session child end?" is answered; the pipe-pin of the
   grand-children is ignored, as it must be (that pin is what stopped the old
   `muxer.join()` — §1.3).

Wiring (both ends; shape identical to the program's existing signal pipes —
`pairofpipes()`, lines 398/463):

```python
chld_rd, chld_wr = os.pipe()
os.set_blocking(chld_wr, False)            # the handler must never block
signal.signal(signal.SIGCHLD,
             lambda s, f: os.write(chld_wr, b"\x01"))   # one byte, nothing else
```

Notes for the implementer:

- Not adopted: `signalfd(2)`, the kernel-flavored equivalent — selectable, handlerless,
  `si_pid` on read. It was deliberately rejected: needs process-wide blocking of
  `SIGCHLD` via `sigaction`/`sigprocmask` surgery CPython does not expose publicly,
  delivers batched (demultiplexed) signals, and some of the `struct signalfd_siginfo`
  payload has no stdlib decode. Keep the self-pipe.
- The handler may write into a full pipe only if the main loop has already drained —
  at most one byte ever lives on each pipe both ends (one child each), so the
  non-blocking flag is defense, not load-bearing.
- `close_fds=True` (already set) closes `chld_wr` in the child around `exec`, so no
  grand-child ever inherits the pipe write end.
- The closing-side close of `chld_wr` is not required (process exit handles it); do not
  add extra fd bookkeeping.

### 4.6 Signal-relay self-pipe (master only)

Same shape, one byte = signum. Cures B8 (§1.3: a handler that touched a
non-thread-safe `queue.put`/`logging` from the signal context — no longer possible;
`os.write(fd, bytes((sig,)))` is async-signal-safe, and the loop does the logging):

```python
sig_rd, sig_wr = os.pipe()
os.set_blocking(sig_wr, False)
for sig in HANDLED_SIGNALS:
    signal.signal(sig, lambda s, f: os.write(sig_wr, bytes((s,))))
```

`HANDLED_SIGNALS` is verbatim the tuple at lines 388–397:
`(SIGINT, SIGABRT, SIGALRM, SIGTERM, SIGUSR1, SIGUSR2, SIGTSTP, SIGCONT)`.
Instalation stays **after** the confirmation phase, matching the current order
(line 399 vs 383) — no behavioral change before session start.

---

## 5. The remote end

### 5.1 Sequence inside `main_remote()`

1. `set_proc_name("bombshell-client (remote) %s" % quotedargs())` (line 424) —
   unchanged; set up `LoggingEmu("remote")` (426);
2. arg parse: with `-d`: `cmd_b64 = sys.argv[2]`, else `sys.argv[1]` (431–435);
   `cmd = pickle.loads(base64.b64decode(cmd_b64))` (437);
3. **wire the death pipe — before `Popen`** (§4.5 invariants 1/3);
4. `Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, start_new_session=True,
   close_fds=True, bufsize=0)` — **`start_new_session=True` is new** (line 442–450 gains
   it): the child gets its **own session and process group**. Its sole remaining
   reason: signals broadcast to *our* group (e.g. a Ctrl-C typed at the remote VM's own
   console) no longer hit the child at the kernel level — relay stays frame-only, one
   delivery (§9.1 c). The former second reason — a consistent `killpg` target —
   receded with the killpg removal (§9.2); if the pty work takes it back up, revisit
   this flag then too.
5. on `OSError`: send confirmation `127` + message, `return 0` (message rides the
   confirmation; the process exit code is irrelevant to the master) — identical to the
   current 127/126 paths (452–461);
6. one defensive `p.poll()` immediately after spawn (invariant 3 — harmlessly catches
   instant `exec` failures; even if it reaps, the death-branch wake still reaps via
   `Popen`'s cached status);
7. `send_confirmation(sys.stdout, 0, b"")` — byte-identical handshake (451) — then the
   loop below.

### 5.2 The single loop (reference implementation)

```python
def main_remote():
    # steps 1-7 of §5.1 arrive here with `p` spawned and confirmation sent
    live_out = {0: p.stdout, 1: p.stderr}    # outward frames: 0=stdout, 1=stderr
    stdin_open = True                        # inward frame 0's sink (child stdin)
    acc    = bytearray()                     # frame accumulator: short reads impossible
    buf    = bytearray(MAX_MUX_READ)         # scratch for readinto
    chan_out = sys.stdout.fileno()
    channel_dead = False

    while True:
        r = select.select(
            [sys.stdin, chld_rd] + list(live_out.values()), [], []
        )[0]
        # uniform, ready-or-not four sources: channel, child stdout, stderr, death pipe;
        # live_out shrinks over time — the list is rebuilt from it each round.
        # (after both close frames: [sys.stdin, chld_rd] — still meaningful, bounded.)
        # channel_dead is per-wake (note 1 below): set by a failed channel send in
        # branch (1), it skips branches (3)/(4) only for the rest of this wake;
        # the next wake re-tests, so P5/P6 stay reachable after a channel loss.
        channel_dead = False

        # (1) child stdout, (2) child stderr — drain order (D3)
        for n in (0, 1):
            src = live_out.get(n)
            if src is None or src not in r:
                continue
            have = src.readinto(buf)
            if have == 0:                                  # EOF → close frame, once
                src.close()
                del live_out[n]
                try:
                    send_frame(chan_out, n, False)
                except OSError as e:
                    logging.error("can't close stream %d frame: %s", n, e)
                    channel_dead = True
                    break
            else:                                          # data → framed writev
                try:
                    send_frame(chan_out, n, True, memoryview(buf)[:have])
                except OSError as e:                       # P10
                    logging.error("channel write failed: %s", e)
                    channel_dead = True
                    break

        # (3) child death — the waitable end-of-session; reaping is once, here.
        if not channel_dead and chld_rd in r:
            os.read(chld_rd, 64)                           # drains the wake byte(s)
            p.poll()                                       # = waitpid(WNOHANG)
            rc = p.returncode
            logging.info("child exited, status %s", rc)
            # No killpg (decision 2026-10-22, §9.2): grand-children are orphaned;
            # they EPIPE at their next write or linger, accepted.
            return rc if rc is not None else 1             # ABANDON: no drain

        # (4) channel input — last; any keystroke in the fatal wake is never framed
        if not channel_dead and sys.stdin in r:
            chunk = sys.stdin.read(MAX_MUX_READ)
            if not chunk:                                  # P6: channel EOF
                logging.error("channel closed, child still alive")
                return 1                                   # child orphaned (no killpg, §9.2)
            acc += chunk
            while len(acc) >= PACKLEN:
                n, active, ln = struct.unpack(PACKFORMAT, acc[:PACKLEN])
                need = PACKLEN + (0 if not active else ln)
                if len(acc) < need:
                    break                                  # partial body: wait for
                                                           # the next wake
                body = bytes(acc[PACKLEN:need])
                del acc[:need]
                if not active:                             # P7/P8: close frame
                    if n == 0 and stdin_open:
                        p.stdin.close()
                        stdin_open = False
                        logging.debug("child stdin closed by peer")
                    continue
                if n == 0:                                 # P9: keyboard input
                    if stdin_open:
                        try:
                            write_all_file(p.stdin, body)
                        except OSError as e:
                            # Child died in this wake, before the death byte arrived.
                            logging.debug("child stdin dead: %s", e)
                            p.stdin.close()
                            stdin_open = False
                    # n==0 arrival with stdin closed is dropped, never an error
                elif n == 1:                               # P11: relayed signal
                    for i in range(0, len(body) - 1, 2):
                        try:
                            p.send_signal(struct.unpack("!H", body[i:i + 2])[0])
                        except OSError as e:
                            logging.debug("signal delivery failed: %s", e)
    # Only P5 (child death) and P6 (channel EOF) terminate the loop — both via return.
    return 0
```

Implementation notes:

- **`channel_dead` is per-wake, and P6's return is one channel-loss path.** Set by a
  failed channel send in branch (1), it skips the death and channel branches only for
  the *rest of that wake*; the flag is reset every loop round, so the next wake
  re-tests: P5 (the child died meanwhile) or P6 (channel EOF — a dead channel's
  read-end is *always* ready) ends the session (return 1; no group kill — §9.2; the
  child subtree is orphaned). Bounded, and never hangs. (A *persistent* `channel_dead`
  would make both branches unreachable forever and spin the loop — this is exactly
  the regression the local `p10` probe case guards, §11.1.)
- **No `p.stdin` in the read list:** it is write-only. The only touch on it is
  `write_all_file` (P9), `send_signal` (P11), and `close()`.
- **`live_out` empty but child still alive:** loop is `[sys.stdin, chld_rd]`
  only — still bounded: the child either dies (P5), or the user gives up (P6).
- **Status:** `p.returncode` after the death branch is the child's own exit status,
  which `qrexec-client-vm` propagates back as the session status (§3.4; verified by T9).
- The old remote `demuxer`+`signaler` threads (lines 469–471, 465–467, and
  `pairofpipes()` at 463) are entirely replaced by branch (4) and the inline
  handling of `send_signal`.

---

## 6. The master end

### 6.1 Sequence inside `main_master()`

1. `set_proc_name`/`LoggingEmu("master")`/arg parse — lines 331–345 verbatim, including
   the `-d` mapping and the `assert remote_command`.
2. Build the helper text — lines 347–362 **byte-identical** (this is the wire
   bootstrap; do not reformat anything inside it).
3. **wire the death pipe — before `Popen`** (invariant 1): the master's single direct
   child is `qrexec-client-vm`; its death is the master's session-end event (P17).
4. `Popen(["qrexec-client-vm", remote_vm, "qubes.VMShell"],
   stdin=PIPE, stdout=PIPE, close_fds=True, preexec_fn=os.setpgrp, bufsize=0)`
   (367–374) — unchanged; on `OSError` → `return 127` (376–377).
5. defensive `p.poll()`.
6. `saved_stderr = openfdforappend(os.dup(sys.stderr.fileno()))` (364) — unchanged;
   write the helper into `p.stdin` and flush (380–381) — unchanged.
7. **parse the confirmation *inside the loop*, before the TTY/signal pipe occur in the
   read list** (shape the pre-rewrite design sketch asked for — see the §6.2 form
   note): this also cures the
   fragile short reads at lines 127–138 (select-gated chunked accumulation below, §6.2).
8. on a nonzero confirmation → log the errmsg and return the confirmation code, as
   today (384–386); only the code-0 path falls through to step 9.
9. **wire the signal self-pipe** (§4.6) — reached only after a clean confirmation,
   matching the current ordering (confirmation at 383, signaler at 399).

### 6.2 The confirmation phase (select-gated accumulating read)

Not a bare `recv_confirmation` call: the proxy may die before the confirmation
arrives (bad domain, service failure), and the two possibilities must be
distinguished, never polled. The shape:

```python
conf = bytearray()
while True:
    r = select.select([p.stdout, chld_rd], [], [])[0]
    if p.stdout in r:
        got = p.stdout.read(MAX_MUX_READ)
        if got:
            conf += got
            if len(conf) >= 2:
                code = struct.unpack("!H", bytes(conf[:2]))[0]
                if len(conf) >= 6:
                    ln = struct.unpack("!I", bytes(conf[2:6]))[0]
                    if len(conf) >= 6 + ln:
                        errmsg = bytes(conf[6:6 + ln])
                        if code != 0:
                            logging.error("remote: %s", errmsg.decode("utf-8", "replace"))
                        return code
        else:
            return 125                    # EOF: service didn't report back
    if chld_rd in r:
        os.read(chld_rd, 64)
        p.poll()
        rc = p.returncode
        logging.error("proxy died before confirmation, status %s", rc)
        return rc if rc is not None else 125
```

Semantics preserved: EOF before anything parseable → 125 ("domain does not exist",
lines 128–132); nonzero ret → that ret (today's 384–386); proxy dead before the
confirmation → its status. Only the code-0 path falls through to the main loop.

Form note: the pre-rewrite design sketch asked for the confirmation to be parsed
*inside the same loop*, before the TTY joins the watch list. The two-phase form
above is functionally equivalent to that: the TTY and the signal self-pipe are not
in any read list before the code-0 verdict, there is no timeout and no polling in
either phase, and the "four uniformly-ready fds" contract (D2) governs the
*session* loop, which has no exception. If the implementer prefers the literal
single-`select` shape, inline this phase as an initial gate of the §6.3 loop: while
the verdict is pending, build the read list as `[p.stdout, chld_rd]` only; after the
code-0 verdict returns, build the full four-fd list. Both forms are accepted; the
four-fd session loop is what the port is judged on.

### 6.3 The main loop (reference implementation)

```python
# after the confirmation phase:
sig_rd, sig_wr = os.pipe()
os.set_blocking(sig_wr, False)
for sig in HANDLED_SIGNALS:
    signal.signal(sig, lambda s, f: os.write(sig_wr, bytes((s,))))

in_live = {0: sys.stdout, 1: saved_stderr}   # channel frame n -> local sink
kbd_live = True                             # TTY stream 0 still writable
acc     = bytearray()                       # receiver accumulator
channel_dead = False

while True:
    r = select.select(
        [p.stdout] + ([sys.stdin] if kbd_live else []) + [sig_rd, chld_rd],
        [], []
    )[0]

    # (1) channel demux first — last lines on the fatal wake arrive before return
    if p.stdout in r:
        got = p.stdout.read(MAX_MUX_READ)
        if got:
            acc += got
        while len(acc) >= PACKLEN:
            n, active, ln = struct.unpack(PACKFORMAT, acc[:PACKLEN])
            need = PACKLEN + (0 if not active else ln)
            if len(acc) < need:
                break                        # partial body: wait
            body = bytes(acc[PACKLEN:need])
            del acc[:need]
            sink = in_live.get(n)
            if sink is None:
                continue                     # sink already dropped: skip, never an error
            if active:                       # P15
                try:
                    write_all_file(sink, body)
                except OSError as e:
                    logging.debug("local sink %d dead: %s", n, e)
                    sink.close()
                    del in_live[n]           # sink EPIPE → drop, continue
            else:                            # P16
                logging.debug("remote closed stream %d", n)
                sink.close()
                del in_live[n]
        if not got:                          # P18: channel EOF
            logging.debug("channel EOF")
            channel_dead = True
            break                            # any remainder in acc is delivered
                                             # above; nothing else to wait on

    # (2) proxy death — the master's session-end detector
    if not channel_dead and chld_rd in r:
        os.read(chld_rd, 64)
        p.poll()
        rc = p.returncode
        logging.info("proxy exit status %s (== remote session status)", rc)
        return rc if rc is not None else 1

    # (3) local signals → frame n=1
    if not channel_dead and sig_rd in r:
        data = os.read(sig_rd, 64)
        for b in data:
            try:
                send_frame(p.stdin.fileno(), 1, True, struct.pack("!H", b))
            except OSError as e:
                logging.debug("signal frame failed: %s", e)
                break

    # (4) keyboard → frame n=0; Ctrl-D → close frame n=0 (once)
    if not channel_dead and sys.stdin in r:
        got = sys.stdin.read(MAX_MUX_READ)
        if got:
            try:
                send_frame(p.stdin.fileno(), 0, True, got)
            except OSError as e:
                logging.debug("stdin frame failed: %s", e)
                # the proxy is dying; its death wake (P17) ends the session
        elif kbd_live:
            try:
                send_frame(p.stdin.fileno(), 0, False)      # close frame #0
            except OSError as e:
                logging.debug("stdin close frame failed: %s", e)
            kbd_live = False    # no longer read the TTY

# P18 close-out: the remote's exit closed the channel, which ends the proxy
# (assumption Q5; exercised by T8 and T12)
p.poll()
if p.returncode is None:
    p.wait()
return p.returncode if p.returncode is not None else 1
```

### 6.4 Exit paths (all four, no other outlet)

| Path | Trigger | Returned |
|---|---|---|
| A | P17 (death wake in loop) | proxy `returncode` (= remote session status) |
| B | P18 (channel EOF) | `p.poll()`; if not reaped, `p.wait()` then `returncode` |
| C | Popen of the proxy failed | 127 |
| D | confirmation phase | nonzero confirmation value, 125, or early-proxy-death status |

`main_master()` returns an int; dispatch (§7) hands it to `sys.exit(...)`.
The old tail — `p.wait()`/`demuxer.join()` (411–415) — is replaced by paths A/B:
no join, so no competitor of join-order (the B7 class, §1.3, is unrepresentable).

---

## 7. Bootstrap and dispatch (changes minimal)

- Module-level fd wrappers at lines 487–488 are kept verbatim:
  ```python
  sys.stdin = openfdforread(sys.stdin.fileno())
  sys.stdout = openfdforappend(sys.stdout.fileno())
  ```
- The dispatch guard at line 489 keeps its exact meaning: `__file__` present and no
  `-s` as the first arg ⇒ master, else remote. Wrap it in one
  top-level function that replaces the current `sys.exit(main_master())` direct calls
  and upgrades `MyThread.run`'s `os._exit(124)` catch-all (B1, §1.3) into a real
  top-level handler:
  ```python
  def _main():
      try:
          if "__file__" in locals() and not ("-s" in sys.argv[1:2]):
              return main_master()
          return main_remote()
      except SystemExit:
          raise
      except BaseException:
          if logging is None:
              logging = LoggingEmu("bootstrap")
          logging.error("unhandled exception in the main loop")
          logging.error("traceback: %s", traceback.format_exc())
          return 1
  sys.exit(_main())
  ```
  Uncaught exceptions now exit **1** with a syslog traceback instead of the
  never-returns `os._exit(124)`.
- Imports: drop the Python-2 fallback shims (lines 9–17, the `queue`/`Queue` try/except
  and the `shlex`/`pipes` try/except) — Python 3 only (Qubes floor; §12 Q3). Keep
  `traceback` (top-level handler). The internal `import time` for the `LoggingEmu` timing
  prefix stays.

---

## 8. Delete / keep map (against the 492-line file)

| Lines | Symbol | Fate |
|---|---|---|
| 9–17 | py2 import fallbacks | removed (§12 Q3) |
| 24 | `import threading` | removed (nothing threaded left) |
| 15, 17 | `queue` / `Queue` import | removed |
| 68 | `debug_lock = threading.Lock()` | removed |
| 73–104 | `LoggingEmu` | kept; `_print` drops `threading.current_thread().name` and `debug_lock.acquire/release` (single-threaded now); the syslog line becomes `%.3f  <prefix>: msg` (§9.1 f). `prefix`, `openlog`, and every call site unchanged |
| 110–122 | `send_confirmation` | kept verbatim |
| 125–140 | `recv_confirmation` | removed; replaced by §6.2's select-gated accumulation |
| 143–153 | `MyThread` | removed; its fault path replaced by `_main`'s handler (§7) |
| 156–179 | `SignalSender` | removed; handler + self-pipe (§4.6) |
| 182–212 | `Signaler` | removed; inline `send_signal` in remote branch (4) (§5.2) |
| 215–224 | `write()` | removed; replaced by `write_all_file` + `writev_all` (§4) |
| 227–238 | `copy()` | removed (also kills the EOF-fatal misunderstanding of §3.3) |
| 241–276 | `DataMultiplexer` | removed; loop branches (1)(2) on remote, (3)(4) on master |
| 279–317 | `DataDemultiplexer` | removed; loop's channel-accumulator branches |
| 364 | `saved_stderr` construction | kept verbatim |
| 367–374 | proxy `Popen` | kept verbatim; death pipe (§4.5) is wired *before* it |
| 379–386 | helper write + `recv_confirmation` call | helper write kept verbatim; confirmation moved to §6.2 in-loop |
| 388–401 | signal tuple + `pairofpipes` + `Signaler.start()` | tuple kept (as `HANDLED_SIGNALS`); the rest replaced by §4.6 + loop branch (3) |
| 403–415 | muxer/demuxer start, `p.wait()`, `demuxer.join()`, return | replaced by §6.3 loop + exit paths A/B |
| 418–420 | `pairofpipes()` | removed (both uses replaced; remote pair vanishes entirely) |
| 431–451 | remote arg parse, `Popen`, confirmation | parse kept; `Popen` gains `start_new_session=True`; confirmation kept; death pipe wired before |
| 452–461 | remote spawn-failure paths | kept verbatim (codes 127/126) |
| 463–484 | remote signaler/demux/mux, `p.wait()`, `muxer.join()` | replaced by §5.2 loop + P5/P6 |
| 487–492 | bootstrap wrappers + dispatch | wrappers kept; dispatch per §7 |

New symbols to add: `read_exact`, `write_all_file`, `writev_all`, `send_frame`,
`HANDLED_SIGNALS`, the two self-pipe wiring blocks, the confirmation phase (§6.2),
both loops. Target new-file size ≈ 430–470 lines (actual: 572 — the delta from the estimate
is documentation comments, not new logic).

---

## 9. Behavior changes (user-visible — record in the changelog)

a. **The incident is fixed:** background `tail -F … &` + `exit` (or Ctrl-D) inside the
   session: the remote breaks on child exit, the channel closes, the master prompt
   returns in milliseconds with exit status 0 (or the child's status). No hang, no
   `os._exit(124)` crash path on a later keystroke.
b. **Grand-children at session end are *not killed*** (decision 2026-10-22 — **no
   `killpg`**, §9.2): they are orphaned; they EPIPE at their next write, or, if they
   stay quiet, linger indefinitely (accepted, D1). Revisit with
   the pty work.
c. **The remote child runs in its own session** (`start_new_session=True`, new at line
   442): signals broadcast to the bombshell's own process group no longer hit the child
   at the kernel level; relay remains frame-only (exactly one delivery — previously a
   group broadcast *and* a relayed frame could double-deliver on the remote).
d. **Channel loss with a live child** (remote: qrexec channel dropped while the child
   runs; master: `kill -9` the `qrexec-client-vm` proxy) now terminates the session:
   remote exits 1 (child subtree *not* killed — §9.2; orphaned); master returns the
   proxy status (typically 137). Previously: the remote kept pumping output into a dead channel until a muxer
   thread crashed the process with `os._exit(124)`.
e. **Exit codes:** unchanged on all pre-existing paths (125/127/126/child status); the
   *new* code 1 is observable only in case (d).
f. **Log-line naming:** thread names ("remote multiplexer", "master signaler", …) become
   the end prefix ("remote" / "master"); the syslog streams themselves are preserved
   (ident `bombshell-client.master` / `.remote`, same `%.3f` offset).
g. **Keystrokes in the fatal wake** are not framed — bounded by design; same wake's
   output drains before the loop ends (§3.3 in-wake order).
h. **Ctrl-D closes the child's stdin exactly once** (close frame n=0); the master
   stops reading the TTY after that.
i. **`os._exit(124)` is gone.** Real unhandled exceptions end the program with exit code
   1 and a traceback in syslog (§7).
j. **A channel write failure is bounded (P10).** If the remote's send to the channel
   fails (peer aborted, EPIPE), the remote sets a *per-wake* `channel_dead`, stops
   framing into the dead channel, and the session still ends on the next wake via P5
   or P6 — it does not spin (regression case: local `p10`, §11.1).

### 9.2 No `killpg` (decision 2026-10-22 — recorded; not a toggle)

**The port contains no group-kill code.** Both candidate sites are simply absent,
with no placeholder:

- **P5 (child-death branch, remote):** `return rc` and done. The child's descendants
  are orphaned; they EPIPE at their next write (their stdout/stderr lose their read
  ends when this process exits) and die then, or, if they produce no output, linger
  silently — the accepted case (D1).
- **P6 (channel-EOF branch, remote):** `return 1` and done, with the same orphaning of
  the child itself and its subtree.

Why this stays parked now: the orphan's failure profile changes once descendants
hold a **pty** (typed-at terminals, line flushes, terminal control), and the
process-group / job-control semantics that "kill the group" leans on are only wanted
in that setting. When the pty work returns to session cleanup, revisit in one pass:
(i) re-adding the two remote `killpg` sites, (ii) the second
`start_new_session=True` rationale (§5.1 step 4), and (iii) the §12 Q5 contingency
(which today bans any trailing group-kill).

---

## 10. New file layout

```
 1   #!/usr/bin/python3 -u
    imports (py3-only): base64, errno, fcntl, os, pickle, select, signal, struct,
                        subprocess, sys, syslog, time, traceback, shlex.quote
 N   MAX_MUX_READ / PACKLEN / PACKFORMAT   (29–31, unchanged values)
    set_proc_name / unset_cloexec / openfdforappend / openfdforread      (kept)
    debug_enabled / _startt / LoggingEmu (single thread, §8)
    send_confirmation                                                        (kept)
    read_exact / write_all_file / writev_all / send_frame                    (§4)
    HANDLED_SIGNALS                                                          (388–397)
    def main_remote():    §5.1 + §5.2
    def main_master():    §6.1 + §6.2 + §6.3
    sys.stdin / sys.stdout bootstrap wrappers                                (487–488)
    def _main():  +  sys.exit(_main())                                       (§7)
```

Style rules to respect: the file is a module on *both* ends (self-embedding via
`-c`), so no top-level side effects other than the two `sys.`/`signal.` wrappers;
no configuration; starts with shebang, ends with `sys.exit(...)`.

---

## 11. Verification plan

### 11.1 Local tests (no Qubes needed) — remote end via `-s -d`

The remote role can be driven entirely by pipe pairs: launch
`python3 -u bin/bombshell-client -s -d <b64(pickle(cmd))>` with its stdin/stdout
connected to pipes, inject frames on stdin, read frames from stdout, then close the
channel to end. The driver adopted for this, `tests/probe.py` (appendix A is the
reference it was written from), implements `run(cmd, actions) -> (rc, frames_bytes, elapsed_s)`:

```
("io",    0, payload)                # frame:  keyboard input
("io",    1, struct.pack("!H", sig)) # frame:  relayed signal
("sleep", 1.0)                       # wait before the next action
("close", 0)                         # frame:  close stream 0 (the Ctrl-D analog)
("eof",)                             # close the channel (the peer goes away)
("abort",)                           # close the channel's *read* end mid-stream
                                      #  (the remote's next channel write EPIPEs:
                                      #  P10), without ever EOFing its stdin
```

| # | Passes `cmd` | Actions | Expected |
|---|---|---|---|
| T1 | `bash -c 'echo OUT0; echo ERR1 >&2; exit 0'` | eof | rc 0; frames ⊇ data(0) `OUT0\n`, data(1) `ERR1\n`, close(0), close(1); stream identity preserved (OUT0 isn't in the err stream and vice versa) |
| T2 | `bash -c 'trap "echo GOTINT" INT; while :; do sleep 0.1; done'` | io(1, SIGINT), sleep 1 s, eof | rc **1** (channel-EOF path, §5.2 branch 4 / P6); frame `data(1) "GOTINT\n"` present → proves P11's signal relay |
| T3 | `bash -c 'echo start; nohup tail -F /nonexistent & exit 5'` | eof | rc 5; return in **< 2 s** even though tail pins the pipes → the incident directly, without Qubes |
| T4 | `bash -c 'exit 9'` | io(0, b"x\n") at once, sleep 2 s, eof | rc 9, < 2 s. The input frame races the child's death: it is either written into a dying child (possible EPIPE handled per-sink, P9) or never parsed because the loop already broke. Either way: no crash, no exit 124. This is the incident's late keystroke made harmless |
| T5 | `bash -c 'read line; echo got-$line'` | io(0, b"hello\n"), eof | rc 0; frame data(0) `got-hello\n` |
| T6 | `bash -c 'for i in $(seq 1 20000); do echo line-$i; done'` | eof | rc 0; all 20000 lines received (accumulator + readinto-loop under `MAX_MUX_READ` chunking; no frame loss, total payload = full output) |
| T7 | `/nonexistent-binary` | eof | confirmation `127` before any frame; rc of remote process 0 (confirmation carries the code; the process exit is irrelevant) |
| T7b **stream close (Ctrl-D analog)** | `bash -c 'cat'` | io(0, b"data\n"), close(0), sleep 1 s, eof | rc 0; frame `data(0) "data\n"`; P7 ran: the close frame closed `p.stdin`, `cat` exited on EOF, and the death wake returned the status *before* the channel EOF |

T3 is the *regression of the headline incident* in its minimal form; T7b is the local
analog of Qubes T12 (Ctrl-D).

Supplementary local case **p10** (P10 channel-write-failure spin regression, §5.2 note 1):
`bash -c 'sleep 0.2; seq 1 40000; sleep 0.5'`, actions `sleep 0.1 s, abort` — the driver
drops the channel's read end *before* the child starts streaming, so the remote's sends
EPIPE mid-stream while its stdin stays open forever. Expected: the session ends **< 2 s**
with the child's status (the stream drains to EOF, the child exits, P5 wins) — never a
spin in the `channel_dead` guard. `tests/probe.py` runs it; its 30 s watchdog proves the
"never" half (an unfixed build hangs until it fires).

### 11.2 Qubes matrix

| # | Scenario | Pass criterion |
|---|---|---|
| T8 **the incident** | `bombshell-client <vm> bash`, then in the shell: `tail -F /var/log/messages &` then `exit` | (a) the master prompt returns in **< 2 s** with status 0; (b) the next session is clean; (c) `ps` in `<vm>`: `tail` still present (orphaned — no killpg, §9.2) and *no* zombie `bombshell-client.remote` on the remote (its process has exited); (d) remote syslog shows only clean "child exited, status 0", no traceback, no "exiting program" |
| T9 **status fidelity** | `bombshell-client <vm> 'exit 42'`, `'kill -9 $$'`, and a command with `bash -c 'true'` | master rc = 42, 137, 0 respectively → proves the remote→proxy→master status flow (§3.4). If this fails, document qrexec proxy status propagation first, before treating it as a bug in the port |
| T10 **proxy kill mid-session** | `bombshell-client <vm> 'sleep 300'`; then from a second terminal `kill -9 $(pidof qrexec-client-vm)` | master returns 137 in < 2 s; `sleep` stays in `<vm>` (orphan — no killpg, §9.2); remote syslog: "channel closed, child still alive" |
| T11 **streams big** | `bombshell-client <vm> 'head -c 10485760 /dev/zero \| tr "\0" a'` | 10 MiB received exactly; stdout/stderr identity; no hangs (the 128 KiB `MAX_MUX_READ` chunking makes this cross many frame boundaries) |
| T12 **Ctrl-D** | `bombshell-client <vm> bash`, then Ctrl-D at the prompt | remote bash sees EOF, the session ends, master returns bash's status (usually 0), < 2 s |
| T13 **Ctrl-C** | `bombshell-client <vm> bash`; in-session: `sleep 300 &`, then Ctrl-C | The kernel routes the TTY's SIGINT to the *master*, not to the remote child, so only P14→P11 can deliver it. Pass: remote bash dies with ~130, master rc ≈ 130, and `ps` in the VM shows the background `sleep` still present (orphan — no killpg, §9.2) |
| T14 **stream separation** | `bombshell-client <vm> 'bash -c "echo A; echo B >&2; echo C"'` | A, C on the master's stdout; B on the master's stderr — not jumbled |
| T15 **end is waitable** (smoking gun of the design) | run T8 with `strace -f` on the remote | the remote `bombshell-client` is at no point in a polling loop: during the session it blocks only in `pselect/select`; there is *no* thread and no repeating `waitpid` — exactly one `select` of the four fds, and one `waitpid(pid, WNOHANG)` at child death |

**Status-mask note (affects T9 and T13).** Where the child dies *by signal* and the
all-Python chain carries that status up, every Python hop exits via `sys.exit(-N)`,
which CPython surfaces as `(-N) & 0xFF = 256−N`: SIGKILL therefore observes as
**247** (not the shell-convention 137) and a relayed SIGINT as **254** (not 130).
The suites accept both values and report the observed one; the T9/T13 rows above
quote the conventional value, and either is in scope.

### 11.3 Code-level QA (run after implementation, before any Qubes test)

```bash
python3 -m py_compile bin/bombshell-client
python3 -m pyflakes bin/bombshell-client        # (if available)
```
And, in `bin/bombshell-client`, *these patterns must NOT exist* (all of them were
removed by design):

```
threading      ──  zero occurrences
import queue   ──  zero
\.join\(       ──  2 (the two string joins in `quotedargs`/`quotedargs_ellipsized`; no thread or list join)
os\._exit      ──  zero
select\.select\([^)]*,\s*timeout=    ──  zero (no time-out select)
Popen\.wait\(\s*timeout               ──  zero
os\.killpg                             ──  zero (decision 2026-10-22, §9.2)
```
And *these must exist exactly:*

```
signal\.signal\(signal\.SIGCHLD        ──  2 (one per end)
os\.pipe\(\)                            ──  ≥ 2 (death pipes; +1 on master for signals)
start_new_session=True                  ──  1 (remote child)
```

`p.poll()` occurrences: at most **six** total, each of which is in a named place:
two defensive reads immediately after each `Popen` (§5.1 step 6, §6.1 step 5); one in
each death branch (P5 remote, P17 master) — the session-level reaping, and the only
`poll()` that *serves as* the D4 "reap once, at the wake" contract; one in the
confirmation phase's early-death path (§6.2); and one in P18's channel-EOF close-out
(§6.3 bottom). Any `poll()` *anywhere else*, or any `poll()` used as the normal
per-iteration termination probe, **is** a bug (D4: reaping belongs in exactly one
place per end).

---

## 12. Open questions (default stated; resolve if the implementer objects)

Q1 **Grand-children at session end** — **resolved:** no killpg (decision 2026-10-22,
§9.2). Orphaned descendants are accepted for now; revisit together with the pty work.
Q2 **Exit code on channel-loss** — fixed as 1; alt proposals are 255 or 128+SIGKILL —
all are wire-neutral; 1 is what the remote's P6 contract (§5.2) already states.
Q3 **Python floor / py2 fallback removal** — assumed OK: every current Qubes host runs
a Python 3 toolchain, and the self-embedded bootstrap already *prefers* it via
`anypython` (lines 353–356). Confirm when merging.
Q4 **`LoggingEmu` syslog line** — the end prefix instead of the thread name (traces in
the user's log shift from "master multiplexer:" to "master:"). Acceptable.
Q5 **Master-side `p.wait()` in P18** — assumed that closing the channel's read end
(prompted by the remote process's exit) promptly ends `qrexec-client-vm`; T8 and T12
both close via this path. If any configuration makes the proxy linger, replace that `p.wait()` with
`p.poll()` + a short grace, and if still alive `p.kill()` it (our own child, not a
group signal — §9.2) — **do not add a time-out select in the loop**.

---

## 13. Acceptance criteria (definition of done)

- §11.3 forbidden/required pattern checks pass.
- Local T1–T7b plus the `p10` channel-loss regression green (`tests/probe.py`).
- Qubes T8–T15 green; incident (T8) and T9/T10 wall-time budget < 2 s.
- The incident's steps 4–7 (§1.3) are unreachable under the new code: step 4 vanishes
  (no `muxer.join()` — the remote `return`s at P5 without waiting for the
  grandchildren's EOF); step 5 vanishes with it (the remote process exits at once,
  so the channel EOFs and the master's P18 closes out); steps 6–7 never fire
  (late keystrokes drop per-sink at P9 — no uncaught `BrokenPipeError`, no
  `os._exit(124)`). The incident's `exit` returning 0 in milliseconds *is* the fix.
- No wire-format diff: on T14, capture the master's channel bytes (e.g. `strace`
  `-e write` on the proxy's stdin pipe) and verify the frame sequence matches §2 —
  the old and new ends are, byte for byte, mutually compatible framing.

---

## Appendix A — reference test driver for §11.1 (adopted as `tests/probe.py`)

Self-contained, ~70 lines, requires no Qubes. The implementer may adopt it as-is or
port it; behavior above is what is mandatory, not the code.

```python
#!/usr/bin/env python3
"""Drive bombshell-client's remote role over pipes (the qrexec channel).
Usage: probe.py <case>   (cases: t1..t7, t7b, p10)"""
import base64, os, pickle, struct, subprocess, sys, time
PACKFORMAT, PACKLEN = "!HbIx", 8

def mk(cmd): return base64.b64encode(pickle.dumps(list(cmd))).decode()

def frame(n, active, payload=b""):
    return struct.pack(PACKFORMAT, n, int(active), len(payload)) + payload

def run(cmd, actions):   # run from the repo root
    r_in,  w_in  = os.pipe()   # channel stdin  -> remote
    r_out, w_out = os.pipe()   # channel stdout <- remote
    t0 = time.time()
    child = subprocess.Popen([sys.executable, "-u", "bin/bombshell-client",
                              "-s", "-d", mk(cmd)],
                             stdin=r_in, stdout=r_out, stderr=subprocess.DEVNULL)
    os.close(w_out); os.close(r_in)
    ro = os.fdopen(r_out, "rb", 0); rw = os.fdopen(w_in, "wb", 0)
    acc = b""
    aborted = False
    for act in actions:
        if act[0] == "io":
            rw.write(frame(act[1], 1, act[2])); rw.flush()
        elif act[0] == "close":
            rw.write(frame(act[1], 0)); rw.flush()
        elif act[0] == "sleep":
            time.sleep(act[1])
        elif act[0] == "eof":
            break
        elif act[0] == "abort":      # P10 spin regression: drop the channel's
            aborted = True           # read end mid-stream; the remote's next
            ro.close()               # channel write EPIPEs, its stdin never EOFs
            break
    if not aborted:
        rw.close()                   # channel EOF (the peer goes away)
    while not aborted:
        d = ro.read(128 * 1024)
        if not d:
            break
        acc += d
    rc = child.wait(timeout=30)
    return rc, acc, time.time() - t0, ro

def dump(acc):
    out = []
    while len(acc) >= PACKLEN:
        n, a, ln = struct.unpack(PACKFORMAT, acc[:PACKLEN])
        if len(acc) < PACKLEN + ln:
            return out, "TRUNCATED"
        out.append((a, n, acc[PACKLEN:PACKLEN + ln]))
        acc = acc[PACKLEN + ln:]
    return out, "ok"

# --- cases ---------------------------------------------------------------
CASES = {
    "t1": (["bash", "-c", "echo OUT0; echo ERR1 >&2; exit 0"], [("eof",)]),
    "t2": (["bash", "-c", 'trap "echo GOTINT" INT; while :; do sleep 0.1; done'],
           [("io", 1, struct.pack("!H", 2)), ("sleep", 1.0), ("eof",)]),
    "t3": (["bash", "-c", "echo start; nohup tail -F /nonexistent & exit 5"],
           [("sleep", 0.5), ("eof",)]),
    "t4": (["bash", "-c", "exit 9"], [("io", 0, b"x\n"), ("sleep", 2.0), ("eof",)]),
    "t5": (["bash", "-c", "read line; echo got-$line"],
           [("io", 0, b"hello\n"), ("sleep", 1.0), ("eof",)]),
    "t6": (["bash", "-c", "for i in $(seq 1 20000); do echo line-$i; done"],
           [("sleep", 2.0), ("eof",)]),
    "t7": (["/nonexistent-binary"], [("eof",)]),
    "t7b": (["bash", "-c", "cat"],
           [("io", 0, b"data\n"), ("close", 0), ("sleep", 1.0), ("eof",)]),
    # P10 spin regression: abort before the child streams — the remote's sends
    # EPIPE mid-stream while its stdin stays open; P5 must still win.
    "p10": (["bash", "-c", "sleep 0.2; seq 1 40000; sleep 0.5"],
            [("sleep", 0.1), ("abort",)]),
}

def main(name):
    cmd, actions = CASES[name]
    if name == "p10":     # frame-assert off: acc can cut mid-frame at abort;
        rc, acc, dt, _ = run(cmd, actions)
        code = struct.unpack("!H", acc[:2])[0] if len(acc) >= 2 else None
        assert code == 0, "expected clean confirmation, got %r" % code
        assert rc == 0 and dt < 2.0, (rc, dt)   # child status wins (P5); no spin
        return
    if name == "t7":      # expect confirmation, not frames
        rc, acc, dt, _ = run(cmd, actions)
        code = struct.unpack("!H", acc[:2])[0] if len(acc) >= 2 else None
        print(name, "conf", code, "proc_rc", rc, "dt", round(dt, 2))
        assert code == 127, "expected 127 confirmation"
        return
    rc, acc, dt, _ = run(cmd, actions)
    frames, err = dump(acc)
    print(name, "rc", rc, "dt", round(dt, 2), err, [(a, n, b[:12]) for a, n, b in frames][:8])
    assert err == "ok"
    if name == "t1":
        assert rc == 0
        assert any(a and n == 0 and b == b"OUT0\n" for a, n, b in frames)
        assert any(a and n == 1 and b == b"ERR1\n" for a, n, b in frames)
        assert any(not a and n == 0 for a, n, b in frames)
        assert any(not a and n == 1 for a, n, b in frames)
    if name == "t2":
        assert rc == 1
        assert any(a and n == 1 and b == b"GOTINT\n" for a, n, b in frames)
    if name == "t3":      # incident regression: fast exit despite a pinned pipe
        assert rc == 5 and dt < 2.0, (rc, dt)
    if name == "t4":
        assert rc == 9 and dt < 2.0, (rc, dt)
    if name == "t5":
        assert any(a and n == 0 and b == b"got-hello\n" for a, n, b in frames)
    if name == "t6":
        payload = b"".join(b for a, n, b in frames if a and n == 0)
        assert payload.count(b"line-") == 20000, len(payload)
    if name == "t7b":
        assert rc == 0
        assert any(a and n == 0 and b == b"data\n" for a, n, b in frames)

if __name__ == "__main__":
    main(sys.argv[1])
```

Note: the driver's read loop blocks until the channel closes, which always happens as
the remote process exits on its own path — except in `p10`, where the driver closes the
read end itself and then just waits on the child (its 30 s `child.wait` timeout is the
hang detector). The sleep values leave explicit margins in T2/T4. Adjust sleeps freely;
the assertions and the timing contracts are mandatory.
