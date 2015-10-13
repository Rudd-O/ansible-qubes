Ansible connection plugin for Qubes
===================================

This is an experimental plug-in mechanism that enables Ansible to connect
to Qubes VMs, either from another Qubes VM, or from a remote host via SSH
(assuming there exists a proxy Qubes VM with SSH listening on it).

**Warning: this is a massive hack.**  Please be *absolutely sure* you
have reviewed this code before using it.  Contributions welcome.

How to use this
---------------

You integrate it into your Ansible setup by:

1. placing the `qubes.py` connection plugin in your Ansible
`connection_plugins` directory, then
2. placing the `qrun` and `qrun-bridge` executables in one of two locations:

  * Anywhere on your Ansible machine's `PATH`.
  * In a `../../bin` directory relative to the `qubes.py` file.

After having done that, you can add Qubes VMs to your Ansible `hosts` file:

```
workvm          ansible_connection=qubes
vmonremotehost  ansible_connection=qubes management_proxy=1.2.3.4
```

Experimental bombshell replacement for qrun-bridge and friends
--------------------------------------------------------------

There is a *much faster* way to run commands in other VMs that employs the `bombshell-client` script on this repository.  Said script is still not part of the Ansible Qubes automation system, but it's the future of Ansible Qubes automation.  Despite the fact that the script is not yet wired into the Ansible automation system for Qubes, it can be used right now to execute commands against other VMs in a much faster way than through the legacy `qrun` script.

Usage instructions:

    ./bombshell-client <vmname> command-to-run [arguments...]

The command above spawns a `command-to-run` on `vmname`, interactively.  Standard input, output, and error work as you would expect them to work -- you can type or pipe data, and said data will be fed to the remote end as standard input, with the remote end's standard output and standard error coming to your terminal's standard output and standard error.  Several signals sent to the local `bombshell` client will be relayed to the command-to-run program in the `vmname`.

    ./bombshell-client -d <vmname> command-to-run [arguments...]

Spawns the `command-to-run` on the `vmname`, interactively, printing communication channel interaction behavior into the standard error of the invoker, and into the root journal of the `vmname`.

I'm pledging bounties for the following bugs:

* US$65 per bug fix that solves problems with the script handling extraneous error conditions (you must explain how the condition arises, and how your fix prevents it).
* US$230 per bug fix that fixes data losses (you must explain what the data loss is, and demonstrate how your fix fixes it).
* US$830 per bug fix that fixes security issues (you must demo the security flaw after explaining what the insecurity scenario is and justifying the scenario).  This one is capped at two fixes.

Enjoy!

License
-------

This code is available to you under the terms of the GNU LGPL version 2
or later.  The license terms are available on the FSF's Web site.
