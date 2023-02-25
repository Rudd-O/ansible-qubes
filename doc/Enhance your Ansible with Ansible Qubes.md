# Enhance your Ansible with Ansible Qubes

This set of instructions assumes that you:

* are running within a Qubes OS system
* have an AppVM already set up (we'll call it `managevm`)
* have cloned this repository into that VM
* have Ansible installed in that VM
* have an Ansible setup already going on within that VM

## Deploy the software to the right places

Integrate this software into your Ansible setup (within your `managevm`) VM) by:

1. setting up a `connections_plugin = <directory>` in your `ansible.cfg`
   file, pointing it to a directory you control, then
2. placing the `qubes.py` connection plugin in your Ansible
   `connection_plugins` directory as defined above, then
3. placing the `qrun` and `bombshell-client` executables in one of two
   locations:

  * Anywhere on your Ansible machine's `PATH`.
  * In a `../../bin` directory relative to the `qubes.py` file.

## Set up the policy file for `qubes.VMShell`

Edit (as `root`) the file `/etc/qubes/policy.d/80-ansible-qubes.policy`
located on the file system of your `dom0`.

At the top of the file, add the following two lines:

```
qubes.VMShell    *    managevm     *      allow
```

This first line lets `managevm` execute any commands on any VM on your
system.  You can also supply an `ask` policy instead of the `allow`
policy specified above.  Note that `ask` will make Qubes OS bother you
every time you run commands (and Ansible plays) with the standard
security prompt to allow `qubes.VMShell` on the target VM you're managing.

Now save that file, and exit your editor.

If your dom0 has a file `/etc/qubes-rpc/policy/qubes.VMShell`,
you can delete it now.  It is obsolete.

### Optional: allow `managevm` to manage `dom0`

The next step is to add the RPC service proper to dom0.  Edit the file
`/etc/qubes-rpc/qubes.VMShell` to have a single line that contains:

```
exec bash
```

Make the file executable.

That is it.  `dom0` should work now.  Note you do this at your own risk.


## Test `qrun` works

Test that `qrun` does the job.  In the VM where you integrated your
Ansible setup, run:

```
path/to/qrun <some VM> hostname
```

This should immediately return with the hostname of `<some VM>`,
indicating that `qrun` successfully invoked `bombshell-client` on it,
requesting the execution of `hostname` in `<some VM>`.

## Register VMs on your Ansible inventory

After having done that, you can add Qubes VMs to your Ansible `hosts` file:

```
# The next line declares a simple connection to a domU on the same system.
workvm          ansible_connection=qubes
# The next line has a parameter which indicates to Ansible to first
# connect to the domU SSH at 1.2.3.4 before attempting to use
# bombshell-client to manage other VMs on the same system.
# See README.md for pointers to enabling remote management of Qubes servers.
vmonremotehost  ansible_connection=qubes management_proxy=1.2.3.4
```

You are now free to run `ansible-playbook` or `ansible` against those hosts.
So long as those programs can find your `ansible.cfg` file, and your `hosts`
file, it will work.
