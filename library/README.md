# Ansible Qubes Pass action module

This action module can be used to store a password into your qubes-pass
(VM-backed) password manager
(see [`qubes-pass`](https://github.com/Rudd-O/qubes-pass).

Note that this module will not run the `qubes-pass` command on the target
managed machine — it will run the `qubes-pass` command locally on the
control machine.

Read the file `qubes_pass.py` in the `library/` directory of this
project for usage instructions.
