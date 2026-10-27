#!/usr/bin/env python3
"""Qubes matrix T8..T15 (spec section 11.2) run for real.

Drives bin/bombshell-client against a REAL Qubes domain over the real
qrexec-client-vm proxy -- the full master -> proxy -> remote -> child
chain, no fakes.  The target domain name comes from the environment:

    QUBES_TEST_VM=<vm-name> python3 tests/qubes_probe.py
    (or: make test-qubes VM=<vm-name>)

Requires: this host can reach the domain's qubes.VMShell service, and
the domain is disposable or expendable -- the tests intentionally
leave orphans behind (T8's tail, T10's sleep 300, T13's sleep 300;
spec section 9.2 says they are NOT killed).

Environment notes verified on the reference template (Qubes 7, F41):
  * no /var/log/messages -- the remote syslog lands in the journal as
    unit-less entries with SyslogIdentifier 'bombshell-client.remote'.
    Journal checks run inside a follow-up session and scope lines
    PER-SESSION: each case anchors on the argv b64 prefix in its
    remote's 'Started with arguments' line (protocol 2, matching the
    implementation) -- deterministic under back-to-back runs on the
    same VM, where a time window would pick up the previous run's
    P6 lines (e.g. T10's 'channel closed' would poison T8d).
  * ps -C does not process-select on this template -- process checks
    use ps/grep/pgrep instead.
  * T9/T10/T13 status expectations: a process the chain waits on that
    dies by signal reports a negative CPython status; the tool converts
    it once at its exit boundary (_shell_status, spec section 7) to the
    shell convention 128+signum.  The assertions are STRICT on the
    shell-convention values (130/137, matching the spec's observed
    real-Qubes values); anything else is a failure.
"""
import base64
import hashlib
import os
import pickle
import re
import select as sel
import signal
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINARY = os.path.join(REPO_ROOT, "bin", "bombshell-client")

CASE_TIMEOUT = 40          # per-session hard ceiling (hang guard)
VM = os.environ.get("QUBES_TEST_VM") or (sys.argv[1] if len(sys.argv) > 1 else "")
results = []

if not VM:
    sys.exit("usage: QUBES_TEST_VM=<vm-name> python3 tests/qubes_probe.py "
             "(or: make test-qubes VM=<vm-name>)")


def case(name, ok, detail=""):
    results.append((name, ok, detail))
    print("%-22s %s %s" % (name, "ok" if ok else "FAIL", detail), flush=True)


def start_session(cmdlist, stdin_data=None, keep_stdin_open=False):
    """One bombshell-client session; returns the Popen of the master."""
    p = subprocess.Popen([sys.executable, "-u", BINARY, VM] + cmdlist,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    if stdin_data is not None:
        p.stdin.write(stdin_data)
        p.stdin.flush()
    if not keep_stdin_open:
        p.stdin.close()
    return p


def wait_for_confirmation_done(p, deadline=CASE_TIMEOUT):
    """Block until the master has consumed its confirmation phase or died.
    Not directly observable; use a generous margin (rtt to the domain)."""
    t0 = time.monotonic()
    while True:
        if p.poll() is not None:
            return p.returncode
        if time.monotonic() - t0 > 2.0:      # the far side is programmed and up
            return None
        time.sleep(0.1)


def keystroke(p, data, margin=0.35):
    """Send bytes then give the chain time to deliver them."""
    if isinstance(data, str):
        data = data.encode()
    p.stdin.write(data)
    p.stdin.flush()
    time.sleep(margin)


def harvest(p, deadline=CASE_TIMEOUT):
    """Select-gated collection until the master exits. Returns
    (rc, stdout_bytes, stderr_bytes, exit_dt_from_close?)."""
    end = time.monotonic() + deadline
    out = err = b""
    while True:
        if time.monotonic() > end:
            p.kill()
            p.wait()
            raise TimeoutError("master did not return within %d s"
                               % deadline)
        r, _, _ = sel.select([p.stdout, p.stderr], [], [], 0.05)
        for fdobj in r:
            data = fdobj.read(128 * 1024)
            if data:
                if fdobj is p.stdout:
                    out += data
                else:
                    err += data
        if p.poll() is not None:
            out += p.stdout.read()
            err += p.stderr.read()
            break
    p.wait(timeout=10)
    return p.returncode, out, err


def find_master_child(pid):
    """The master's one direct child: the qrexec-client-vm proxy."""
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % d) as f:
                stat = f.read()
        except OSError:
            continue
        fields = stat.rsplit(")", 1)[1].split()
        if len(fields) > 1 and int(fields[1]) == pid:
            return int(d)
    return None


def drain_session(cmdlist, deadline=CASE_TIMEOUT):
    p = start_session(cmdlist)
    try:
        return harvest(p, deadline=deadline)
    except TimeoutError:
        return None, b"", b""


def journal_scope(anchor_b64):
    """Journal lines of ONE session, anchored by the argv b64 prefix in
    the remote's 'Started with arguments' line, ending at the next
    session's start line.  journalctl output is in time order; taking
    the NEWEST match keeps the anchor unambiguous when the same command
    is used by repeated runs.  Returns (anchored_bool, scoped_lines)."""
    rc, out, _ = drain_session(["bash", "-c",
                                "journalctl -q --no-pager -o short-iso "
                                "-t bombshell-client.remote 2>/dev/null"])
    if rc is None:
        return False, []
    lines = [l.decode("ascii", "replace") for l in out.split(b"\n")
             if b"bombshell-client.remote[" in l]
    key = "Started with arguments: "
    anchor = anchor_b64[:40]   # stays visible even in a truncated log line
    i = None
    for k in range(len(lines) - 1, -1, -1):    # newest first
        if key in lines[k] and lines[k].split(key, 1)[1].startswith(anchor):
            i = k
            break
    if i is None:
        return False, []
    j = len(lines)
    for k in range(i + 1, len(lines)):
        if key in lines[k]:
            j = k
            break
    return True, lines[i:j]


# ---------------------------------------------------------------- cases ---

def preflight():
    rc, out, err = drain_session(["bash", "-c", "echo preflight-ok"])
    if rc == 125:
        sys.exit("VM %r refused the domain (does it exist / run the "
                 "qubes.VMShell service?)" % VM)
    if rc != 0 or b"preflight-ok\n" not in out:
        sys.exit("preflight through %s failed (rc=%s, out=%r)"
                 % (VM, rc, out[:80]))
    print("preflight ok: %s is reachable" % VM, flush=True)


def t8_incident():
    """The incident, live: an orphan grand-child pins the child pipes;
    the session must still end < 2 s with status 0, the tail must
    still be in the VM, no remote zombie, and the remote journal must
    be clean (spec section 11.2 T8)."""
    p = start_session(["bash"], keep_stdin_open=True)
    wait_for_confirmation_done(p)
    keystroke(p, "touch /tmp/t8pin\ntail -F /tmp/t8pin >/dev/null 2>&1 &\n",
              margin=0.6)
    tsend = time.monotonic()
    p.stdin.write(b"exit\n")
    p.stdin.flush()
    rc, out, err = harvest(p)
    dt = time.monotonic() - tsend
    ok = rc == 0 and dt < 2.0
    case("T8a incident-end-<2s", ok, "rc=%s dt=%.2f" % (rc, dt))

    rc2, out2, _ = drain_session(["bash", "-c", "echo clean-session"])
    case("T8b next-session-clean", rc2 == 0 and b"clean-session\n" in out2,
         "rc=%s out=%r" % (rc2, out2[:40]))

    rc, out, err = drain_session(["bash", "-c",
        "echo MARK-T\n"
        "ps -eo pid,ppid,stat,args -ww | grep -F 'tail -F /tmp/t8pin'\n"
        "echo MARK-Z\n"
        "ps -eo stat,args -ww | awk '$1 ~ /^Z/'\n"
        "echo MARK-R"])
    tail_live = b"tail -F /tmp/t8pin" in out

    def section(mark, end):
        parts = out.split(b"MARK-" + mark.encode() + b"\n")
        if len(parts) < 2:
            return b""
        return parts[1].split(b"MARK-" + end.encode() + b"\n")[0]

    zsec = section("Z", "R")
    nzombies = len([l for l in zsec.split(b"\n") if l.strip()])
    case("T8c orphan+no-zombie", tail_live and nzombies == 0,
         "tail_live=%s zombies=%s" % (tail_live, nzombies))

    # T8e: a ps on the VM mid-session must show the clean remote command
    # line (set_cmdline, spec section 9.k), not the remote's multi-KB
    # launch form.  The keep-alive session's command is quoted as
    # 'sleep 2.5' in its title.  The scan needs two self-match defenses
    # (Qubes run 2026-10-26 made both bite): the search string is
    # assembled at RUNTIME from non-adjacent parts so this session's
    # own rewritten title (which carries this script's text) cannot
    # match; and the scan reads /proc/*/cmdline directly instead of
    # piping through ps|grep -- grep's own cmdline always contains the
    # pattern as argv, so a pipeline self-match is structural.  The
    # only children spawned are `tr` (argv carries no pattern).
    p_ka = start_session(["bash", "-c", "sleep 2.5"],
                         keep_stdin_open=True)
    wait_for_confirmation_done(p_ka)
    _, pso, _ = drain_session(["bash", "-c",
                               "a='bombshell-client (remote) bash -c '\n"
                               "b=\"'sleep 2.5'\"\n"
                               "for f in /proc/[0-9]*/cmdline; do\n"
                               "  [ -r \"$f\" ] || continue\n"
                               "  t=$(tr '\\0' ' ' < \"$f\")\n"
                               "  case \"$t\" in *\"${a}${b}\"*)\n"
                               "    printf '%s\\n' \"$t\" | cut -c1-100\n"
                               "  esac\n"
                               "done"])
    p_ka_rc, _, _ = harvest(p_ka)
    ok = (b"bombshell-client (remote) bash -c 'sleep 2.5'" in pso
          and p_ka_rc == 0)
    case("T8e ps-shows-clean-cmdline", ok, "ps=%r" % pso[:80])

    anchor = base64.b64encode(pickle.dumps(["bash"], 2)).decode("ascii")
    found, scope = journal_scope(anchor)
    exit_line = any("child exited, status 0" in l for l in scope)
    messy = any(k in "\n".join(scope) for k in
                ("Traceback", "channel closed", "cannot execute",
                 "exiting program"))
    good = found and exit_line and not messy
    case("T8d remote-journal-clean", good,
         "scope=%d exit_line=%s messy=%s" % (len(scope), exit_line, messy))


def t9_status_fidelity():
    for script, expected, label in (
            ("exit 42", (42,), "T9 42-fidelity"),
            ("kill -9 $$", (137,), "T9 kill-9-fidelity"),
            ("true", (0,), "T9 true-fidelity")):
        rc, _, _ = drain_session(["bash", "-c", script])
        ok = rc in expected
        case(label, ok, "rc=%s expected=%s" % (rc, expected))


def t10_proxy_kill():
    """Kill the qrexec proxy mid-session; the master must stop < 2 s
    with the proxy's shell signal status (137), the remote sleep must
    orphan in the VM, and the remote journal must show P6 (spec
    section 11.2 T10)."""
    p = start_session(["bash", "-c", "sleep 300"], keep_stdin_open=True)
    wait_for_confirmation_done(p)
    time.sleep(1.0)                    # remote bash is idling in select
    proxy = find_master_child(p.pid)
    if proxy is None:
        p.kill()
        p.wait()
        case("T10 proxy-kill-<2s", False, "proxy pid not found")
        return
    os.kill(proxy, signal.SIGKILL)
    t0 = time.monotonic()
    p.wait(timeout=15)
    dt = time.monotonic() - t0
    case("T10 proxy-kill-<2s",
         p.returncode == 137 and dt < 2.0,
         "rc=%s dt=%.2f" % (p.returncode, dt))
    time.sleep(2.0)                    # let the remote log P6, if so fated
    _, pso, _ = drain_session(["bash", "-c",
                               "ps -eo pid,stat,args -ww | grep -F ' sleep 300'"])
    case("T10 sleep-orphans-in-vm", b"sleep 300" in pso,
         "ps=%r" % pso[:60])
    anchor = base64.b64encode(
        pickle.dumps(["bash", "-c", "sleep 300"], 2)).decode("ascii")
    found, scope = journal_scope(anchor)
    p6 = any("channel closed, child still alive" in l for l in scope)
    case("T10 remote-journal-P6", found and p6,
         "scope=%d p6=%s" % (len(scope), p6))


def t11_stream_big():
    rc, out, err = drain_session(["bash", "-c",
                                   'head -c 10485760 /dev/zero | tr "\\0" a'],
                                  deadline=120)
    case("T11 10MiB-exact", rc == 0 and out == b"a" * 10485760 and err == b"",
         "rc=%s got=%d err=%d" % (rc, len(out), len(err)))


def t12_ctrl_d():
    p = start_session(["bash"], keep_stdin_open=True)
    wait_for_confirmation_done(p)
    time.sleep(1.0)                    # bash is idling at its read
    t0 = time.monotonic()
    p.stdin.close()                    # Ctrl-D -> master's close frame
    rc, out, err = harvest(p)
    dt = time.monotonic() - t0
    case("T12 ctrl-d-end-<2s", rc == 0 and dt < 2.0,
         "rc=%s dt=%.2f" % (rc, dt))


def t13_ctrl_c():
    """The kernel never delivers the TTY's SIGINT to the remote child
    (it is in its own session); only P14->P11 can deliver it.  Pass:
    remote bash dies 130 (128+SIGINT, shell convention), the
    backgrounded sleep orphans (spec section 11.2 T13)."""
    p = start_session(["bash"], keep_stdin_open=True)
    wait_for_confirmation_done(p)
    keystroke(p, "sleep 300 &\n", margin=0.7)
    p.send_signal(signal.SIGINT)
    rc, out, err = harvest(p)
    case("T13 sigint-relay-death", rc == 130, "rc=%s" % rc)
    _, pso, _ = drain_session(["bash", "-c",
                               "ps -eo pid,stat,args -ww | grep -F ' sleep 300'"])
    case("T13 sleep-orphans-in-vm", b"sleep 300" in pso,
         "ps=%r" % pso[:60])


def t14_stream_separation():
    rc, out, err = drain_session(["bash", "-c", "echo A; echo B >&2; echo C"])
    case("T14 stream-separation",
         rc == 0 and out == b"A\nC\n" and err == b"B\n",
         "out=%r err=%r" % (out[:20], err[:20]))


def t15_waitable():
    """The smoking gun: while a live session is idling, attach strace to
    the remote bombshell python and record only pselect6/select and
    wait4/waitpid.  Pass: every select carries exactly four ready-able
    fds, the loop ends with exactly one WNOHANG wait4 reaping the child
    at status 7, and nothing else is waited on (spec section 11.2
    T15: the remote is at no point in a polling loop).

    The remote Python is identified in its /proc cmdline by this
    session's command text  --  NOT by its b64 payload, which the
    rewritten command line (set_cmdline, spec section 9.k) no longer
    carries in ps.  The search string is assembled from parts at
    runtime so this script does not match its OWN session (whose
    rewritten title contains this script's text).  strace runs WITHOUT
    -f: only the Python itself is traced, never its child.
    """
    mark_src = "%s" % hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:8]
    p = start_session(["bash", "-c",
                       "echo mark-%s; sleep 4; exit 7" % mark_src],
                      keep_stdin_open=True)
    wait_for_confirmation_done(p)
    time.sleep(1.2)

    script = (
        "s1='bombshell-client (remote) bash -c '\n"
        "s2=\"'echo mark-\"\n"
        "s3='%s'\n"
        "pid=$(ps -eo pid,args -ww "
        "| grep -F \"$s1$s2$s3\" | awk '{print $1; exit}')\n"
        "if [ -z \"$pid\" ]; then echo NO_PID; exit 1; fi\n"
        "echo PID=$pid\n"
        "strace -p $pid -o /tmp/bs.strace "
        "-e trace=pselect6,select,wait4,waitpid 2>/dev/null\n"
        "sleep 2\n"
        "echo TRACE_DUMP\n"
        "cat /tmp/bs.strace 2>/dev/null\n"
        "echo TRACE_EOF\n"
    ) % mark_src
    sp = start_session(["bash", "-c", script], keep_stdin_open=True)
    rc, spout, _ = harvest(sp, deadline=30)
    rc_a, aout, _ = harvest(p, deadline=30)
    case("T15 session-status", rc_a == 7, "session-A rc=%s" % rc_a)

    if b"NO_PID" in spout:
        case("T15 remote-found", False, "remote python not found by title")
        case("T15 wait-nohang", False, "skipped (no remote pid)")
        case("T15 select-four-fds", False, "skipped (no remote pid)")
        return

    head = spout.split(b"TRACE_DUMP\n")
    tail = head[1] if len(head) > 1 else b""
    trace_lines = [l for l in tail.split(b"\n") if l
                   if b"pselect6(" in l or b"select(" in l
                   or b"wait4(" in l or b"waitpid(" in l]
    waits = [l for l in trace_lines if b"wait4(" in l or b"waitpid(" in l]
    # strace renders the reaping poll as, e.g.
    #   wait4(1234, [{WIFEXITED(s) && WEXITSTATUS(s) == 7}], WNOHANG, NULL) = 1234
    ok_wait = (len(waits) == 1
               and b"WNOHANG" in waits[0]
               and b"WIFEXITED" in waits[0]
               and b"== 7" in waits[0])
    case("T15 wait-nohang", bool(ok_wait),
         "waits=%d sample=%r" % (len(waits), waits[0][:100] if waits else b""))
    sele = [l for l in trace_lines if b"pselect6(" in l or b"select(" in l]
    ok_four = False
    for l in sele:
        # strace prints the rlist as {0, 5, 9, 11} or [0 5 9 11]
        m = re.search(rb"[\{\[]([0-9]+(?:[,\s]+[0-9]+)+)[\}\]]", l)
        if m and len(re.split(rb"[,\s]+", m.group(1))) == 4:
            ok_four = True
            break
    case("T15 select-four-fds", bool(sele) and ok_four,
         "selects=%d sample=%r" % (len(sele), sele[0][:100] if sele else b""))


def main():
    preflight()
    t8_incident()
    t9_status_fidelity()
    t10_proxy_kill()
    t11_stream_big()
    t12_ctrl_d()
    t13_ctrl_c()
    t14_stream_separation()
    t15_waitable()
    good = all(ok for _, ok, _ in results)
    print("-" * 52)
    print("Qubes matrix (spec section 11.2) vs %s: %d/%d"
          % (VM, sum(ok for _, ok, _ in results), len(results)))
    if not good:
        print("FAILED: %s" % ", ".join(n for n, ok, _ in results if not ok))
    sys.exit(0 if good else 1)


if __name__ == "__main__":
    main()
