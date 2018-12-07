import sys, os, json
sys.path.append(os.path.abspath(os.path.dirname(os.path.realpath(__file__))))
import run, utils

class Hosts:

    def __init__(self, **kwargs):
        # Set up some vars and things
        self.hosts = "/Windows/System32/Drivers/etc/hosts" if os.name=="nt" else "/private/etc/hosts"
        os.chdir(os.path.dirname(os.path.realpath(__file__)))
        # See if we have a "json" key - which supercedes all others
        j = kwargs.get("json", None)
        if j:
            # We have a json file listed
            cwd = os.getcwd()
            os.chdir(os.path.dirname(os.path.realpath(__file__)))
            if os.path.exists(j):
                kwargs = json.load(open(j))
            else:
                kwargs = {}
            os.chdir(cwd)
        # Setup vars
        self.blocks = kwargs.get("blocks", [])
        self.header = kwargs.get("header", "# Block Start #")
        self.footer = kwargs.get("footer", "# Block End #")
        self.r      = run.Run()
        self.u      = utils.Utils()

    def compare_hosts(self):
        found = []
        with open(self.hosts, "r") as f:
            for line in f:
                if line.strip().startswith("#"):
                    # Comment - skip
                    continue
                for i in self.blocks:
                    if i.lower() in line.lower() and not i in found:
                        found.append(i)
        # Return the percent of blocked items
        return round(len(found) / len(self.blocks) * 100)

    def flush_dns(self):
        if os.name == "nt":
            self.r.run({"args" : ["ipconfig", "/flushdns"]})
        else:
            # Assume macOS
            o = self.r.run({"args":["sw_vers", "-productVersion"]})
            if o[2]:
                return
            v = int(o[0].split(".")[1]) # Get the major OS version
            if v < 5:
                self.r.run({"args" : ["lookupd", "-flushcache"], "sudo" : True})
            elif v < 7:
                self.r.run({"args" : ["dscacheutil", "-flushcache"], "sudo" : True})
            elif v < 9:
                self.r.run({"args" : ["killall", "-HUP", "mDNSResponder"], "sudo" : True})
            elif v < 11:
                self.r.run({"args" : ["discoveryutil", "mdnsflushcache;", "discoveryutil", "udnsflushcaches"], "sudo" : True})
            else:
                self.r.run({"args" : ["killall", "-HUP", "mDNSResponder"], "sudo" : True})

    def block(self):
        # Let's gather up all the lines that could be a part of our block - and move them to the end
        new_hosts = ""
        with open(self.hosts, "r") as f:
            for line in f:
                line_trim = line.replace("\n", "")
                if line_trim.lower() in self.blocks or line_trim == self.header or line_trim == self.footer:
                    # We found one of ours - omit it
                    continue
                # Not in our list
                new_hosts += line
        if len(new_hosts) and not new_hosts[-1] == "\n":
            # Doesn't end with a newline
            new_hosts += "\n"
        new_hosts += self.header + "\n"
        for block in self.blocks:
            new_hosts += block + "\n"
        new_hosts += self.footer
        with open(self.hosts, "w") as f:
            f.write(new_hosts)
        self.flush_dns()

    def unblock(self):
        new_hosts = ""
        with open(self.hosts, "r") as f:
            for line in f:
                line_trim = line.replace("\n", "")
                if line_trim.lower() in self.blocks or line_trim == self.header or line_trim == self.footer:
                    # We found one of ours - omit it
                    continue
                # Not in our list
                new_hosts += line
        with open(self.hosts, "w") as f:
            f.write(new_hosts)
        self.flush_dns()