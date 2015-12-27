import pipes
from ansible import errors


class ActionModule(object):

    TRANSFERS_FILES = True

    def __init__(self, runner):
        self.runner = runner

    def run(self, conn, tmp, module_name, module_args, inject, complex_args=None, **kwargs):
        ''' handler for launcher operations '''

        if module_args:
            raise errors.AnsibleError("This module does not accept simple module args: %r" % module_args)

        cmd = ["qubesctl"]
        cmd.append('state.sls')
        cmd.append(complex_args['sls'])
        if 'env' in complex_args:
            cmd.append("saltenv=%s" % (complex_args['env'],))
        if self.runner.noop_on_check(inject):
            cmd.append("test=True")

        module_args = " ".join(pipes.quote(s) for s in cmd)

        retval = self.runner._execute_module(
            conn,
            tmp,
            'command',
            module_args,
            inject=inject,
            complex_args=complex_args
        )
        changeline = retval.result['stdout'].splitlines()[-4]
        if self.runner.noop_on_check(inject):
            numtasks = changeline.split()[1]
            numunchanged = changeline.split("=")[1].split(')')[0]
            retval.result['changed'] = numtasks != numunchanged
        else:
            retval.result['changed'] = 'changed=' in changeline
        return retval
