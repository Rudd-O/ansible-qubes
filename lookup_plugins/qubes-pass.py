from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

import sys
import subprocess

try:
    from __main__ import display
except ImportError:
    from ansible.utils.display import Display
    display = Display()


UNDEFINED = object()


class LookupModule(LookupBase):

    def run(self, args, variables=None, vm=None, create=True, multiline=False, no_symbols=False, default=UNDEFINED):

        ret = []

        cmd = ['qvm-pass']
        if vm is not None:
            cmd += ['-d', vm]
        if create:
            cmd += ['get-or-generate']
            if no_symbols:
                cmd += ["-n"]
        cmd += ['--', args[0]]

        display.vvvv(u"Password lookup using command %s" % cmd)

        try:
            ret = subprocess.check_output(cmd)
            if not multiline:
                ret = ret[:-1].decode("utf-8")
        except subprocess.CalledProcessError as e:
            if e.returncode == 8:
                if create or default is UNDEFINED:
                    raise AnsibleError("qubes-pass could not locate password entry %s in store" % args[0])
                return [default]
            else:
                raise AnsibleError("qubes-pass lookup failed: %s" % e)

        return [ret]
