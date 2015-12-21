Qubes OS DevOps automation toolkit
==================================

This software helps you automate development operations on Qubes OS through
industry-standard configuration management solutions.

**Do you learn better by example?**  Then jump to the directory
[`examples/ansible/`](examples/ansible/) to  get started right away.

The software in this kit includes the following:

1. A computer program `bombshell-client` that can run in dom0 or
   in any domU, which uses the `qubes.VMShell` Qubes RPC service
   to provide an *interactive* session with a shell interpreter
   (or any program of your choice) from a VM to any other VM.
2. A connection plug-in for Ansible that uses `bombshell-client`
   to make the full power of Ansible automation available to
   Qubes OS administrators and users.
3. A set of commands for SaltStack `salt-ssh` that fake SSH
   and SCP using `bombshell-client` to enable SaltStack management
   of Qubes OS VMs.

`bombshell-client` and the other programs in this toolkit that
depend on it, can be used to remotely manipulate Qubes OS VMs:

* from the `dom0` within your Qubes OS machine
* from any `domU` within your Qubes OS machine
* to the `dom0` (you must install the `qubes.VMShell` RPC handler
  on `dom0` first) within your Qubes OS machine
* to any `domU` within your Qubes OS machine (no work needed)
* to any `dom0` or `domU` in a remote Qubes OS machine, provided:
  * that Qubes OS instance has at least one `domU` VM running SSH,
  * the SSH server is accessible via the network from the client
    machine running `bombshell-client` (firewall rules, etc.)
  * the SSH server lets the client log in passwordlessly (pubkey auth)
  * you have set up the `dom0` `/etc/qubes-rpc/policy/qubes.VMShell`
    such that RPC invocations from the `domU` running the SSH server
    are allowed to other VMs.

What this means:

With this toolkit, now you can script the setup and maintenance of
an entire network of Qubes OS machines.

**Warning: this is a massive hack.**  Please be *absolutely sure* you
have reviewed this code before using it.  Contributions welcome.

Bombshell remote shell technology
---------------------------------

Bombshell is a way to run commands in other VMs, that employs the `bombshell-client` script on this repository.  Said method is now integrated in these programs and will only work with Qubes OS 3.

Direct (non-Ansible and non-SaltStack) usage instructions:

    ./bombshell-client <vmname> command-to-run [arguments...]

The command above spawns a `command-to-run` on `vmname`, interactively.  Standard input, output, and error work as you would expect them to work -- you can type or pipe data, and said data will be fed to the remote end as standard input, with the remote end's standard output and standard error coming to your terminal's standard output and standard error.  Several signals sent to the local `bombshell` client will be relayed to the command-to-run program in the `vmname`.

    ./bombshell-client -d <vmname> command-to-run [arguments...]

Spawns the `command-to-run` on the `vmname`, interactively, printing communication channel interaction behavior into the standard error of the invoker, and into the root journal of the `vmname`.

Fairly simple:

    ./bombshell-client vmname bash

starts an interactive bash shell (without a prompt, as there is no tty)
on the machine `vmname`.  Any progran can be run in this way.  For
example:

    ./bombshell-client vmname hostname

should give you the host name of the VM `vmname`.

The rsync manpage documents the use of a special form of rsh to connect
to remote hosts -- this option can be used with `bombshell-client`
to run rsync against other VMs as if they were normal SSH hosts.

Enabling bombshell-client access to dom0
----------------------------------------

`dom0` needs its `qubes.VMShell` service activated.  As `root` in `dom0`,
create a file `/etc/qubes-rpc/qubes.VMshell` with mode `0644` and make
sure its contents say `/bin/bash`.

That's it -- `bombshell-client` should work against dom0 now.

How to use this with automation tools like Ansible and SaltStack
----------------------------------------------------------------

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
# The next line declares a simple connection to a domU on the same system.
workvm          ansible_connection=qubes
# The next line has a parameter which indicates to Ansible to first
# connect to the domU SSH at 1.2.3.4 before attempting to use
# bombshell-client to manage other VMs on the same system.
vmonremotehost  ansible_connection=qubes management_proxy=1.2.3.4
```

You are now free to run `ansible-playbook` or `ansible` against those hosts.
So long as those programs can find your `ansible.cfg` file, and your `hosts`
file, it will work.  Note that Qubes OS will bother you every time you run
commands with the prompt to allow `qubes.VMShell` on the target VM you're
managing, unless you set said permission to default to yes (the pertinent
file to edit is in the `dom0` of the target Qubes OS machine, path
`/etc/qubes-rpc/policy/qubes.VMShell`).

You can also integrate this plugin with SaltStack's `salt-ssh` program, by:

1. placing the `bombshell-client`, `qrun` and `qssh` commands
   in some directory of your path, then
2. symlinking `ssh` to `qssh` and `scp` to `qssh` again, then
3. adding the `host:` attribute to the roster entry of each one of your
   VMs as follows: `<VM name>.__qubes__`.

These fake `ssh` and `scp` commands will transparently attempt to SSH
into a host unless the host name ends with `.__qubes__`, in which case
they will assume it's a VM and fall back to using the `bombshell-client`
to communicate with said presumed VM.  SaltStack's SSH-based `salt-ssh`
automator will pick these fake SSH and SCP clients based on the path,
and they will work transparently.

If the program `qssh` or `qscp` get a first and second parameters
`--vmname <VM>`, then it is assumed that the host name passed to
the command is irrelevant, and that you want to connect to the VM
specified by `<VM>`.  If, in addition to that, you specify third
and fourth parameters `--management-proxy <M>`, then it is assumed
that you want to connect to the VM through the IP address of the
management proxy `<M>`.

Bug bounties
------------

The bounties that were published have been collected.  Sorry!   Open source works!

Enjoy!

License
-------

This code is available to you under the terms of the GNU LGPL version 2
or later.  The license terms are available on the FSF's Web site.
