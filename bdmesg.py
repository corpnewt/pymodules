import binascii, subprocess

def bdmesg(just_clover = True):
    b = None
    if not just_clover:
        b = _bdmesg(["ioreg","-l","-p","IOService","-w0"])
    if not b:
        b = _bdmesg(["ioreg","-l","-p","IODeviceTree","-w0"])
    return b

def _bdmesg(comm):
    # Runs the passed command and searches for "boot-log"
    p = subprocess.Popen(comm, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    bd, be = p.communicate()
    for line in bd.decode("utf-8").split("\n"):
        # We're just looking for the "boot-log" property, then we need to format it
        if not '"boot-log"' in line:
            # Skip it!
            continue
        # Must have found it - let's try to split it, then get the hex data and process it
        try:
            # Split it up, then convert from hex to ascii
            return binascii.unhexlify(line.split("<")[1].split(">")[0].encode("utf-8")).decode("utf-8")
        except:
            # Failed to convert
            return None
    # Didn't find it
    return None
