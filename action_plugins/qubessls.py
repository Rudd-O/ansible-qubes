import pipes
from ansible import errors
from ansible.plugins.action.command import ActionModule as command


class ActionModule(command):

    def run(self, tmp=None, task_vars=None):
        cmd = ["qubesctl"]
        cmd.append('state.sls')
        cmd.append(self._task.args['sls'])
        if 'env' in self._task.args:
            cmd.append("saltenv=%s" % (self._task.args['env'],))
        module_args = " ".join(pipes.quote(s) for s in cmd)
        module_args = "bash -c %s" % pipes.quote("DISPLAY=:0 " + module_args)
        self._task.action = "command"
        self._task.args['_raw_params'] = module_args
        for x in 'env sls'.split():
            if x in self._task.args:
                del self._task.args[x]
        return command.run(self, tmp, task_vars)
