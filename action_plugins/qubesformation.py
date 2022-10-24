import collections
import os
import sys
import tempfile
from ansible import errors
from ansible.plugins.action.template import ActionModule as template

sys.path.insert(0, os.path.dirname(__file__))
import commonlib

contents = """{{ vms | to_nice_yaml }}"""
topcontents = "{{ saltenv }}:\n  '*':\n  - {{ recipename }}\n"

def generate_datastructure(vms, task_vars):
    dc = collections.OrderedDict
    d = dc()
    for n, data in vms.items():
        # This block will skip any VMs that are not in the groups defined in the 'formation_vm_groups' variable
        # This allows you to deploy in multiple stages which is useful in cases
        # where you want to create a template after another template is already provisioned.
        if 'formation_vm_groups' in task_vars:
            continueLoop = True
            for group in task_vars['formation_vm_groups']:
                if n in task_vars['hostvars'][n]['groups'][group]:
                    continueLoop = False
            if continueLoop:
                continue
        
        qubes = data['qubes']
        d[task_vars['hostvars'][n]['inventory_hostname_short']] = dc(qvm=['vm'])
        vm = d[task_vars['hostvars'][n]['inventory_hostname_short']]
        qvm = vm['qvm']
        actions = []
        qvm.append(dc(actions=actions))

        for k in 'template source netvm'.split():
            if qubes.get(k) and qubes.get(k) is not None:
                qubes[k] = task_vars['hostvars'][qubes[k]]['inventory_hostname_short']

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
        if 'services' in qubes:
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
        template = qubes.get('template', None)
        source = qubes.get('source', None)
        netvm = qubes.get('netvm', None)
        require = []
        if template or source:
            require.append({'qvm': template or source})
        if netvm != None:
            require.append({'qvm': netvm})
        if require:
            qvm.append({'require': require})

    return d

class ActionModule(template):

    TRANSFERS_FILES = True

    def run(self, tmp=None, task_vars=None):
        qubesdata = commonlib.inject_qubes(task_vars)
        task_vars["vms"] = generate_datastructure(qubesdata, task_vars)
        with tempfile.NamedTemporaryFile() as x:
            x.write(contents.encode())
            x.flush()
            self._task.args['src'] = x.name
            retval = template.run(self, tmp, task_vars)
            if retval.get("failed"):
                return retval
    
            with tempfile.NamedTemporaryFile() as y:
                y.write(topcontents.encode())
                y.flush()

                # Create new tmp path -- the other was blown away.
                tmp = self._make_tmp_path()

                self._task.args["src"] = y.name
                namenoext = os.path.splitext(self._task.args["dest"])[0]
                dest = namenoext + ".top"
                self._task.args["dest"] = dest
                task_vars["recipename"] = os.path.basename(namenoext)
                task_vars["saltenv"] = "user" if "user_salt" in dest.split(os.sep) else "base"
                retval2 = template.run(self, tmp, task_vars)
                if retval2.get("failed"):
                    return retval2

            if not retval['changed'] and not retval2['changed']:
                for c in ('path', 'size'):
                    retval[c] = [x[c] for x in (retval, retval2) if c in x]
                return retval
            elif retval['changed'] and retval2['changed']:
                for c in ('src', 'checksum', 'size', 'state', 'changed', 'md5sum', 'dest'):
                    retval[c] = [x[c] for x in (retval, retval2) if c in x]
                return retval
            elif retval['changed']:
                return retval
            elif retval2['changed']:
                return retval2
            else:
                assert 0, "not reached"
