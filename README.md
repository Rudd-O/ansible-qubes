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
2. placing the `bombshell-client` executable in one of two locations:

  * Anywhere on your Ansible machine's `PATH`.
  * In a `../../bin` directory relative to the `qubes.py` file.

3. placing the `qrun` executable in the same location as `bombshell-client`.

After having done that, you can add Qubes VMs to your Ansible `hosts` file:

```
workvm          ansible_connection=qubes
vmonremotehost  ansible_connection=qubes management_proxy=1.2.3.4
```

You are now free to run `ansible-playbook` or `ansible` against those hosts.

Additionally, you can use the `qssh` and `qscp` commands, which will
transparently attempt to SSH into a host unless it is unresolvable,
in which case it will fall back to using the `bombshell-client` to
communicate with a local VM.  Simply place these commands within the
same `bin` directory mentioned above, and they will just work.  If you
symlink `ssh` and `scp` to those commands respectively, SaltStack's
SSH-based automation will work transparently as well.

Bombshell remote shell technology
---------------------------------

Bombshell is a way to run commands in other VMs, that employs the `bombshell-client` script on this repository.  Said method is now integrated in these programs and will only work with Qubes OS 3.

Direct (non-Ansible and non-SaltStack) usage instructions:

    ./bombshell-client <vmname> command-to-run [arguments...]

The command above spawns a `command-to-run` on `vmname`, interactively.  Standard input, output, and error work as you would expect them to work -- you can type or pipe data, and said data will be fed to the remote end as standard input, with the remote end's standard output and standard error coming to your terminal's standard output and standard error.  Several signals sent to the local `bombshell` client will be relayed to the command-to-run program in the `vmname`.

    ./bombshell-client -d <vmname> command-to-run [arguments...]

Spawns the `command-to-run` on the `vmname`, interactively, printing communication channel interaction behavior into the standard error of the invoker, and into the root journal of the `vmname`.

The bounties that were published have been collected.  Sorry!   Open source works!

Enjoy!

License
-------

This code is available to you under the terms of the GNU LGPL version 2
or later.  The license terms are available on the FSF's Web site.
