#!/usr/bin/env python3
"""Local master-side suite (M1..M5) for `bin/bombshell-client`.

Companion to tests/probe.py, which pins the spec section 11.1 cases for
the remote role.  This suite exercises the other half without any Qubes
host: the master is driven against a fake qrexec-client-vm (tests/
fakebin/) that execs the helper line it is streamed, so the full
master -> proxy -> remote -> child chain runs on this machine.

Requires Linux (process discovery under /proc).

Usage (from anywhere):
    python3 tests/master_probe.py

Status note: a process killed by SIGKILL reports returncode -9 to
Python; sys.exit(-9) then yields 247 (CPython masks with & 0xFF).
All-Python chains therefore observe 247 locally, not the shell-style
137 that spec section 11.2's T9/T10 quote from real-Qubes observations
(see docs/specs/Threadless algorithm.md section 3.4 / section 6.3 for the
proxy-propagation analysis).
"""
import os
import select as sel
import signal
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINARY = os.path.join(REPO_ROOT, "bin", "bombshell-client")
FAKEBIN = os.path.join(REPO_ROOT, "tests", "fakebin")
ENV = dict(os.environ, PATH=FAKEBIN + os.pathsep + os.environ.get("PATH", ""))
results = []


def start_master(vm, cmd, stdin_data=None, keep_stdin_open=False):
    p = subprocess.Popen([sys.executable, "-u", BINARY, vm] + cmd,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=ENV)
    if stdin_data is not None:
        p.stdin.write(stdin_data)
        p.stdin.flush()
    if not keep_stdin_open:
        p.stdin.close()
    return p


def find_child_of(pid):
    """The first child of pid (None while the process has no children)."""
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % d) as f:
                stat = f.read()
        except OSError:
            continue
        fields = stat.rsplit(")", 1)[1].split()
        # after the comm: state ppid pgrp ...
        if len(fields) > 1 and int(fields[1]) == pid:
            return int(d)
    return None


def wait_chain(p, levels=2, deadline=10.0):
    """Wait until the master's descendant chain is levels deep (the
    remote role alive means its spawn-then-confirm handshake is done),
    then add a short grace so the confirmation reaches the master's
    parser.  Returns the level-1 pid (the proxy) or None on timeout."""
    end = time.monotonic() + deadline
    proxy = None
    while time.monotonic() < end:
        proxy = find_child_of(p.pid)
        deeper = proxy
        for _ in range(levels - 1):
            if deeper is None:
                break
            deeper = find_child_of(deeper)
        if deeper is not None:
            time.sleep(0.1)          # let the handshake confirmation settle
            return find_child_of(p.pid)
        time.sleep(0.05)
    return None


def find_sleep300():
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % d, "rb") as f:
                cmdline = f.read()
        except OSError:
            continue
        if cmdline == b"sleep\x00300\x00":
            return int(d)
    return None


def harvest(p, deadline=30.0):
    """Select-gated collection of the master's stdout/stderr until exit."""
    end = time.monotonic() + deadline
    out = err = b""
    while True:
        if time.monotonic() > end:
            raise TimeoutError("harvest timeout")
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
    return out, err


def case(name, ok, detail=""):
    results.append((name, ok, detail))
    print("%-22s %s %s" % (name, "ok" if ok else "FAIL", detail))


# M1: child status fidelity (42) up the whole chain
p = start_master("fakevm", ["bash", "-c", "exit 42"])
out, err = harvest(p)
case("M1 status-42-fidelity", p.returncode == 42, "rc=%s" % p.returncode)

# M2: keyboard round-trip + Ctrl-D (stdin EOF -> close frame -> session end)
p = start_master("fakevm", ["bash", "-c", "read line; echo answered-$line"],
                 stdin_data=b"ping\n")
out, err = harvest(p)
case("M2 keyboard+Ctrl-D", b"answered-ping\n" in out and p.returncode == 0,
     "rc=%s out=%r" % (p.returncode, out[:40]))

# M3: proxy SIGKILL mid-session -> master returns 247 (masked -9) promptly
p = start_master("fakevm", ["bash", "-c", "sleep 300"], keep_stdin_open=True)
proxy = wait_chain(p)          # remote alive => confirmation sent
if proxy is None:
    p.kill()
    p.wait()
    case("M3 proxy-kill-247", False, "remote chain not up within 10 s")
else:
    os.kill(proxy, signal.SIGKILL)      # who crashed: the proxy itself
    t0 = time.monotonic()
    p.wait(timeout=10)
    dt = time.monotonic() - t0
    case("M3 proxy-kill-247", p.returncode == 247 and dt < 2.0,
         "rc=%s dt=%.2f" % (p.returncode, dt))
    sleep = find_sleep300()            # orphan per spec 9.2; tidy the artifact
    if sleep:
        os.kill(sleep, signal.SIGTERM)

# M4: refused domain -> 125 (ack-phase EOF semantics)
p = start_master("refusenode", ["true"])
out, err = harvest(p)
case("M4 refused-domain-125", p.returncode == 125, "rc=%s" % p.returncode)

# M5: SIGINT to the master relays as a control frame down the chain
p = start_master("fakevm",
                 ["bash", "-c", 'trap "echo GOTIT >&2" INT; while :; do sleep 0.1; done'],
                 keep_stdin_open=True)
proxy = wait_chain(p)          # remote alive => confirmation relayed, trap installed
if proxy is None:
    p.kill()
    p.wait()
    case("M5 sigint-relay", False, "remote chain not up within 10 s")
else:
    p.send_signal(signal.SIGINT)      # relays as a control frame down the chain
    time.sleep(0.5)                   # the child traps it and writes GOTIT
    os.kill(proxy, signal.SIGKILL)    # end the session
out, err = harvest(p, deadline=10)
case("M5 sigint-relay", b"GOTIT" in err,
     "rc=%s stderr=%r" % (p.returncode, err[:40]))

good = all(ok for _, ok, _ in results)
print("-" * 52)
print("master-side local suite: %d/%d" % (sum(ok for _, ok, _ in results), len(results)))
sys.exit(0 if good else 1)
