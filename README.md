Ansible connection plugin for Qubes
===================================

This is an experimental plug-in mechanism that enables Ansible to connect
to Qubes VMs, either from another Qubes VM, or from a remote host via SSH
(assuming there exists a proxy Qubes VM with SSH listening on it).

You integrate it by (a) placing the `qubes.py` connection plugin in the Ansible
`connection_plugins` directory (b) placing the qrun and qrun-bridge
executables in one of two locations:

1. Anywhere on your Ansible machine's `PATH`.
2. In a `../../bin` directory relative to the `qubes.py` file.

After having done that, you can add Qubes VMs to your Ansible `hosts` file:

```
workvm          ansible_connection=qubes
vmonremotehost  ansible_connection=qubes management_proxy=1.2.3.4
```

Please be *absolutely sure* you have reviewed this code before using it.

This code is available to you under the terms of the GNU LGPL version 2
or later.  The license terms are available on the FSF's Web site.
