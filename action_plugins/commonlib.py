import collections
import copy


def inject_qubes(inject):
    myname = inject["inventory_hostname"]
    akk = collections.OrderedDict()
    all_pcidevs = dict()
    for invhostname in inject["groups"]["all"]:
        if invhostname == myname:
            continue
        hostvars = inject["hostvars"][invhostname]
        if hostvars.get("qubes", {}).get("dom0_vm") == myname:
            akk[invhostname] = copy.deepcopy(hostvars)
    for invhostname, hostvars in akk.items():
        qubes = hostvars["qubes"]
        dominv = qubes["dom0_vm"]
        for dev in qubes.get("pcidevs", []):
            if all_pcidevs.get(dev):
                assert t in akk, (
                    "while processing attribute pcidevs of VM %s: "
                    "device %s already in use by VM %s"
                ) % (
                    invhostname,
                    dev,
                    all_pcidevs[dev],
                )
            all_pcidevs[dev] = invhostname
        for vmitem in ["template_vm", "netvm_vm"]:
            if vmitem == "template_vm":
                if "_template" in hostvars and not "template_vm" in qubes:
                    qubes["template_vm"] = hostvars["_template"]
                elif invhostname + "-template" in inject["groups"]:
                    qubes["template_vm"] = inject["groups"][invhostname + "-template"][0]
            if vmitem in qubes:
                t = qubes[vmitem]
                if t is None or t.lower() == "none":
                    qubes[vmitem[:-3]] = None
                else:
                    if t.startswith("sibling(") and t.endswith(")"):
                        t = t[len("sibling("):-1]
                        dompostfix = dominv.split(".")[1:]
                        dompostfix = "." + ".".join(dompostfix) if dompostfix else ""
                        t = t + dompostfix
                    assert t in akk, (
                        "while processing attribute %s of VM %s: "
                        "%s not found in VMs of %s: %s"
                    ) % (
                        vmitem,
                        invhostname,
                        t,
                        dominv,
                        ", ".join(akk)
                    )
                    qubes[vmitem[:-3]] = t
                del qubes[vmitem]
        enabledservices = []
        disabledservices = []
        defaultservices = []
        for service, status in qubes.get("services", {}).items():
            if status == "default" or status == None:
                defaultservices.append(service)
            elif status == True:
                enabledservices.append(service)
            elif status == False:
                disabledservices.append(service)
            else:
                assert 0, "while processing service %s of VM %s: invalid value %r" % (
                    service, invhostname, status
                )
        if enabledservices or disabledservices or defaultservices:
            qubes["services"] = collections.OrderedDict()
            if enabledservices:
                qubes["services"]["enable"] = enabledservices
            if disabledservices:
                qubes["services"]["disable"] = disabledservices
            if defaultservices:
                qubes["services"]["disable"] = defaultservices
        elif "services" in qubes:
            del qubes["services"]
        try:
            vmtype = qubes["vm_type"]
        except KeyError:
            assert 0, "while processing attribute %s of VM %s: attribute not set" % (
                "vm_type", invhostname
            )
        flags = qubes.get("flags", [])
        def add(l, v):
            if v not in l:
                l.append(v)
        if vmtype == "NetVM":
            add(flags, "net")
        elif vmtype == "StandaloneVM":
            add(flags, "standalone")
        elif vmtype == "AppVM":
            pass
        elif vmtype == "ProxyVM":
            add(flags, "proxy")
        elif vmtype == "DispVM":
            pass
        elif vmtype == "TemplateVM":
            try:
                qubes["source"] = qubes["template"]
                del qubes["template"]
            except KeyError:
                if "source" in qubes:
                    del qubes["source"]
        else:
            assert 0, "while processing attribute %s of VM %s: VM type %s unsupported" % (
                "vm_type", invhostname, vmtype
            )
        if flags:
            qubes["flags"] = flags
        else:
            if "flags" in qubes:
                del qubes["flags"]
    return akk
