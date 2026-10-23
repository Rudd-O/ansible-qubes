#!/usr/bin/env python3
"""Local test driver for `bin/bombshell-client`, remote role.

Runs the spec section 11.1 cases T1..T7b plus the supplemental `p10`
channel-loss spin regression against the threadless implementation without
any Qubes host: the remote role is driven over a pair of pipes that stand
in for the qrexec channel.  Frames are injected on the remote's stdin,
frames are read back from its stdout, and the channel is closed (EOF) to
end the session  --  exactly what a `qrexec-client-vm` proxy would do.

The Qubes matrix (T8..T15, spec section 11.2) lives in
tests/qubes_probe.py and needs a real disposable domain:
    make test-qubes VM=<vm>
    (equivalently: QUBES_TEST_VM=<vm> python3 tests/qubes_probe.py)

Usage (from anywhere):
    python3 tests/probe.py            # run every local case, exit 0/1
    python3 tests/probe.py t3 t7b     # run selected cases only

Per-case assertions and the timing contracts (< 2 s for T3/T4) are
mandatory (spec section 11.1); the sleeps below only carve margins and
may be adjusted freely.
"""
import base64
import os
import pickle
import select
import signal
import struct
import subprocess
import sys
import time

PACKFORMAT = "!HbIx"
PACKLEN = 8

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINARY = os.path.join(REPO_ROOT, "bin", "bombshell-client")

# Hard ceiling per case.  The spec's pass criteria are much tighter
# (T3/T4: < 2 s); this only guards the driver itself against a
# regress-to-hang implementation.
CASE_TIMEOUT = 30


def case_timeout(signum, frame):
    # installed by `run_case`; run() tears the child down before the
    # exception propagates
    raise TimeoutError("case exceeded %d s (regress-to-hang?)" % CASE_TIMEOUT)


def mk(cmd):
    return base64.b64encode(pickle.dumps(list(cmd))).decode()


def frame(n, active, payload=b""):
    return struct.pack(PACKFORMAT, n, int(bool(active)), len(payload)) + payload


def run(cmd, actions):
    """Spawn the remote role and feed it the action list over the channel.

    Actions:
        ("io",    n, payload)        # stream n data frame
        ("close", n)                 # stream n close (active=0) frame
        ("sleep", s)                 # wait s seconds (channel keeps draining)
        ("eof",)                     # close the channel (the peer went away)
                                     #  then keep draining until the remote exits
        ("abort",)                   # close the channel's read end mid-stream
                                     #  without closing its write end: the
                                     #  remote's next channel write EPIPEs
                                     #  (P10), but its stdin never sees EOF

    The channel is drained continuously while actions are pending  --  a real
    proxy never stops reading  --  so pipe buffers never wedge the session.
    Once the channel reads EOF (the remote exited), the case is done.

    Returns (rc, raw_channel_bytes, elapsed_s).
    """
    # channel stdin:  probe -> remote ;  channel stdout: remote -> probe
    r_in, w_in = os.pipe()
    r_out, w_out = os.pipe()
    child = subprocess.Popen(
        [sys.executable, "-u", BINARY, "-s", "-d", mk(cmd)],
        stdin=r_in,
        stdout=w_out,
        stderr=subprocess.DEVNULL,
    )
    os.close(r_in)
    os.close(w_out)
    ro = os.fdopen(r_out, "rb", 0)
    rw = os.fdopen(w_in, "wb", 0)

    t0 = time.monotonic()
    # Precompute each non-sleep action's start time from the total of the
    # sleeps that precede it.  Executing by deadline keeps ordering without
    # any per-action rescheduling state to get wrong.
    sched = []
    t = 0.0
    for act in actions:
        if act[0] == "sleep":
            t += act[1]
        else:
            sched.append((t0 + t, act))
    si = 0
    eof = False
    aborted = False
    channel_eof = False
    acc = b""
    try:
        while not channel_eof:
            # 1) drain whatever the remote already sent (non-blocking)
            if not aborted:
                ready, _, _ = select.select([ro], [], [], 0.01)
                if ready:
                    d = ro.read(128 * 1024)
                    if d:
                        acc += d
                    else:
                        channel_eof = True
                        break
            # 2) run every action whose start time has come
            now = time.monotonic()
            while si < len(sched) and sched[si][0] <= now:
                _, act = sched[si]
                kind = act[0]
                if kind == "io":
                    rw.write(frame(act[1], 1, act[2]))
                    rw.flush()
                elif kind == "close":
                    rw.write(frame(act[1], 0))
                    rw.flush()
                elif kind == "eof":
                    eof = True
                elif kind == "abort":
                    # close the read end only after the confirmation frame
                    # is captured, so the raw capture always starts with the
                    # handshake (the remote sends it right after spawn,
                    # before its loop)
                    while len(acc) < 6:
                        d_ = b""
                        if select.select([ro], [], [], 0.05)[0]:
                            d_ = ro.read(128 * 1024)
                        if d_:
                            acc += d_
                    aborted = True
                    ro.close()
                si += 1
            if eof:
                rw.close()              # channel EOF (peer gone)
            elif aborted and si >= len(sched):
                break                   # nothing left to send; wait on the child
    except TimeoutError:
        # watchdog fired: tear down, then propagate the failure
        child.kill()
        child.wait()
        raise
    finally:
        signal.alarm(0)
    try:
        rc = child.wait(timeout=CASE_TIMEOUT)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
        raise TimeoutError("remote role did not exit within %d s"
                           % CASE_TIMEOUT)
    # measured after the wait so dt is the remote's full lifetime on every
    # path (the drain loop may exit early once actions are spent)
    dt = time.monotonic() - t0
    return rc, acc, dt


def split_confirmation(raw):
    """Strip the unframed bootstrap confirmation.

    raw := <2b ret><4b len><len msg> followed by multiplex frames.
    Returns (ret, frames_bytes).
    """
    if len(raw) < 6:
        raise ValueError("no confirmation received (%d bytes: %r)"
                         % (len(raw), raw[:64]))
    ret = struct.unpack("!H", bytes(raw[:2]))[0]
    ln = struct.unpack("!I", bytes(raw[2:6]))[0]
    if len(raw) < 6 + ln:
        raise ValueError("truncated confirmation (msg len %d, got %d)"
                         % (ln, len(raw) - 6))
    return ret, raw[6 + ln:]


def parse_frames(raw):
    """Demux the whole frame stream.  Returns (stream, active, payload).

    Raises ValueError on any torn frame  --  the accumulator contract
    (spec section 2.3) makes this impossible unless the implementation
    regressed.
    """
    out = []
    while raw:
        if len(raw) < PACKLEN:
            raise ValueError("truncated frame header: %r" % raw[:32])
        n, a, ln = struct.unpack(PACKFORMAT, raw[:PACKLEN])
        total = PACKLEN + (ln if a else 0)
        if len(raw) < total:
            raise ValueError("truncated frame body (stream %d, active %d)"
                             % (n, a))
        out.append((n, bool(a), raw[PACKLEN:total]))
        raw = raw[total:]
    return out


def streamed(frames, n):
    return b"".join(b for m, a, b in frames if a and m == n)


def has_close(frames, n):
    return any(m == n and not a for m, a, b in frames)


CASES = {
    # T1: both streams, both close frames, stream identity.  The margin
    # before eof is what makes the child's exit win the race against the
    # channel EOF  --  rc is then the child's status (0), not P6's 1.
    "t1": (
        ["bash", "-c", "echo OUT0; echo ERR1 >&2; exit 0"],
        [("sleep", 0.5), ("eof",)],
    ),
    # T2: relayed SIGINT proof (P14->P11) + channel-EOF end (rc 1).
    # Margin before the frame: SIGINT delivered before the child's own
    # `trap` has run would take the default action and kill it.
    # The trap writes to stderr so the proof lands on remote stream 1,
    # exactly the frame spec section 11.1 asserts on.
    "t2": (
        ["bash", "-c", 'trap "echo GOTINT >&2" INT; while :; do sleep 0.1; done'],
        [("sleep", 0.5), ("io", 1, struct.pack("!H", 2)), ("sleep", 1.0),
         ("eof",)],
    ),
    # T3: THE INCIDENT in its minimal form  --  a grand-child (tail) pins
    # the output pipes yet the session must end in < 2 s with rc 5.
    "t3": (
        ["bash", "-c", "echo start; nohup tail -F /nonexistent & exit 5"],
        [("sleep", 0.5), ("eof",)],
    ),
    # T4: the incident's late keystroke  --  input frame races the child's
    # death; either written (P9 per-sink) or dropped, never fatal.
    # (Margin trimmed to 1.0 s so the < 2 s contract stays measurable.)
    "t4": (
        ["bash", "-c", "exit 9"],
        [("io", 0, b"x\n"), ("sleep", 1.0), ("eof",)],
    ),
    # T5: keyboard input round-trip
    "t5": (
        ["bash", "-c", "read line; echo got-$line"],
        [("io", 0, b"hello\n"), ("sleep", 0.5), ("eof",)],
    ),
    # T6: chunking under MAX_MUX_READ  --  no frame loss over many frames.
    # The drain in run() keeps the channel flowing during the margin;
    # the channel must stay open until the child has fully finished.
    "t6": (
        ["bash", "-c", "for i in $(seq 1 20000); do echo line-$i; done"],
        [("sleep", 3.0), ("eof",)],
    ),
    # T7: spawn failure  --  the confirmation carries the code, not the
    # process exit (which is 0 and irrelevant to the master)
    "t7": (
        ["/nonexistent-binary"],
        [("eof",)],
    ),
    # T7b: stream-0 close frame (Ctrl-D analog): cat must exit on EOF
    # and the death wake must end the session BEFORE the channel EOF
    "t7b": (
        ["bash", "-c", "cat"],
        [("io", 0, b"data\n"), ("close", 0), ("sleep", 1.0), ("eof",)],
    ),
    # tsig: THE STATUS CONVENTION (spec section 11.2 status note; local
    # pin of T9/T13 without Qubes).  A child that dies BY SIGNAL must be
    # reported to the caller as the shell convention 128+signum --
    # converted at the tool's single exit boundary (_shell_status).
    # 137 == 128 + SIGKILL; an un-converted CPython (-9) mask would
    # read 247.
    "tsig": (
        ["bash", "-c", "kill -9 $$"],
        [("sleep", 0.5), ("eof",)],
    ),
    # p10: the P10 channel-write-failure spin regression (spec section 3.3
    # P10, section 5.2 note 1).  The driver drops the channel's read end
    # at 0.1 s -- before the child starts emitting (0.2 s) -- so the
    # remote's sends EPIPE mid-stream (channel_dead set) while its stdin
    # stays open forever (no channel EOF for the remote).  The session
    # must still end: the child's output is drained (discarded), the
    # child exits at ~1.1 s, and P5 wins with the child's status  --
    # never a spin in the channel_dead guard, never a hang (the 30 s
    # watchdog proves the "never" half).
    "p10": (
        ["bash", "-c", "sleep 0.2; seq 1 40000; sleep 0.5"],
        [("sleep", 0.1), ("abort",)],
    ),
}


def check(name, rc, ret, frames, dt):
    """Per-case assertions from spec section 11.1 (mandatory)."""
    if name == "p10":
        # frames are None here: the driver's acc can be truncated mid-frame
        # at the abort, so only the confirmation and the end path are
        # asserted.  The interesting contract is "ended, fast, with the
        # child's status"  --  a persistent channel_dead guard instead
        # hangs until the 30 s watchdog.
        assert ret == 0, "confirmation code %r, expected 0" % ret
        assert rc == 0, ("child status must win the end (P5), got %s" % rc)
        assert dt < 2.0, ("channel loss must not stall the end: %.2f s" % dt)
        return
    if name == "t7":
        # expect confirmation, not frames
        assert ret == 127, "expected 127 confirmation, got %r" % ret
        assert not frames, "no frames expected after a 127 confirmation"
        assert rc == 0, "spawn-failure process exit should be 0, got %s" % rc
        return

    assert ret == 0, "confirmation code %r, expected 0" % ret
    if name == "t1":
        assert rc == 0, ("rc", rc)
        assert b"OUT0\n" in streamed(frames, 0), "missing stdout payload"
        assert b"ERR1\n" in streamed(frames, 1), "missing stderr payload"
        assert b"OUT0" not in streamed(frames, 1), "stdout leaked to stream 1"
        assert b"ERR1" not in streamed(frames, 0), "stderr leaked to stream 0"
        assert has_close(frames, 0), "missing stream-0 close frame"
        assert has_close(frames, 1), "missing stream-1 close frame"
        # no data (or second close) may follow a stream's close frame
        closed = set()
        for m, a, b in frames:
            assert m not in closed, "frame after close on stream %d" % m
            if not a:
                closed.add(m)
    if name == "t2":
        assert rc == 1, ("channel-EOF path must return 1", rc)
        assert b"GOTINT\n" in streamed(frames, 1), \
            "relayed signal did not reach the child"
    if name == "t3":
        assert rc == 5, ("child status must survive abandonment", rc)
        assert dt < 2.0, ("incident regression: %.2f s too slow" % dt)
    if name == "t4":
        assert rc == 9, rc
        assert dt < 2.0, ("late keystroke must not stall the end", dt)
    if name == "t5":
        assert rc == 0, rc
        assert b"got-hello\n" in streamed(frames, 0), "keyboard round-trip"
    if name == "t6":
        assert rc == 0, rc
        payload = streamed(frames, 0)
        assert payload.count(b"line-") == 20000, \
            "frame loss over %d bytes" % len(payload)
    if name == "t7b":
        # the death wake (cat EOF after the close frame) must have ended
        # the session before our channel EOF  --  rc is cat's, not P6's 1
        assert rc == 0, ("expected the child's 0, got %s (P6 instead of P5?)"
                         % rc)
        assert b"data\n" in streamed(frames, 0), "cat echo missing"
    if name == "tsig":
        # shell convention for a signal-killed child: 128 + signum
        assert rc == 137, ("signal-killed child must report 128+9 (137), "
                           "got %s" % rc)
        assert dt < 2.0, ("child death must end the session fast: %.2f s" % dt)


def run_case(name):
    if name not in CASES:
        known = ", ".join(sorted(CASES, key=lambda k: (len(k), k)))
        raise SystemExit("unknown case %r (known: %s)" % (name, known))
    cmd, actions = CASES[name]
    signal.signal(signal.SIGALRM, case_timeout)
    signal.alarm(CASE_TIMEOUT)
    try:
        rc, raw, dt = run(cmd, actions)
    except TimeoutError as e:
        print("%-4s  FAIL  %s" % (name, e))
        return False
    if name == "p10":
        ret = struct.unpack("!H", bytes(raw[:2]))[0] if len(raw) >= 2 else None
        frames = None
    else:
        ret, frames_bytes = split_confirmation(raw)
        frames = parse_frames(frames_bytes)
    try:
        check(name, rc, ret, frames, dt)
    except Exception as e:
        print("%-4s  FAIL  %s" % (name, e))
        sample = [(m, a, b[:16]) for m, a, b in frames[:8]] if frames else []
        if sample:
            print("      frames: %s (ret=%s, dt=%.2f)" % (sample, ret, dt))
        return False
    print("%-4s  ok    rc=%s ret=%s frames=%s dt=%.2f"
          % (name, rc, ret, len(frames) if frames is not None else "-", dt))
    return True


def main(argv):
    names = argv or ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t7b",
                     "tsig", "p10"]
    failed = []
    t0 = time.time()
    for name in names:
        if not run_case(name):
            failed.append(name)
    print("-" * 52)
    print("local suite (spec \u00a711.1): %d/%d passed in %.1f s"
          % (len(names) - len(failed), len(names), time.time() - t0))
    if failed:
        print("FAILED: %s" % ", ".join(failed))
        return 1
    print("Qubes matrix (spec \u00a711.2, T8\u2013T15): tests/qubes_probe.py, "
          "needs a real domain (make test-qubes VM=<vm>).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
