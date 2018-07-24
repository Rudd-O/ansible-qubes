import os
import sys
import tempfile
from ansible import errors
from ansible.plugins.action.template import ActionModule as template

sys.path.insert(0, os.path.dirname(__file__))
import commonlib


contents = """# Sample configuration file for Qubes GUI daemon
#  For syntax go http://www.hyperrealm.com/libconfig/libconfig_manual.html

global: {
  # default values
  #allow_fullscreen = false;
  #allow_utf8_titles = false;
  #secure_copy_sequence = "Ctrl-Shift-c";
  #secure_paste_sequence = "Ctrl-Shift-v";
  #windows_count_limit = 500;
  #audio_low_latency = false;
};

# most of setting can be set per-VM basis
VM: {

{% for vmname, vm in vms.items() %}
{% set audio_low_latency = vm.qubes.get('guid', {}).get('audio_low_latency') %}
{% set allow_fullscreen  = vm.qubes.get('guid', {}).get('allow_fullscreen') %}
{% if audio_low_latency or allow_fullscreen %}
  {{ vmname }}: {
    {% if audio_low_latency %}audio_low_latency = true;{% endif %}
    
    {% if allow_fullscreen  %}allow_fullscreen = true;{% endif %}

  };
{% endif %}
{% endfor %}

};
"""


class ActionModule(object):

    TRANSFERS_FILES = True

    def __init__(self, runner):
        self.ActionModule = template.ActionModule(runner)

    def run(self, conn, tmp, module_name, module_args, inject, complex_args=None, **kwargs):
        ''' handler for launcher operations '''

        if module_args:
            raise errors.AnsibleError("This module does not accept simple module args: %r" % module_args)
        new_inject = dict(inject)
        new_inject["vms"] = commonlib.inject_qubes(inject)
        with tempfile.NamedTemporaryFile() as x:
            x.write(contents)
            x.flush()
            new_complex_args = dict(complex_args)
            new_complex_args["src"] = x.name
            new_complex_args["dest"] = "/etc/qubes/guid.conf"
            return self.ActionModule.run(
                conn,
                tmp,
                'template',
                module_args,
                inject=new_inject,
                complex_args=new_complex_args
            )
