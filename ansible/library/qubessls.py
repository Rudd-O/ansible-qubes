DOCUMENTATION = """
---
module: qubesformation
author: Manuel Amador (Rudd-O) <rudd-o@rudd-o.com>
short_description: provision VMs via a generated Qubes Salt Management recipe.
version_added: 0.0
description:
  - 'This module lets you provision VMs and enforce VM settings on a
    collection of VMs derived from your Ansible inventory.  Note that
    this module does not accept simple arguments -- you must specify
    complex arguments in the form of a dictionary below the module name.'
options:
  sls:
    required: true
    description:
      - The name of the recipe (SLS and top files), as stored in either `/srv/salt` for
        recipes in the `base` Salt environment, or `/srv/user_salt` for those in the `user`
        environment.
  env:
    required: false
    description:
      - Which Salt environment to load the SLS from (default `base`, you can specify `user`).
"""

EXAMPLES = r"""
# Would realize `/srv/salt/formation.sls` and `/srv/salt/formation.top`.
- qubessls:
    env: base
    sls: formation
"""
