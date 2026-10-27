#!/usr/bin/env python3
"""Supplemental fidelity checks for the base64-JSON payload (2026-10-27).

Complements the spec section 11.1 matrix (tests/probe.py) with the
properties the JSON carriage replacement exists to prove:

  j1  surrogate-degree fidelity: a master argv str carrying
      surrogate-escape characters (bytes the emission master could not
      UTF-8-decode) must arrive on the remote byte-for-byte (the str
      round-trip json -> b64 -> Popen fsencode is lossless; the test
      child prints its own argv so the remote's execve bytes are visible)
  j2  shape refusal: a payload that is valid JSON but not a list of
      strings must be refused with 125, nothing executed
  j3  mixed version: a STALE base64(pickle) payload from a pre-change
      endpoint must fail cleanly with 125, nothing executed

Usage (from anywhere):
    python3 tests/json_fidelity_probe.py        # exit 0/1
"""
import base64
import json
import os
import pickle
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe  # noqa: E402

results = []


def case(name, ok, detail=""):
    results.append((name, ok, detail))
    print("%-12s %s %s" % (name, "ok" if ok else "FAIL", detail), flush=True)


def strip_confirmation(raw):
    ret = struct.unpack("!H", bytes(raw[:2]))[0]
    ln = struct.unpack("!I", bytes(raw[2:6]))[0]
    return ret, raw[6 + ln:]


def drive_remote(payload_b64, actions=()):
    """Remote role via -s launch, the b64 token user-chosen.

    Returns (process_rc, confirmation_code_or_None, body_frames).
    A refusal at payload decode is deliberate: the 125 comes out on the
    process exit with NOTHING on the channel (the master, on its side,
    reads channel EOF there and also returns 125 -- same user-visible
    outcome)."""
    argv = [sys.executable, "-u", probe.BINARY, "-s", "-d", payload_b64]
    rc, raw, _dt = probe.run(["x"], list(actions), argv=argv)
    if len(raw) < 6:
        return rc, None, []
    ret, body = strip_confirmation(raw)
    frames = probe.parse_frames(body) if body else []
    return rc, ret, frames


def main():
    # j1: surrogate-degree fidelity
    surr = "a" + chr(0xdc81) + "b"  # one stray high byte (0x81) present
                                    # as the surrogate CPython installs for
                                    # it on an argv decode (PEP 383)
    # a surrogate via the master's surrogateescape argv decode
    cmd = ["bash", "-c", "printf '%s' \"$0\"", surr]
    payload = probe.mk(cmd)
    assert payload == base64.b64encode(
        json.dumps(list(cmd)).encode("ascii")).decode()
    rc, ret, frames = drive_remote(payload, [("sleep", 0.4), ("eof",)])
    out = probe.streamed(frames, 0)
    case("j1 surrogate-byte", ret == 0 and rc == 0 and out == b"a\x81b",
         "out=%r rc=%s ret=%s" % (out, rc, ret))

    # j2: valid JSON, wrong shape
    bad = json.dumps({"not": "a str list"}).encode("ascii")
    rc, ret, frames = drive_remote(base64.b64encode(bad).decode())
    case("j2 shape-refusal",
         ret is None and len(frames) == 0 and rc == 125,
         "ret=%s frames=%d rc=%s" % (ret, len(frames), rc))

    # j3: stale pickle payload from a pre-change endpoint
    old = pickle.dumps(["bash", "-c", "echo SHOULD-NOT-PRINT"], 2)
    rc, ret, frames = drive_remote(base64.b64encode(old).decode())
    leaked = b"SHOULD-NOT-PRINT" in b"".join(
        b for _m, a, b in frames if a)
    case("j3 mixed-version",
         ret is None and len(frames) == 0 and not leaked and rc == 125,
         "ret=%s rc=%s leaked=%s" % (ret, rc, leaked))

    ok = all(o for _n, o, _d in results)
    print("-" * 40)
    print("json-carriage probes: %d/%d %s"
          % (sum(o for _n, o, _d in results), len(results),
             "passed" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
