Qubes OS DevOps automation toolkit: Basic Ansible example
========================================================

This is an example of Ansible automation that leverages this toolkit to
let you manage Qubes VMs.  With it, you'll be managing dozens of VMs
(as well as any SSH-based remote host) in a fraction of the time it would
take to do so by hand or with shell scripts.

Hitting the ground running
--------------------------

Get yourself ready to test this example:

1. Create or designate an AppVM where you'll run this example.  We'll assume
   it will be called `manager` in this text.
2. Install the `git` and the `ansible` programs on the TemplateVM of that
   designated `manager` VM.  In the latest Qubes OS release,
   `sudo dnf install git ansible` from a terminal window would do the trick.
3. Power off both the `manager` and its Template VM.
4. Start the `manager` VM.
5. Open a terminal window on it.
6. `git clone` this project into `/home/user/ansible-qubes`.

You're ready to continue with this tutorial.  If you would like to get an
introduction on Ansible concepts parallel to reading this document, a
compare-and-contrast exercise with the
[Ansible introduction](https://docs.ansible.com/ansible/intro_getting_started.html)
would probably work very well.

Now, let's dive into this example Ansible setup.

Ansible configuration
---------------------

The starting point is the file [`ansible.cfg`](./ansible.cfg).  This file tells Ansible where
to find the requisite components to make the Qubes automation work.  As
you can see, it's composed mostly of paths, and it points you to the
[`hosts`](./hosts) file.

Importantly, because Ansible will look for the [`ansible.cfg`](./ansible.cfg) file
on your current directory first, that means you will be running your
Ansible commands on the directory containing [`ansible.cfg`](./ansible.cfg).  Later, you can
deploy aliases, symlinks or helpers to help you work around that.

Inventory
---------

The [`hosts`](./hosts) file is your machine inventory -- the VMs (and also physical
machines) that you own, and how they group together.  The included inventory
is almost certainly guaranteed not to match the machines you have, nor how
you've grouped them conceptually, so feel free to edit it how you see fit.  To
learn more about managing the inventory, check out [the relevant Ansible
documentation](https://docs.ansible.com/ansible/intro_inventory.html).

Two key things to note about the inventory:

1. You denote which machines are Qubes VMs by setting the `ansible_connection`
   property to `qubes` on the configuration line specifying the inventory
   entry.   Instead of a host name, you use the VM name to refer to the
   machine.
2. You can (of course, if the VM holding these files has network
   connectivity) mix and match hosts you can manage via SSH into your
   inventory.

How Ansible knows to connect to your Qubes VMs
----------------------------------------------

Importantly, nothing about this is magic.  `qubes` in the `ansible_connection`
parameter merely tells Ansible to use the
[Qubes connection plugin](../../ansible/connection_plugins/qubes.py)
as pointed to by the [`ansible.cfg`](./ansible.cfg) file.  That file automatically enlists
the `bombshell-client` technology to connect you to your VMs via Ansible.

When `bombshell-client` starts, it attempts to connect to the target VM's
`qubes.VMShell` service.  This is a small Qubes RPC stub that allows a calling
VM to execute any command on the target VM.  Of course, all of this is
always subject to the Qubes authorization mechanism, so it's secure.

Time to test drive it!
----------------------

Add some of your VMs to your inventory now.  Let's assume you've added your
`work` VM to the inventory, and that you are running this from a `manager`
VM you've created for the purpose.

Ready?

OK, let's try the following.  On the terminal window, type:

    ansible work -m shell -a whoami

Qubes OS will ask you for permission to run several shell commands from the
`manager` VM to the `work` VM.  Accept those prompts, and you'll see
something like this:

    [user@manager ansible]$ ansible work -m shell -a whoami
    work | success | rc=0 >>
    user

That's your `work` VM responding with `I am logged in as user`, which
happens to be the user that Ansible logged into your VM as.  The above
command line makes the `shell` module (specified in the command line as
`-m shell`) execute its arguments (specified with `-a`).  Ansible has a ton
of execution modules, and they are all documented here:

* [Intro to modules](https://docs.ansible.com/ansible/modules.html)
* [Module index](https://docs.ansible.com/ansible/modules_by_category.html)

Connecting to dom0
------------------

If you're running a bit ahead of these instructions, you may have noticed
that running `ansible dom0 -m shell whoami` actually results in an error.

This is by design from the Qubes team -- the `qubes.VMShell` service does
not ship in the `dom0` VM at all.  If you'd like to be able to manage `dom0`
from your configuration management system, all you need to do is deploy
the necessary configuration to `dom0`.

See the heading *Enabling bombshell-client access to dom0* in the [top-level
`README.md`](../../README.md) file of this toolkit for instructions on how to do that.

Running modules as root
-----------------------

You can, however, demand to execute commands as `root` wih the parameter `-s`:

    [user@manager ansible]$ ansible work -s -m shell -a whoami
    work | success | rc=0 >>
    root

`-s` makes the `shell` module execute its arguments as root.  In fact, it
makes any Ansible module run as root.  Ansible has a ton of execution modules, and they
are all documented here:

* [Intro to modules](https://docs.ansible.com/ansible/modules.html)
* [Module index](https://docs.ansible.com/ansible/modules_by_category.html)

Note that running as root may require the `sudo` package to be installed
first.   If you encounter problems getting to root, then please install
the `sudo` package on the VM you're targeting (or, more appropriately,
in its template, if it is a template-based VM).

Targeting multiple machines
---------------------------

So far, we've targeted only the `work` VM, but technically you can target any
machine or group of machines in your inventory.  Based on the (entirely
fictional) inventory shipped in this example:

* `ansible work:netvm ...` targets two VMs
* `ansible appvms ...` targets all VMs in a group `appvms`.
* `ansible 'all:!nonqubes' ...` targets all inventory machines minus the
   non-Qubes ones.

Playbooks
---------

Everything you've seen so far applies to simple `ansible` runs.  But the real
worth of Ansible is the possibility to weave repeatable, idempotent scripts
that involve multiple machines, so you're not constantly repeating yourself.
Enter [`ansible-playbook`](https://docs.ansible.com/ansible/playbooks.html),
generously documented there, and exemplified here.

For a quick primer on how to run playbooks, here are the essentials:

    ansible-playbook -v <playbook YML file> [-l <only these hosts>]

This would tell `ansible-playbook` to run every step of the playbook file
in order, on all the hosts the playbook targets.  Should you
want to limit your run to a subset of the hosts, you can use the `-l` argument
and pass those hosts, which are in the exact same format as the one
taken by the `ansible` command on its hosts specification list.

We ship several different sample playbooks:

* [`test-nofacts.yml`](./test-nofacts.yml): logs into the specified machines
   and retrieves variables, but without the fact gathering process, leaving
   the collected environment in a `/tmp/` directory.
* [`test-facts.yml`](./test-facts.yml): does the same thing, but collects
   facts about the targeted hosts before dumping the variables.
* [`editors.yml`](./editors.yml): deploys some text editors on your
   template VMs (assumed to be Fedora).
* [`qubes-service.yml`](./qubes-service.yml): deploys a Qubes service to
   your template VM, which can later be turned on via the Services tab
   of the properties window of VMs based on the template.  In the example,
   the service is named `qubes-helloworld`, so that would be the name
   of the service to add and enable on the Services tab.

More will come as time goes by.  For now, that's all.  Happy hacking!
