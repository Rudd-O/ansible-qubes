Qubes OS DevOps automation toolkit
==================================

This software helps you automate development operations on Qubes OS through
industry-standard configuration management solutions.

**Do you learn better by example?**  Then jump to the directory
[`examples/`](examples/) to  get started right away.

The software in this kit includes the following:

1. A [computer program `bombshell-client`](./bin/bombshell-client) that can run in dom0 or
   in any domU, which uses the `qubes.VMShell` Qubes RPC service
   to provide an *interactive* session with a shell interpreter
   (or any program of your choice) from a VM to any other VM.
2. A [connection plug-in for Ansible](./ansible/connection_plugins/qubes.py)
   that uses `bombshell-client` to make the full power of Ansible automation
   available to Qubes OS administrators and users.
3. A [set of commands for SaltStack `salt-ssh`](./bin/) that fake SSH
   and SCP using `bombshell-client` to enable SaltStack management
   of Qubes OS VMs.
4. A set of [action plugins for Ansible](./ansible/action_plugins/) that
   interface with the new
   [Qubes OS 3.1 Salt management stack](https://www.qubes-os.org/news/2015/12/14/mgmt-stack/).
5. A [set of DevOps automation skeletons / examples](./examples/) to get you up and
   running without having to construct everything yourself.
6. A [lookup plugin](./lookup_plugins) for
   [`qubes-pass`](https://github.com/Rudd-O/qubes-pass) to get you to
   look up passwords for your infrastructure stored in separate VMs.
6. A [module and action plugin](./library) for
   [`qubes-pass`](https://github.com/Rudd-O/qubes-pass) to get you to
   store passwords needed to manage your infrastructure in separate VMs.

`bombshell-client` and the other programs in this toolkit that
depend on it, can be used to run operations from one VM to another,
in the following combinations:

* Qubes VM -> Qubes VM
* Qubes VM -> Qubes `dom0` (see below for enablement instructions)
* Qubes `dom0` -> Qubes VM
* Qubes VM -> network (SSH) -> Qubes VM on another Qubes host (see below)
* normal desktop Linux -> network (SSH) -> Qubes VM on another Qubes host

What this means for you is quite simple.  With this toolkit, you can completely
script the setup and maintenance of an entire network of Qubes OS machines.

Contributions always welcome.

**Security notes:**

1. Please be *absolutely sure* you have reviewed this code before using it.
2. These programs are stdin / stdout / stderr proxies over `qubes.VMShell`
   that allow the calling VM to create interactive and batch sessions in
   another VM.  Treat the resulting output from the called programs with
   the appropriate security precautions involving parsing untrusted input.

Bombshell remote shell technology
---------------------------------

Bombshell is a way to run commands in other VMs, that employs the `bombshell-client` script from this repository.  Said method is now integrated in these programs and will only work with Qubes OS 3.

Direct (non-Ansible and non-SaltStack) usage instructions:

    ./bombshell-client <vmname> command-to-run [arguments...]

The command above spawns a `command-to-run` on `vmname`, interactively.  Standard input, output, and error work as you would expect them to work -- you can type or pipe data, and said data will be fed to the remote end as standard input, with the remote end's standard output and standard error coming to your terminal's standard output and standard error.  Several signals sent to the local `bombshell` client will be relayed to the command-to-run program in the `vmname`.

    ./bombshell-client -d <vmname> command-to-run [arguments...]

Spawns the `command-to-run` on the `vmname`, interactively, printing communication channel interaction behavior into the standard error of the invoker, and into the root journal of the `vmname`.

Fairly simple:

    ./bombshell-client vmname bash

starts an interactive bash shell (without a prompt, as there is no tty)
on the machine `vmname`.  Any program can be run in this way.  For
example:

    ./bombshell-client vmname hostname

should give you the host name of the VM `vmname`.

The rsync manpage documents the use of a special form of rsh to connect
to remote hosts -- this option can be used with `bombshell-client`
to run rsync against other VMs as if they were normal SSH hosts.

Enabling bombshell-client access to dom0
----------------------------------------

`dom0` needs its `qubes.VMShell` service activated.  As `root` in `dom0`,
create a file `/etc/qubes-rpc/qubes.VMshell` with mode `0755` and make
sure its contents say `/bin/bash`.

You will then create a file `/etc/qubes/policy.d/80-ansible-qubes.policy`
with mode 0664, owned by `root` and group `qubes`.  Add a policy
line towards the top of the file:

```
qubes.VMShell           *           controller          *     allow
```

Where `controller` represents the name of the VM you will be executing
`bombshell-client` against `dom0` from.

That's it -- `bombshell-client` should work against `dom0` now.  Of course,
you can adjust the policy to have it not ask — do the security math
on what that implies.

How to use the connection technology with automation tools like Ansible
-----------------------------------------------------------------------

See [Enhance your Ansible with Ansible Qubes](doc/Enhance your Ansible with Ansible Qubes.md).

Enabling bombshell-client remote access to VMs in other machines
----------------------------------------------------------------

See [Remote management of Qubes OS servers](doc/Remote management of Qubes OS servers.md).

How to use the connection technology with SaltStack
---------------------------------------------------

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

How to use the Salt management interface for Qubes in Ansible
-------------------------------------------------------------

Documentation is a bit sparse at the moment, so the best bet is
to follow [the tutorial contained in the corresponding example](./examples/qubesformation/).

Bug bounties
------------

The bounties that were published have been collected.  Sorry!   Open source works!

Enjoy!

License
-------

This code is available to you under the terms of the GNU LGPL version 2
or later.  The license terms are available on the FSF's Web site.
