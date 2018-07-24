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
  dest:
    required: true
    description:
      - |
        Where to deposit the recipe -- usually a path like
        `/srv/user_salt/<formation name>.sls`).  Will create
        two files:
        1. The file you specified in `description`.
        2. An additional file with a .top extension instead of the
        original extension of the file you specified.
  others:
    description:
      - All arguments accepted by the M(template) module also work here,
        except for `src` and `content`.
    required: false
"""

EXAMPLES = r"""
# Would create `/srv/user_salt/formation.sls` and `/srv/user_salt/formation.top`.
- qubesformation:
    dest: /srv/user_salt/formation.sls
"""
