from ansible.plugins.action import ActionBase
import errno
import os
import re
import subprocess


class ActionModule(ActionBase):

    def __init__(self, *args, **kw):
        ActionBase.__init__(self, *args, **kw)

    def run(self, task_vars=None):
        ''' handler for launcher operations '''
        if task_vars is None:
            task_vars = dict()

        name = self._task.args["name"]
        if self._task.args["state"] == "present":
            return self.present(self._task.args["name"], self._task.args["content"])

    def present(self, name, content):
        result = {"changed": False}

        content = content.rstrip("\n")

        present = False
        try:
            oldcontent = subprocess.check_output(
                ["qvm-pass", "get", "--", name],
                stderr=file(os.devnull, "a")).rstrip("\n")
            if oldcontent == content:
                present = True
        except subprocess.CalledProcessError as e:
            if e.returncode != 8:
                raise
            # Else do nothing, the content is absent, we continue.

        if not present:
            if not self._play_context.check_mode:
                cmd = ["qvm-pass", "insert", "-f", "-m", "--", name]
                p = subprocess.Popen(cmd,
                                     stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT)
                out = p.communicate(content)[0].strip()
                ret = p.wait()
                if ret != 0:
                    raise subprocess.CalledProcessError(ret, cmd, out)
            result["changed"] = True
            if present:
                result["msg"] = "Password entry %s updated." % (name,)
            else:
                result["msg"] = "Password entry %s created." % (name,)

        return result
