# Remote management of Qubes OS servers

This tutorial will help you combine [Qubes network server](https://github.com/Rudd-O/qubes-network-server) and Ansible to remotely manage a Qubes OS machine, and some or all VMs within it.

## Set up the SSH access on the Qubes server

Follow the [instructions to set up an SSH server on Qubes network server](https://github.com/Rudd-O/qubes-network-server/tree/master/doc/Setting up an SSH server.md).  We'll use the same conventions as outlined in that document for the rest of this tutorial.

## Set up Qubes policy for the `exp-manager` VM

Since our objective is to manage the entire server machine from the `exp-manager` VM, we need
to set up a policy that allows us to remotely execute commands on any VM of the Qubes
network server, without having to be physically present to click any dialogs authorizing
the execution of those commands.

In `dom0` of your Qubes server, edit `/etc/qubes/policy.d/80-ansible-qubes.policy` to add,
at the top of the file, a policy that looks like this:

```
qubes.VMShell    *    managevm     *      allow
```

This tells Qubes OS that `exp-manager` is now authorized to run any command in any of the VMs.

**Security note**: this does mean that anyone with access to `exp-manager` can do
literally anything on any of your VMs in your Qubes OS server.

If that is not what you want, then replace `*` after `managevm` with the name of the VMs you
would like to manage.  For example: if you would like `exp-manager` to be authorized to run
commands *only* on `exp-net`, then you can use the following policy:

```
qubes.VMShell    *      exp-manager   exp-net   allow
qubes.VMShell    *      exp-manager   @anyvm    deny
```

Try it out now.  SSH from your manager machine into `exp-manager` and run:

```
qvm-run exp-net 'echo yes ; hostname'
```

You should see `yes` followed by `exp-net` on the output side.

### If you want `exp-manager` to also run commands on `dom0`

If you expect that you will need to run commands in `dom0` from your manager machine
(say, to create, stop, start and modify VMs in the Qubes OS server),
then you will have to create a file `/etc/qubes-rpc/qubes.VMShell` as `root` in `dom0`,
with the contents `/bin/bash` and permission mode `0755`.  Doing this will enable you
to run commands on `dom0` which you can subsequently test in `exp-manager` by running command:

```
qvm-run dom0 'echo yes ; hostname'
```

like you did before.

**Security note**: this does mean that anyone with access to `exp-manager` can do
*literally anything* on your Qubes OS server.  You have been warned.

## Integrate your Ansible setup

Assuming you have set up Ansible on your manager machine, [integrate
Ansible Qubes into your setup](./Enhance your Ansible with Ansible Qubes.md).

Now test that you can run commands using `qrun`.  In your manager
machine, run in a terminal:

```
qrun --proxy=x.y.z.w exp-net hostname
```

This should immediately return with `exp-net` as output on the terminal,
indicating that `qrun` successfully connected to `exp-manager` and then
invoked `bombshell-client` on it, requesting the execution of `hostname`
on `exp-net`.

Now, to your Ansible `hosts` file, add an inventory entry:

```
exp-manager  ansible_connection=ssh ansible_ssh_host=x.y.z.w
```

Try to see if your `exp-manager` responds to Ansible now.  On your
manager machine, run:

```
ansible exp-manager -m shell -a "hostname ; whoami"
```

You should see `exp-manager` promptly followed by `user` on the output.

## Add VMs you want to manage to your Ansible setup

At this point, all you must do is add to your Ansible `hosts` file
any number of VMs you want to manage.  For example, if you'd like to
run commands on `exp-net`, you'd add it as follows:

```
exp-net   ansible_connection=qubes management_proxy=x.y.z.w
```

This tells Ansible to use the Qubes connection plugin, and to proxy its
`bombshell-client` connection through `exp-manager`.  The
`management_proxy` host variable tells the Ansible Qubes connection plugin
to first bridge the connection via SSH over to the target VM, and to then
execute `bombshell-client` to gain access to `exp-manager`.

Thus, in your manager machine, run:

```
ansible exp-net -m shell -a "hostname ; whoami"
```

Ansible should promptly print `exp-net` followed by `user`.

If you set up `dom0` to run commands on it, the same configuration can
be applied to it.  In your `hosts` file, add:

```
dom0      ansible_connection=qubes management_proxy=x.y.z.w
```

Then, in your manager machine, run:

```
ansible dom0 -m shell -a "hostname"
```

Ansible should promptly print `dom0`.
