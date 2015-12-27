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
4. A set of [action plugions for Ansible](./ansible/action_plugins/) that
   interface with the new
   [Qubes OS 3.1 Salt management stack](https://www.qubes-os.org/news/2015/12/14/mgmt-stack/).
5. A [set of DevOps automation skeletons / examples](./examples/) to get you up and
   running without having to construct everything yourself.

`bombshell-client` and the other programs in this toolkit that
depend on it, can be used to run operations from one VM to another,
in the following combinations:

* Qubes VM  -> Qubes VM
* Qubes VM -> Qubes `dom0` (see below for enablement instructions)
* Qubes `dom0` -> Qubes VM
* Qubes VM -> network (SSH) -> Qubes VM in another machine (see below for
   enablement instructions)
* normal desktop Linux -> network (SSH) -> Qubes VM in another machine

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

Enabling bombshell-client access to VMs in other machines
---------------------------------------------------------

Do this at your own risk.  On the other machine:

* Ensure that Qubes OS instance has at least one `domU` VM running SSH, which
   we will call the *target VM*.
* Ensure the SSH server on that VM is is accessible via the network from the
   *source VM* (which runs `bombshell-client`).  This includes any firewall
   and forwarding rules, etc.
* Ensure the target VM's SSH server lets your source VM log in passwordlessly
   (pubkey auth).
* Ensure the policy file in the other machine's `dom0` (the file is located at
   `/etc/qubes-rpc/policy/qubes.VMShell`) allows  the target VM (the one
   with the SSH server) to execute `qubes.VMShell` without prompting (otherwise
   you will have to physically walk over to the other machine and authorize
   each execution by hand).

How to use the connection technology with automation tools like Ansible and SaltStack
-------------------------------------------------------------------------------------

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
