Qubes OS DevOps automation toolkit: sample playbooks
============================================

Here are a few sample playbooks.  These assume that you already have an
[Ansible Qubes setup](../examples/ansible/) going, and so that consequently
you can drop the files of the example directly into your setup.

* [wakeupservice/](wakeupservice/) sets up a post-wakeup systemd service
   in your templates.  This service is not controllable via the Qubes OS
   service preferences for your VMs, [but it could be](../ansible/qubes-service.yml).
