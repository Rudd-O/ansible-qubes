from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase
from ansible.module_utils._text import to_text

import subprocess

try:
    from __main__ import display
except ImportError:
    from ansible.utils.display import Display
    display = Display()


class LookupModule(LookupBase):

    def run(self, args, variables=None, vm=None, create=True):

        ret = []

        cmd = ['qvm-pass']
        if vm is not None:
            cmd += ['-d', vm]
        if create:
            cmd += ['get-or-generate']
        else:
            cmd += ['get']
        cmd += ['--', args[0]]

        display.vvvv(u"Password lookup using command %s" % cmd)

        try:
            ret = subprocess.check_output(cmd)[:-1]
        except subprocess.CalledProcessError as e:
            if e.retcode == 8:
                raise AnsibleError("qubes-pass could not locate password entry %s in store" % entry)
            else:
                raise AnsibleError("qubes-pass lookup failed: %s" % e)

        return [ret]
