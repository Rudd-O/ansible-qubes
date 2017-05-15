DOCUMENTATION = """
---
module: qubes_pass
author: Rudd-O
short_description: Save passwords in the keyring.
description:
  - This module will call qvm-pass.  On the control machine.
    In this sense, it is very similar to the fetch module
    — it acts on the state of the control machine.
    Because of the way pass works, the final line endings
    on a content that is a multiline string are stripped
    before being stored.
options:
  name:
    required: true
    description: name of the entry for qvm-pass
  state:
    required: false
    choices: [ "present" ]
    default: "present"
  content:
    required: false
    description: set the name to these contents, when
                 state is present.
"""

EXAMPLES = r"""
- qubes_pass:
    name: key/a/b/c
    content: password

- qubes_pass:
    name: g/h/i
    content: |
      multi
      line
      string
"""
