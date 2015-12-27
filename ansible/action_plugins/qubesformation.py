import collections
import os
import sys
import tempfile
from ansible import errors
from ansible.runner.action_plugins import template

sys.path.insert(0, os.path.dirname(__file__))
import commonlib


contents = """{{ vms | to_nice_yaml }}"""
topcontents = "{{ saltenv }}:\n  '*':\n  - {{ recipename }}\n"


def generate_datastructure(vms):
    dc = collections.OrderedDict
    d = dc()
    for n, data in vms.items():
        qubes = data['qubes']
        d[n] = dc(qvm=['vm'])
        vm = d[n]
        qvm = vm['qvm']
        actions = []
        qvm.append(dc(actions=actions))

        # Setup creation / cloning / existence test.
        if 'template' in qubes:
            creationparms = [
                {k: v} for k, v in qubes.items()
                if k in ['template', 'label', 'mem', 'vcpus', 'flags']
            ]
            actions.append('present')
            qvm.append({'present': creationparms})
        elif 'source' in qubes:
            assert qubes['vm_type'] in ['StandaloneVM', 'TemplateVM'], qubes['vm_type']
            cloneparms = [
                {k: v} for k, v in qubes.items()
                if k in ['source']
            ]
            actions.append('clone')
            qvm.append({'clone': cloneparms})
        else:
            actions.append('exists')
            qvm.append({'exists': []})

        # Setup preferences.
        ignparm = ['guid', 'services', 'dom0_vm',
                   'vm_type', 'flags', 'source']
        ignparm += ['netvm'] if qubes.get('vm_type') == 'NetVM' else []
        ignparm += ['template'] if qubes.get('vm_type') == 'StandaloneVM' else []
        prefsparms = [
            {k: v} for k, v in qubes.items()
            if k not in ignparm
        ]
        if prefsparms:
            actions.append('prefs')
            qvm.append({'prefs': prefsparms})

        # Setup services.
        if'services' in qubes:
            s = qubes['services']
            actions.append('service')
            services = []
            qvm.append({'service': services})
            for act in ['enable', 'disable', 'default']:
                if act in s:
                    services.append({act: s[act]})

        # Setup autostart and execution.
        if qubes.get('autostart'):
            actions.append('start')
            qvm.append({'start': []})

        # Collate and setup dependencies.
        template = qubes.get('template') or qubes.get('source')
        netvm = qubes.get('netvm', None)
        require = []
        if template:
            require.append({'qvm': template})
        if netvm != None:
            require.append({'qvm': netvm})
        if require:
            qvm.append({'require': require})

    return d


class ActionModule(object):

    TRANSFERS_FILES = True

    def __init__(self, runner):
        self.ActionModule = template.ActionModule(runner)

    def run(self, conn, tmp, module_name, module_args, inject, complex_args=None, **kwargs):
        ''' handler for launcher operations '''

        if module_args:
            raise errors.AnsibleError("This module does not accept simple module args: %r" % module_args)
        new_inject = dict(inject)
        qubesdata = commonlib.inject_qubes(inject)
        new_inject["vms"] = generate_datastructure(qubesdata)
        with tempfile.NamedTemporaryFile() as x:
            x.write(contents)
            x.flush()
            new_complex_args = dict(complex_args)
            new_complex_args["src"] = x.name
            retval = self.ActionModule.run(
                conn,
                tmp,
                'template',
                module_args,
                inject=new_inject,
                complex_args=new_complex_args
            )
            if retval.result.get("failed"):
                return retval

            with tempfile.NamedTemporaryFile() as y:
                y.write(topcontents)
                y.flush()

                # Create new tmp path -- the other was blown away.
                tmp = self.ActionModule.runner._make_tmp_path(conn)

                new_complex_args = dict(complex_args)
                new_complex_args["src"] = y.name
                namenoext = os.path.splitext(complex_args["dest"])[0]
                dest = namenoext + ".top"
                new_complex_args["dest"] = dest
                new_inject["recipename"] = os.path.basename(namenoext)
                new_inject["saltenv"] = "user" if "user_salt" in dest.split(os.sep) else "base"
                retval2 = self.ActionModule.run(
                    conn,
                    tmp,
                    'template',
                    module_args,
                    inject=new_inject,
                    complex_args=new_complex_args
                )
                if retval2.result.get("failed"):
                    return retval2
            if not retval.result['changed'] and not retval2.result['changed']:
                for c in ('path', 'size'):
                    retval.result[c] = [x.result[c] for x in (retval, retval2) if c in x.result]
                return retval
            elif retval.result['changed'] and retval2.result['changed']:
                for c in ('src', 'checksum', 'size', 'state', 'changed', 'md5sum', 'dest'):
                    retval.result[c] = [x.result[c] for x in (retval, retval2) if c in x.result]
                return retval
            elif retval.result['changed']:
                return retval
            elif retval2.result['changed']:
                return retval2
            else:
                assert 0, "not reached"
