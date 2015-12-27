Qubes OS DevOps automation toolkit: Provisioning example
========================================================

This example shows how to use the `qubesformation` and `qubessls`
action plugins to:

* automatically provision a number of VMs entirely based on your Ansible
   inventory, as well as
* alter and enforce settings on your provisioned VMs over time.

These Ansible plugins leverage the newly-added
[Salt management stack in Qubes 3.1](https://www.qubes-os.org/news/2015/12/14/mgmt-stack/)
in a very simple way: they use your inventory information to generate
a Salt formula (a "top"), and then use the `qubesctl` command to realize
said formula.

This example assumes you are familiar with:

* [the previous example](../ansible/)
* Ansible concepts like the inventory, host vars, group vars, and the like
* the [Salt management stack in Qubes](https://www.qubes-os.org/news/2015/12/14/mgmt-stack/)
* how to set up your [`ansible.cfg`](./ansible.cfg) to point Ansible to the
   `library` and `action_plugins` directories containing the requisite code.

Additionally, we assume that you are running this sample Ansible setup within
an AppVM on your Qubes OS machine -- similar to what we did in the basic
example mentioned before.

Defining the inventory
----------------------

Let's start by examining the [inventory file](./hosts).  What do we
see?

1. Our targets under `# Hosts defined here`.  For the purposes of this example,
   these will be the VMs we will configure, as well as the templates we will
   rely on, and finally the `dom0` machine where the magic will happen.
2. A list of `[groups]` that identify VMs based on the type.  You can group
   your own VMs however you like.  The key characteristic of these groups,
   however, is that the all the groups are listed under `[vms:children]`,
   which tells Ansible there's a "group of groups" called `vms`, that
   includes all VMs we will manage in this example.
3. A configuration variable applied to *all*hosts under the stanza
   `[all:vars]`.  This tells Ansible that all of the hosts it knows about,
   it must contact via the [Qubes connection plug-in for Ansible](../../ansible/connection_plugins/qubes.py).

Defining the requisite variables for the creation of the formula
----------------------------------------------------------------

At this point, we need to assign a few variables to each VM we want
to provision.  Due to the fact that this example's Ansible configuration
already includes `hash_behaviour = merge` to merge variables
from different sources, this process will be very easy and flexible.

Let's start by defining which inventory host will be
the `dom0` for all of the VMs (yes, this system is compatible
with it being used on multiple Qubes OS machines, so we cannot just
assume that there's a single `dom0`).

Look at the [group vars file for the group `vms`](group_vars/vms.yml).
This vars file contains one dictionary `qubes`, with a sole attribute
`dom0_vm`.  Since this attribute will be inherited (as per Ansible variable
precedence) by all VMs in the super-group `vms`, we've effectively told
Ansible that all VMs have `dom0` as their `dom0_vm`.

Now let's direct our attention to [host vars](host_vars/).  You'll note there
are a few notable attributes we are defining per hosts:

* `qubes.template_vm`: designates which VM will be used as a template
   for the VM in question.  Note how most VMs have `app-template`
   as their template, except for `app-template` itself, which has `fedora-23`
   as template -- this will tell the formula to clone `app-template` from
   `fedora-23` if it doesn't exist already.  Also note that `fedora-23` itself
   has no template -- this tells the formula to simply expect its existence.
   As `fedora-23` is generally a built-in template of Qubes, that should
   work as we expected.
* `qubes.vm_type`: this assigns the VM type we expect to instantiate.
   There are several types: TemplateVM, StandaloneVM, NetVM, ProxyVM
   and AppVM.  Depending on the type, the formula will perform a
   different action to bring the VM into existence.  Note that we could have
   set the attribute `vm_type` in a `group_vars` file for its type -- but,
   since this is a small example, we set the attribute directly in each
   `host_vars` file.
* `qubes.netvm_vm`: this assigns the NetVM to which the VM
   will be attached.  It's not mandatory to assign one -- in which case
   the system will automatically assign the default NetVM to the
   created VM.  To explicitly demand no NetVM, you can always say
   `netvm_vm: None`.  In our example, the VM we want to use as
   NetVM is almost always `firewall`, except in the case of `firewall`
   itself, in which case we use `wired-netvm`.
* `qubes.label`: sets the color label you're already familiar with.
* `qubes.pcidevs` and `qubes.services` set the PCI devices to
   attach to the VM, and the services to enable or disable.  `pcidevs`
   is a list of strings denoting PCI IDs in their short form (without the
   leading `0000`, as expected by `qvm-prefs`).  `services` is a
   dictionary of `{service_name: value}`, where the value is
   always one of `True` for enabled, `False` for disabled, or `None`
   for explicitly setting the service to its default value.  You'll note
   that we use these in the NetVM to attach a single PCI device,
   and to disable the memory balancing service (dangerous to
   use on a NetVM or any other VM with a PCI device on it).

This is all we really need to get on with it.  Of course, you can add
additional properties to each VM.  This system supports listing,
within the `qubes` dictionary of each VM, pretty much all properties
that `qvm-prefs` supports.

Ansible playbook
----------------

Now look at [the playbook](./realize-inventory.yml).  It targets your
`dom0`, which is precisely what you want.

There are four main plays in it:

1. Use the Salt subsystem in your dom0 to create the `/srv/user_salt`
   directory, which happens the first time that `qubesctl` is used to apply
   the highstate of the system.
2. Create the provisioning formula.  This formula is stored in
   `/srv/user_salt/myprovisionedvms.sls` and
   `/srv/user_salt/myprovisionedvms.top`.
3. Tell the Salt subsystem to activate the formula.  This won't actually
   realize the formula, but it will tell Salt that, from now on, every time
   a `qubesctl state.highstate` is applied, the formula must be
   enforced.
4. Finally, realize the formula.

Let's discuss steps 2 and 4, unique to this software project:

In step 2, we invoke the [`qubesformation` action plugin](../../ansible/action_plugins/qubesformation.py]).  This plugin will:

* identify the targeted dom0,
* collect all inventory hosts that have been declared to be in that dom0
   (via `qubes.dom0_vm`),
* identify their types, preferences, and other attributes as declared
   in the `qubes` variable for each inventory host,
* generate a SaltStack formula (the `.sls` file) that uses the Qubes
   Salt modules `qvm.*` to realize and enforce state,
* generate a SaltStack Qubes top file, that will let you activate
   or deactivate the formula as a single unit.

This formula is clever enough to know in which order to create and
reconfigure hosts, because you've provided it with all the necessary
information to make those determinations.

In step 4, all we do is simply tell the [`qubessls` action plugin](../../ansible/action_plugins/qubessls.py) to look for the `myprovisionedvms.sls`
and the `myprovisionedvms.top` files we created in step 2, then
actually realize them by executing them.  It is the equivalent of running
`qubesctl state.sls myprovisionedvms saltenv=user` on the
dom0 as root.

Testing the playbook
--------------------

Assuming you've modified the inventory and vars files to suit your
testing needs, you can now run the playbook:

    ansible-playbook -v realize-inventory.yml -t create

creates the `/srv/user_salt/myprovisionedvms.sls`.  Now take
a look at that file -- it should describe your infrastructure as you'd like
it to be (or perhaps even how it already is).

    ansible-playbook -v realize-inventory.yml -t realize

does the work to activate and realize the infrastructure as it was
described in `myprovisionedvms.sls`.

From this point on, every time you want to change properties in
your VMs, all you must do is run the playbook after changing
the appropriate variables.  The playbook will ensure that your
system remains compliant with what you've specified for it.

More will come as time goes by.  For now, that's all.  Happy hacking!
