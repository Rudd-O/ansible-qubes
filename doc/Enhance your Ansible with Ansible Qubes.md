# Enhance your Ansible with Ansible Qubes

## Deploy the software to the right places

Integrate this software into your Ansible setup by:

1. setting up a `connections_plugin = <directory>` in your `ansible.cfg`
   file, pointing it to a directory you control, then
2. placing the `qubes.py` connection plugin in your Ansible
   `connection_plugins` directory as defined above, then
3. placing the `qrun` and `bombshell-client` executables in one of two
   locations:

  * Anywhere on your Ansible machine's `PATH`.
  * In a `../../bin` directory relative to the `qubes.py` file.

## Test `qrun` works

Test that `qrun` does the job.  In the VM where you integrated your
Ansible setup, run:

```
path/to/qrun <some VM> hostname
```

This should immediately return with the hostname of `<some VM>`,
indicating that `qrun` successfully invoked `bombshell-client` on it,
requesting the execution of `hostname` on `exp-net`.

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
file, it will work.  Note that Qubes OS will bother you every time you run
commands with the prompt to allow `qubes.VMShell` on the target VM you're
managing, unless you set said permission to default to yes (the pertinent
file to edit is in the `dom0` of the target Qubes OS machine, path
`/etc/qubes-rpc/policy/qubes.VMShell`).
