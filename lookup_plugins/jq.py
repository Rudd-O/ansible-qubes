from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

import json
import sys
import subprocess

try:
    from __main__ import display
except ImportError:
    from ansible.utils.display import Display
    display = Display()


UNDEFINED = object()


class LookupModule(LookupBase):

    def run(self, args, variables):
        i = json.dumps(args[0])
        c = ["jq", args[1]]
        p = subprocess.Popen(c, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        o, e = p.communicate(i)
        r = p.wait()
        if r != 0 or e:
            assert 0, e
            raise subprocess.CalledProcessError(r, c, o, e)
        r = json.loads(o)
        return r
