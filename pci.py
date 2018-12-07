import subprocess

def pci():
    p = subprocess.Popen(["ioreg","-l","-w0"], shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    bd, be = p.communicate()
    pc = False
    ckey = None
    find = "<class IOPCIDevice"
    lines = []
    pci_list = {}
    for line in bd.decode("utf-8").split("\n"):
        if find in line:
            # Found it - save the key
            lines = []
            try:
                ckey = line.split("+-o ")[1].split("  ")[0]
                pc = True
            except:
                # Wrong format, skip
                ckey = None
                pc = False
            continue
        if not pc:
            # Only progress if we're primed
            continue
        # At this point, we should be primed - let's check
        # to see if we have starting or ending brackets and
        # handle accordingly.
        if line.replace(" ","").replace("|","") == "{":
            # Opening bracket - not useful to us
            continue
        elif line.replace(" ","").replace("|","") == "}":
            # Closing bracket - let's close up our dict
            new = {}
            for l in lines:
                # Add the keys/values
                try:
                    k = l.split('"')[1]
                    v = l.split(" = ")[1]
                    new[k] = v
                except:
                    pass
            # Add the dict
            pci_list[ckey] = new
            # Reset the vars
            ckey = None
            lines = []
            pc = False
            continue
        # Not a starting or ending bracket - let's append the data
        lines.append(line)
    return pci_list