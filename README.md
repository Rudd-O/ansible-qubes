Ansible connection plugin for Qubes
===================================

This is a connection plug-in for Ansible and set of commands for SaltStack
`salt-ssh` that enables you to use Ansible and SaltStack to manage your
Qubes OS VMs:

* from the `dom0`,
* from any VM within your Qubes OS machine, or even
* from a machine that has SSH access to your Qubes OS machine
  (assuming there exists a proxy Qubes OS VM with SSH listening on the
  target Qubes OS machine, and said VM is permitted to run `qubes.VMShell`
  in other VMs of that system).

**Warning: this is a massive hack.**  Please be *absolutely sure* you
have reviewed this code before using it.  Contributions welcome.

How to use this
---------------

You integrate it into your Ansible setup by:

1. setting up a `connections_plugin = <directory>` in your `ansible.cfg`
   file, pointing it to a directory you control, then
2. placing the `qubes.py` connection plugin in your Ansible
   `connection_plugins` directory as defined above, then
3. placing the `qrun` and `bombshell-client` executables in one of two
   locations:

  * Anywhere on your Ansible machine's `PATH`.
  * In a `../../bin` directory relative to the `qubes.py` file.

After having done that, you can add Qubes VMs to your Ansible `hosts` file:

```
workvm          ansible_connection=qubes
vmonremotehost  ansible_connection=qubes management_proxy=1.2.3.4
```

You are now free to run `ansible-playbook` or `ansible` against those hosts.
So long as those programs can find your `ansible.cfg` file, and your `hosts`
file, it will work.  Note that Qubes OS will bother you every time you run
commands with the prompt to allow `qubes.VMShell` on the target VM you're
managing, unless you set said permission to default to yes.

You can also integrate this plugin with SaltStack's `salt-ssh` program, by:

1. placing the `bombshell-client`, `qrun`, `qssh` and `qscp` commands
   in some directory of your path, then
2. symlinking `ssh` to `qssh` and `scp` to `qscp`.

These commands will transparently attempt to SSH into a host unless it is
unresolvable, in which case they will assume it's a VM and fall back to
using the `bombshell-client` to communicate with said presumed VM.
SaltStack's SSH-based `salt-ssh` automator will pick these fake SSH and
SCP clients, and they will work transparently.

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
