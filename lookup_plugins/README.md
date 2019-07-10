# Ansible Qubes Pass lookup plugin

This lookup plugin has the ability to look up a password in another Qubes VM
by using the excellent [`qubes-pass`](https://github.com/Rudd-O/qubes-pass)
to retrieve it from the VM.  It also (by default) automatically creates
password entries that do not exist yet, such that you do not have to ever
manually create passwords for your playbooks and variables.

Here is how you use it:

```
- hosts: myhost
  become: yes
  vars:
    thepassword: '{{ lookup("qubes-pass", "loginpwds/John Smith") }}'
  tasks:
  - copy:
      name: /root/mountcreds
      contents: '{{ thepassword }}'
      owner: root
      group: root
      mode: 0600
```

When executed, this simple playbook will set the variable `thepassword`
to the contents of the key `loginpwds/John Smith` in the password store
of your designated password store VM.  If the key does not exist, then
the key will be created automatically with a 32 character password.

You can also explicitly specify the VM:

```
    thepassword: '{{ lookup("qubes-pass", "loginpwds/John Smith", vm="vault") }}'
```

You can also disable automatic creation of the password.  This will simply
fail if the password does not exist:

```
    thepassword: '{{ lookup("qubes-pass", "loginpwds/John Smith", create=False) }}'
```

If the password you expect to fetch is multiline/binary, you can retrieve
it correctly like this:

```
    thepassword: '{{ lookup("qubes-pass", "loginpwds/John Smith", multiline=True) | b64encode }}'
```

then later base64 decode it on target.
