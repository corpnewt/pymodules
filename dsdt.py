import os, errno, tempfile, shutil, plistlib, sys, binascii, zipfile, getpass, re
from . import run, downloader, utils

try:
    FileNotFoundError
except NameError:
    FileNotFoundError = IOError

class DSDT:
    def __init__(self, **kwargs):
        self.dl = downloader.Downloader()
        self.r  = run.Run()
        self.u  = utils.Utils("SSDT Time")
        self.iasl_url_macOS = "https://raw.githubusercontent.com/acidanthera/MaciASL/master/Dist/iasl-stable"
        self.iasl_url_macOS_legacy = "https://raw.githubusercontent.com/acidanthera/MaciASL/master/Dist/iasl-legacy"
        self.iasl_url_linux = "https://raw.githubusercontent.com/corpnewt/linux_iasl/main/iasl.zip"
        self.iasl_url_linux_legacy = "https://raw.githubusercontent.com/corpnewt/iasl-legacy/main/iasl-legacy-linux.zip"
        self.acpi_github_windows = "https://github.com/acpica/acpica/releases/latest"
        self.acpi_binary_tools = "https://www.intel.com/content/www/us/en/developer/topic-technology/open/acpica/download.html"
        self.iasl_url_windows_legacy = "https://raw.githubusercontent.com/corpnewt/iasl-legacy/main/iasl-legacy-windows.zip"
        self.h = {} # {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        self.iasl = self.check_iasl()
        self.iasl_legacy = self.check_iasl(legacy=True)
        if not self.iasl:
            url = (self.acpi_github_windows,self.acpi_binary_tools) if os.name=="nt" else \
            self.iasl_url_macOS if sys.platform=="darwin" else \
            self.iasl_url_linux if sys.platform.startswith("linux") else None
            exception = "Could not locate or download iasl!"
            if url:
                exception += "\n\nPlease manually download {} from:\n - {}\n\nAnd place in:\n - {}\n".format(
                    "and extract iasl.exe and acpidump.exe" if os.name=="nt" else "iasl",
                    "\n - ".join(url) if isinstance(url,(list,tuple)) else url,
                    os.path.dirname(os.path.realpath(__file__))
                )
            raise Exception(exception)
        self.allowed_signatures = (b"APIC",b"DMAR",b"DSDT",b"SSDT")
        self.mixed_listing      = (b"DSDT",b"SSDT")
        self.acpi_tables = {}
        # Setup regex matches
        self.hex_match  = re.compile(r"^\s*[0-9A-F]{4,}:(\s[0-9A-F]{2})+(\s+\/\/.*)?$")
        self.type_match = re.compile(r".*(?P<type>Processor|Scope|Device|Method|Name) \((?P<name>[^,\)]+).*")

    def _table_signature(self, table_path, table_name = None, data = None):
        path = os.path.join(table_path,table_name) if table_name else table_path
        if not os.path.isfile(path):
            return None
        if data:
            # Got data - make sure there's enough for a signature
            if len(data) >= 4:
                return data[:4]
            else:
                return None
        # Try to load it and read the first 4 bytes to verify the
        # signature
        with open(path,"rb") as f:
            try:
                return f.read(4)
            except:
                pass
        return None

    def non_ascii_count(self, data):
        # Helper to emulate the ACPI_IS_ASCII macro from ACPICA's code
        # It just appears to check if the passed byte is < 0x80
        # We'll check all available data though - and return the number
        # of non-ascii bytes
        non_ascii = 0
        for b in data:
            if not isinstance(b,int):
                try: b = ord(b)
                except: b = -1
            if not b < 0x80:
                non_ascii += 1
        return non_ascii

    def table_is_valid(self, table_path, table_name = None, ensure_binary = True, check_signature = True):
        # Ensure we have a valid file
        path = os.path.join(table_path,table_name) if table_name else table_path
        if not os.path.isfile(path):
            return False
        # Set up a data placeholder
        data = None
        if ensure_binary is not None:
            # Make sure the table is the right type - load it
            # and read the data
            with open(path,"rb") as f:
                data = f.read()
            # Make sure we actually got some data
            if not data:
                return False
            # Gather the non-ASCII char count
            non_ascii_count = self.non_ascii_count(data)
            if ensure_binary and not non_ascii_count:
                # We want a binary, but it's all ascii
                return False
            elif not ensure_binary and non_ascii_count:
                # We want ascii, and got a binary
                return False
        if check_signature:
            if not self._table_signature(path,data=data) in self.allowed_signatures:
                # Check with the function - we didn't load the table
                # already
                return False
        # If we got here - the table passed our checks
        return True

    def get_ascii_print(self, data):
        # Helper to sanitize unprintable characters by replacing them with
        # ? where needed
        unprintables = False
        ascii_string = ""
        for b in data:
            if not isinstance(b,int):
                try: b = ord(b)
                except: b = -1
            if ord(" ") <= b < ord("~"):
                ascii_string += chr(b)
            else:
                ascii_string += "?"
                unprintables = True
        return (unprintables,ascii_string)

    def load(self, table_path):
        # Attempt to load the passed file - or if a directory
        # was passed, load all .aml and .dat files within
        cwd = os.getcwd()
        temp = None
        target_files = {}
        failed = []
        try:
            if os.path.isdir(table_path):
                # Got a directory - gather all valid
                # files in the directory
                valid_files = [
                    x for x in os.listdir(table_path) if self.table_is_valid(table_path,x)
                ]
            elif os.path.isfile(table_path):
                # Just loading the one table - don't check
                # the signature - but make sure it's binary
                if self.table_is_valid(table_path,check_signature=False):
                    valid_files = [table_path]
                else:
                    # Not valid - raise an error
                    raise FileNotFoundError(
                        errno.ENOENT,
                        os.strerror(errno.ENOENT),
                        "{} is not a valid .aml/.dat file.".format(table_path)
                    )
            else:
                # Not a valid path
                raise FileNotFoundError(
                    errno.ENOENT,
                    os.strerror(errno.ENOENT),
                    table_path
                )
            if not valid_files:
                # No valid files were found
                raise FileNotFoundError(
                    errno.ENOENT,
                    os.strerror(errno.ENOENT),
                    "No valid .aml/.dat files found at {}".format(table_path)
                )
            # Create a temp dir and copy all files there
            temp = tempfile.mkdtemp()
            for file in valid_files:
                shutil.copy(
                    os.path.join(table_path,file),
                    temp
                )
            # Build a list of all target files in the temp folder - and save
            # the disassembled_name for each to verify after
            list_dir = os.listdir(temp)
            for x in list_dir:
                if len(list_dir) > 1 and not self.table_is_valid(temp,x):
                    continue # Skip invalid files when multiple are passed
                name_ext = [y for y in os.path.basename(x).split(".") if y]
                if name_ext and name_ext[-1].lower() in ("asl","dsl"):
                    continue # Skip any already disassembled files
                target_files[x] = {
                    "assembled_name": os.path.basename(x),
                    "disassembled_name": ".".join(x.split(".")[:-1]) + ".dsl",
                }
            if not target_files:
                # Somehow we ended up with none?
                raise FileNotFoundError(
                    errno.ENOENT,
                    os.strerror(errno.ENOENT),
                    "No valid .aml/.dat files found at {}".format(table_path)
                )
            os.chdir(temp)
            # Generate and run a command
            dsdt_or_ssdt = [x for x in list(target_files) if self._table_signature(temp,x) in self.mixed_listing]
            other_tables = [x for x in list(target_files) if not x in dsdt_or_ssdt]
            out_d = ("","",0)
            out_t = ("","",0)

            def exists(folder_path,file_name):
                # Helper to make sure the file exists and has a non-Zero size
                check_path = os.path.join(folder_path,file_name)
                if os.path.isfile(check_path) and os.stat(check_path).st_size > 0:
                    return True
                return False
            
            # Check our DSDT and SSDTs first
            if dsdt_or_ssdt:
                args = [self.iasl,"-da","-dl","-l"]+list(dsdt_or_ssdt)
                out_d = self.r.run({"args":args})
                if out_d[2] != 0:
                    # Attempt to run without `-da` if the above failed
                    args = [self.iasl,"-dl","-l"]+list(dsdt_or_ssdt)
                    out_d = self.r.run({"args":args})
                # Get a list of disassembled names that failed
                fail_temp = []
                for x in dsdt_or_ssdt:
                    if not exists(temp,target_files[x]["disassembled_name"]):
                        fail_temp.append(x)
                # Let's try to disassemble any that failed individually
                for x in fail_temp:
                    args = [self.iasl,"-dl","-l",x]
                    self.r.run({"args":args})
                    if not exists(temp,target_files[x]["disassembled_name"]):
                        failed.append(x)
            # Check for other tables (DMAR, APIC, etc)
            if other_tables:
                args = [self.iasl]+list(other_tables)
                out_t = self.r.run({"args":args})
                # Get a list of disassembled names that failed
                for x in other_tables:
                    if not exists(temp,target_files[x]["disassembled_name"]):
                        failed.append(x)
            if len(failed) == len(target_files):
                raise Exception("Failed to disassemble - {}".format(", ".join(failed)))
            # Actually process the tables now
            to_remove = []
            for file in target_files:
                # We need to load the .aml and .dsl into memory
                # and get the paths and scopes
                if not exists(temp,target_files[file]["disassembled_name"]):
                    to_remove.append(file)
                    continue
                with open(os.path.join(temp,target_files[file]["disassembled_name"]),"r") as f:
                    target_files[file]["table"] = f.read()
                    # Remove the compiler info at the start
                    if target_files[file]["table"].startswith("/*"):
                        target_files[file]["table"] = "*/".join(target_files[file]["table"].split("*/")[1:]).strip()
                    # Check for "Table Header:" or "Raw Table Data: Length" and strip everything
                    # after the last occurrence
                    for h in ("\nTable Header:","\nRaw Table Data: Length"):
                        if h in target_files[file]["table"]:
                            target_files[file]["table"] = h.join(target_files[file]["table"].split(h)[:-1]).rstrip()
                            break # Bail on the first match
                    target_files[file]["lines"] = target_files[file]["table"].split("\n")
                    target_files[file]["scopes"] = self.get_scopes(table=target_files[file])
                    target_files[file]["paths"] = self.get_paths(table=target_files[file])
                with open(os.path.join(temp,file),"rb") as f:
                    table_bytes = f.read()
                    target_files[file]["raw"] = table_bytes
                    # Let's read the table header and get the info we need
                    #
                    # [0:4]   = Table Signature
                    # [4:8]   = Length (little endian)
                    # [8]     = Compliance Revision
                    # [9]     = Checksum
                    # [10:16] = OEM ID (6 chars, padded to the right with \x00)
                    # [16:24] = Table ID (8 chars, padded to the right with \x00)
                    # [24:28] = OEM Revision (little endian)
                    # 
                    target_files[file]["signature"] = table_bytes[0:4]
                    target_files[file]["revision"]  = table_bytes[8]
                    target_files[file]["oem"]       = table_bytes[10:16]
                    target_files[file]["id"]        = table_bytes[16:24]
                    target_files[file]["oem_revision"] = int(binascii.hexlify(table_bytes[24:28][::-1]),16)
                    target_files[file]["length"]    = len(table_bytes)
                    # Get the printable versions of the sig, oem, and id as needed
                    for key in ("signature","oem","id"):
                        unprintable,ascii_string = self.get_ascii_print(target_files[file][key])
                        if unprintable:
                            target_files[file][key+"_ascii"] = ascii_string
                    # Cast as int on py2, and try to decode bytes to strings on py3
                    if 2/3==0:
                        target_files[file]["revision"] = int(binascii.hexlify(target_files[file]["revision"]),16)
                if target_files[file]["signature"] in self.mixed_listing:
                    # The disassembler omits the last line of hex data in a mixed listing
                    # file... convenient.  However - we should be able to reconstruct this
                    # manually.
                    last_hex = next((l for l in target_files[file]["lines"][::-1] if self.is_hex(l)),None)
                    if last_hex:
                        # Get the address left of the colon
                        addr = int(last_hex.split(":")[0].strip(),16)
                        # Get the hex bytes right of the colon
                        hexs = last_hex.split(":")[1].split("//")[0].strip()
                        # Increment the address by the number of hex bytes
                        next_addr = addr+len(hexs.split())
                        # Now we need to get the bytes at the end
                        hexb = self.get_hex_bytes(hexs.replace(" ",""))
                        # Get the last occurrence after the split
                        remaining = target_files[file]["raw"].split(hexb)[-1]
                    else:
                        # If we didn't get a last hex val - then we likely don't have any
                        # This can happen if the file passed is small enough, or has all
                        # the data in a single block.
                        next_addr = 0
                        remaining = target_files[file]["raw"]
                    # Iterate in chunks of 16
                    for chunk in [remaining[i:i+16] for i in range(0,len(remaining),16)]:
                        # Build a new byte string
                        hex_string = binascii.hexlify(chunk)
                        # Decode the bytes if we're on python 3
                        if 2/3!=0: hex_string = hex_string.decode()
                        # Ensure the bytes are all upper case
                        hex_string = hex_string.upper()
                        l = "   {}: {}".format(
                            hex(next_addr)[2:].upper().rjust(4,"0"),
                            " ".join([hex_string[i:i+2] for i in range(0,len(hex_string),2)])
                        )
                        # Increment our address
                        next_addr += len(chunk)
                        # Append our line
                        target_files[file]["lines"].append(l)
                        target_files[file]["table"] += "\n"+l
            # Remove any that didn't disassemble
            for file in to_remove:
                target_files.pop(file,None)
        except Exception as e:
            print(e)
            return ({},failed)
        finally:
            os.chdir(cwd)
            if temp: shutil.rmtree(temp,ignore_errors=True)
        # Add/update any tables we loaded
        for table in target_files:
            self.acpi_tables[table] = target_files[table]
        # Only return the newly loaded results
        return (target_files, failed,)

    def get_latest_iasl(self):
        # First try getting from github - if that fails, fall back to intel.com
        try:
            source = self.dl.get_string(self.acpi_github_windows, progress=False, headers=self.h)
            assets_url = None
            # Check for attachments first
            for line in source.split("\n"):
                if '<a href="https://github.com/user-attachments/files/' in line \
                and "/iasl-win-" in line and '.zip"' in line:
                    # We found it - return the URL
                    return line.split('<a href="')[1].split('"')[0]
                if 'src="' in line and "expanded_assets" in line:
                    # Save the URL for later in case we need it
                    assets_url = line.split('src="')[1].split('"')[0]
            # If we got here - we didn't find the link in the attachments,
            # check in the expanded assets
            if assets_url:
                source = self.dl.get_string(assets_url, progress=False, headers=self.h)
                iasl = acpidump = None # Placeholders
                for line in source.split("\n"):
                    # Check for any required assets
                    if '<a href="/acpica/acpica/releases/download/' in line:
                        # Check if we got iasl.exe or acpidump.exe
                        if '/iasl.exe"' in line:
                            iasl = "https://github.com{}".format(line.split('"')[1].split('"')[0])
                        if '/acpidump.exe"' in line:
                            acpidump = "https://github.com{}".format(line.split('"')[1].split('"')[0])
                if iasl and acpidump:
                    # Got the needed files, return them
                    return (iasl,acpidump)
            # If we got here - move on to intel.com
        except: pass
        # Helper to scrape https://www.intel.com/content/www/us/en/developer/topic-technology/open/acpica/download.html for the latest
        # download binaries link - then scrape the contents of that page for the actual download as needed
        try:
            source = self.dl.get_string(self.acpi_binary_tools, progress=False, headers=self.h)
            for line in source.split("\n"):
                if '<a href="' in line and ">iasl compiler and windows acpi tools" in line.lower():
                    # Check if we have a direct download link - i.e. ends with .zip - or if we're
                    # redirected to a different download page - i.e. ends with .html
                    dl_link = line.split('<a href="')[1].split('"')[0]
                    if dl_link.lower().endswith(".zip"):
                        # Direct download - return as-is
                        return dl_link
                    elif dl_link.lower().endswith((".html",".htm")):
                        # Redirect - try to scrape for a download link
                        try:
                            if dl_link.lower().startswith(("http:","https:")):
                                # The existing link is likely complete - use it as-is
                                dl_page_url = dl_link
                            else:
                                # <a href="/content/www/us/en/download/774881/acpi-component-architecture-downloads-windows-binary-tools.html">iASL Compiler and Windows ACPI Tools
                                # Only a suffix - prepend to it
                                dl_page_url = "https://www.intel.com" + line.split('<a href="')[1].split('"')[0]
                            dl_page_source = self.dl.get_string(dl_page_url, progress=False, headers=self.h)
                            for line in dl_page_source.split("\n"):
                                if 'data-href="' in line and '"download-button"' in line:
                                    # Should have the right line
                                    return line.split('data-href="')[1].split('"')[0]
                        except: pass
        except: pass
        return None
    
    def check_iasl(self, legacy=False, try_downloading=True):
        if sys.platform == "win32":
            targets = (os.path.join(os.path.dirname(os.path.realpath(__file__)), "iasl-legacy.exe" if legacy else "iasl.exe"),)
        else:
            if legacy:
                targets = (os.path.join(os.path.dirname(os.path.realpath(__file__)), "iasl-legacy"),)
            else:
                targets = (
                    os.path.join(os.path.dirname(os.path.realpath(__file__)), "iasl-dev"),
                    os.path.join(os.path.dirname(os.path.realpath(__file__)), "iasl-stable"),
                    os.path.join(os.path.dirname(os.path.realpath(__file__)), "iasl")
                )
        target = next((t for t in targets if os.path.exists(t)),None)
        if target or not try_downloading:
            # Either found it - or we didn't, and have already tried downloading
            return target
        # Need to download
        temp = tempfile.mkdtemp()
        try:
            if sys.platform == "darwin":
                self._download_and_extract(temp,self.iasl_url_macOS_legacy if legacy else self.iasl_url_macOS)
            elif sys.platform.startswith("linux"):
                self._download_and_extract(temp,self.iasl_url_linux_legacy if legacy else self.iasl_url_linux)
            elif sys.platform == "win32":
                iasl_url_windows = self.iasl_url_windows_legacy if legacy else self.get_latest_iasl()
                if not iasl_url_windows: raise Exception("Could not get latest iasl for Windows")
                self._download_and_extract(temp,iasl_url_windows)
            else: 
                raise Exception("Unknown OS")
        except Exception as e:
            print("An error occurred :(\n - {}".format(e))
        shutil.rmtree(temp, ignore_errors=True)
        # Check again after downloading
        return self.check_iasl(legacy=legacy,try_downloading=False)

    def _download_and_extract(self, temp, url):
        script_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)))
        if not isinstance(url,(tuple,list)):
            url = (url,) # Wrap in a tuple
        for u in url:
            ztemp = tempfile.mkdtemp(dir=temp)
            zfile = os.path.basename(u)
            print("Downloading {}".format(zfile))
            self.dl.stream_to_file(u, os.path.join(ztemp,zfile), progress=False, headers=self.h)
            search_dir = ztemp
            if zfile.lower().endswith(".zip"):
                print(" - Extracting")
                search_dir = tempfile.mkdtemp(dir=temp)
                # Extract with built-in tools \o/
                with zipfile.ZipFile(os.path.join(ztemp,zfile)) as z:
                    z.extractall(search_dir)
            for x in os.listdir(search_dir):
                if x.lower().startswith(("iasl","acpidump")):
                    # Found one
                    print(" - Found {}".format(x))
                    if sys.platform != "win32":
                        print("   - Chmod +x")
                        self.r.run({"args":["chmod","+x",os.path.join(search_dir,x)]})
                    print("   - Copying to {} directory".format(os.path.basename(script_dir)))
                    shutil.copy(os.path.join(search_dir,x), os.path.join(script_dir,x))

    def dump_tables(self, output, disassemble=False):
        # Helper to dump all ACPI tables to the specified
        # output path
        def check_command_output(out):
            if out[2] == 0: return False
            print(" - {}".format(out[1]))
            return True
        self.u.head("Dumping ACPI Tables")
        print("")
        res = self.check_output(output)
        if os.name == "nt":
            target = os.path.join(os.path.dirname(os.path.realpath(__file__)),"acpidump.exe")
            if os.path.exists(target):
                # Dump to the target folder
                print("Dumping tables to {}...".format(res))
                cwd = os.getcwd()
                os.chdir(res)
                out = self.r.run({"args":[target,"-b"]})
                os.chdir(cwd)
                if check_command_output(out):
                    return
                # Make sure we have a DSDT
                if not next((x for x in os.listdir(res) if x.lower().startswith("dsdt.")),None):
                    # We need to try and dump the DSDT individually - this sometimes
                    # happens on older Windows installs or odd OEM machines
                    print(" - DSDT not found - dumping by signature...")
                    os.chdir(res)
                    out = self.r.run({"args":[target,"-b","-n","DSDT"]})
                    os.chdir(cwd)
                    if check_command_output(out):
                        return
                # Iterate the dumped files and ensure the names are uppercase, and the
                # extension used is .aml, not the default .dat
                print("Updating names...")
                for f in os.listdir(res):
                    new_name = f.upper()
                    if new_name.endswith(".DAT"):
                        new_name = new_name[:-4]+".aml"
                    if new_name != f:
                        # Something changed - print it and rename it
                        try:
                            os.rename(os.path.join(res,f),os.path.join(res,new_name))
                        except Exception as e:
                            print(" - {} -> {} failed: {}".format(f,new_name,e))
                print("Dump successful!")
                if disassemble:
                    return self.load(res)
                return res
            else:
                print("Failed to locate acpidump.exe")
                return
        elif sys.platform.startswith("linux"):
            table_dir = "/sys/firmware/acpi/tables"
            if not os.path.isdir(table_dir):
                print("Could not locate {}!".format(table_dir))
                return
            print("Copying tables to {}...".format(res))
            copied_files = []
            for table in os.listdir(table_dir):
                if not os.path.isfile(os.path.join(table_dir,table)):
                    continue # We only want files
                target_path = os.path.join(res,table.upper()+".aml")
                comms = (
                    # Copy the file
                    ["sudo","cp",os.path.join(table_dir,table),target_path],
                    # Ensure it's owned by the user account
                    ["sudo","chown",getpass.getuser(),target_path],
                    # Enable read and write permissions
                    ["sudo","chmod","a+rw",target_path]
                )
                # Iterate our commands and bail if any error
                for comm in comms:
                    out = self.r.run({"args":comm})
                    if check_command_output(out):
                        return
            print("Dump successful!")
            if disassemble:
                return self.load(res)
            return res

    def check_output(self, output):
        t_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), output)
        if not os.path.isdir(t_folder):
            os.makedirs(t_folder)
        return t_folder

    def get_hex_from_int(self, total, pad_to = 4):
        hex_str = hex(total)[2:].upper().rjust(pad_to,"0")
        return "".join([hex_str[i:i + 2] for i in range(0, len(hex_str), 2)][::-1])

    def get_hex(self, line):
        # strip the header and commented end
        return line.split(":")[1].split("//")[0].replace(" ","")

    def get_line(self, line):
        # Strip the header and commented end - no space replacing though
        line = line.split("//")[0]
        if ":" in line:
            return line.split(":")[1]
        return line

    def get_hex_bytes(self, line):
        return binascii.unhexlify(line)

    def get_str_bytes(self, value):
        if 2/3!=0 and isinstance(value,str):
            value = value.encode()
        return value

    def get_table_with_id(self, table_id):
        table_id = self.get_str_bytes(table_id)
        return next((v for k,v in self.acpi_tables.items() if table_id == v.get("id")),None)

    def get_table_with_signature(self, table_sig):
        table_sig = self.get_str_bytes(table_sig)
        return next((v for k,v in self.acpi_tables.items() if table_sig == v.get("signature")),None)
    
    def get_table(self, table_id_or_sig):
        table_id_or_sig = self.get_str_bytes(table_id_or_sig)
        return next((v for k,v in self.acpi_tables.items() if table_id_or_sig in (v.get("signature"),v.get("id"))),None)

    def get_dsdt(self):
        return self.get_table_with_signature("DSDT")

    def get_dsdt_or_only(self):
        dsdt = self.get_dsdt()
        if dsdt: return dsdt
        # Make sure we have only one table
        if len(self.acpi_tables) != 1:
            return None
        return list(self.acpi_tables.values())[0]

    def find_previous_hex(self, index=0, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return ("",-1,-1)
        # Returns the index of the previous set of hex digits before the passed index
        start_index = -1
        end_index   = -1
        old_hex = True
        for i,line in enumerate(table.get("lines","")[index::-1]):
            if old_hex:
                if not self.is_hex(line):
                    # Broke out of the old hex
                    old_hex = False
                continue
            # Not old_hex territory - check if we got new hex
            if self.is_hex(line): # Checks for a :, but not in comments
                end_index = index-i
                hex_text,start_index = self.get_hex_ending_at(end_index,table=table)
                return (hex_text, start_index, end_index)
        return ("",start_index,end_index)
    
    def find_next_hex(self, index=0, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return ("",-1,-1)
        # Returns the index of the next set of hex digits after the passed index
        start_index = -1
        end_index   = -1
        old_hex = True
        for i,line in enumerate(table.get("lines","")[index:]):
            if old_hex:
                if not self.is_hex(line):
                    # Broke out of the old hex
                    old_hex = False
                continue
            # Not old_hex territory - check if we got new hex
            if self.is_hex(line): # Checks for a :, but not in comments
                start_index = i+index
                hex_text,end_index = self.get_hex_starting_at(start_index,table=table)
                return (hex_text, start_index, end_index)
        return ("",start_index,end_index)

    def is_hex(self, line):
        return self.hex_match.match(line) is not None

    def get_hex_starting_at(self, start_index, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return ("",-1)
        # Returns a tuple of the hex, and the ending index
        hex_text = ""
        index = -1
        for i,x in enumerate(table.get("lines","")[start_index:]):
            if not self.is_hex(x):
                break
            hex_text += self.get_hex(x)
            index = i+start_index
        return (hex_text, index)

    def get_hex_ending_at(self, start_index, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return ("",-1)
        # Returns a tuple of the hex, and the ending index
        hex_text = ""
        index = -1
        for i,x in enumerate(table.get("lines","")[start_index::-1]):
            if not self.is_hex(x):
                break
            hex_text = self.get_hex(x)+hex_text
            index = start_index-i
        return (hex_text, index)

    def get_shortest_unique_pad(self, current_hex, index, instance=0, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return None
        try:    left_pad  = self.get_unique_pad(current_hex, index, False, instance, table=table)
        except: left_pad  = None
        try:    right_pad = self.get_unique_pad(current_hex, index, True, instance, table=table)
        except: right_pad = None
        try:    mid_pad   = self.get_unique_pad(current_hex, index, None, instance, table=table)
        except: mid_pad   = None
        if left_pad == right_pad == mid_pad is None: raise Exception("No unique pad found!")
        # We got at least one unique pad
        min_pad = None
        for x in (left_pad,right_pad,mid_pad):
            if x is None: continue # Skip
            if min_pad is None or len(x[0]+x[1]) < len(min_pad[0]+min_pad[1]):
                min_pad = x
        return min_pad

    def get_unique_pad(self, current_hex, index, direction=None, instance=0, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: raise Exception("No valid table passed!")
        # Returns any pad needed to make the passed patch unique
        # direction can be True = forward, False = backward, None = both
        start_index = index
        line,last_index = self.get_hex_starting_at(index,table=table)
        if last_index == -1:
            raise Exception("Could not find hex starting at index {}!".format(index))
        first_line = line
        # Assume at least 1 byte of our current_hex exists at index, so we need to at
        # least load in len(current_hex)-2 worth of data if we haven't found it.
        while True:
            if current_hex in line or len(line) >= len(first_line)+len(current_hex):
                break # Assume we've hit our cap
            new_line,_index,last_index = self.find_next_hex(last_index, table=table)
            if last_index == -1:
                raise Exception("Hit end of file before passed hex was located!")
            # Append the new info
            line += new_line
        if not current_hex in line:
            raise Exception("{} not found in table at index {}-{}!".format(current_hex,start_index,last_index))
        padl = padr = ""
        parts = line.split(current_hex)
        if instance >= len(parts)-1:
            raise Exception("Instance out of range!")
        linel = current_hex.join(parts[0:instance+1])
        liner = current_hex.join(parts[instance+1:])
        last_check = True # Default to forward
        while True:
            # Check if our hex string is unique
            check_bytes = self.get_hex_bytes(padl+current_hex+padr)
            if table["raw"].count(check_bytes) == 1: # Got it!
                break
            if direction == True or (direction is None and len(padr)<=len(padl)):
                # Let's check a forward byte
                if not len(liner):
                    # Need to grab more
                    liner, _index, last_index = self.find_next_hex(last_index, table=table)
                    if last_index == -1: raise Exception("Hit end of file before unique hex was found!")
                padr  = padr+liner[0:2]
                liner = liner[2:]
                continue
            if direction == False or (direction is None and len(padl)<=len(padr)):
                # Let's check a backward byte
                if not len(linel):
                    # Need to grab more
                    linel, start_index, _index = self.find_previous_hex(start_index, table=table)
                    if _index == -1: raise Exception("Hit end of file before unique hex was found!")
                padl  = linel[-2:]+padl
                linel = linel[:-2]
                continue
            break
        return (padl,padr)
    
    def get_devices(self,search=None,types=("Device (","Scope ("),strip_comments=False,table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return []
        # Returns a list of tuples organized as (Device/Scope,d_s_index,matched_index)
        if search is None:
            return []
        last_device = None
        device_index = 0
        devices = []
        for index,line in enumerate(table.get("lines","")):
            if self.is_hex(line):
                continue
            line = self.get_line(line) if strip_comments else line
            if any ((x for x in types if x in line)):
                # Got a last_device match
                last_device = line
                device_index = index
            if search in line:
                # Got a search hit - add it
                devices.append((last_device,device_index,index))
        return devices

    def get_scope(self,starting_index=0,add_hex=False,strip_comments=False,table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return []
        # Walks the scope starting at starting_index, and returns when
        # we've exited
        brackets = None
        scope = []
        for line in table.get("lines","")[starting_index:]:
            if self.is_hex(line):
                if add_hex:
                    scope.append(line)
                continue
            line = self.get_line(line) if strip_comments else line
            scope.append(line)
            if brackets is None:
                if line.count("{"):
                    brackets = line.count("{")
                continue
            brackets = brackets + line.count("{") - line.count("}")
            if brackets <= 0:
                # We've exited the scope
                return scope
        return scope

    def get_scopes(self, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return []
        scopes = []
        for index,line in enumerate(table.get("lines","")):
            if self.is_hex(line): continue
            if any(x in line for x in ("Processor (","Scope (","Device (","Method (","Name (")):
                scopes.append((line,index))
        return scopes

    def get_paths(self, table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return []
        # Set up lists for complete paths, as well
        # as our current path reference
        path_list  = []
        _path      = []
        brackets = 0
        for i,line in enumerate(table.get("lines",[])):
            if self.is_hex(line):
                # Skip hex
                continue
            line = self.get_line(line)
            brackets += line.count("{")-line.count("}")
            while len(_path):
                # Remove any path entries that are nested
                # equal to or further than our current set
                if _path[-1][-1] >= brackets:
                    del _path[-1]
                else:
                    break
            type_match = self.type_match.match(line)
            if type_match:
                # Add our path entry and save the full path
                # to the path list as needed
                _path.append((type_match.group("name"),brackets))
                if type_match.group("type") == "Scope":
                    continue
                # Ensure that we only consider non-Scope paths that aren't
                # already fully qualified with a \ prefix
                path = []
                for p in _path[::-1]:
                    path.append(p[0])
                    p_check = p[0].split(".")[0].rstrip("_")
                    if p_check.startswith("\\") or p_check in ("_SB","_PR"):
                        # Fully qualified - bail here
                        break
                path = ".".join(path[::-1]).split(".")
                # Properly qualify the path
                if len(path) and path[0] == "\\": path.pop(0)
                if any("^" in x for x in path): # Accommodate caret notation
                    new_path = []
                    for x in path:
                        if x.count("^"):
                            # Remove the last Y paths to account for going up a level
                            del new_path[-1*x.count("^"):]
                        new_path.append(x.replace("^","")) # Add the original, removing any ^ chars
                    path = new_path
                if not path:
                    continue
                # Ensure we strip trailing underscores for consistency
                padded_path = [("\\" if j==0 else"")+x.lstrip("\\").rstrip("_") for j,x in enumerate(path)]
                path_str = ".".join(padded_path)
                path_list.append((path_str,i,type_match.group("type")))
        return sorted(path_list)

    def get_path_of_type(self, obj_type="Device", obj="HPET", table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return []
        paths = []
        # Remove trailing underscores and normalize case for all path
        # elements passed
        obj = ".".join([x.rstrip("_").upper() for x in obj.split(".")])
        obj_type = obj_type.lower() if obj_type else obj_type
        for path in table.get("paths",[]):
            path_check = ".".join([x.rstrip("_").upper() for x in path[0].split(".")])
            if (obj_type and obj_type != path[2].lower()) or not path_check.endswith(obj):
                # Type or object mismatch - skip
                continue
            paths.append(path)
        return sorted(paths)

    def get_device_paths(self, obj="HPET",table=None):
        return self.get_path_of_type(obj_type="Device",obj=obj,table=table)

    def get_method_paths(self, obj="_STA",table=None):
        return self.get_path_of_type(obj_type="Method",obj=obj,table=table)

    def get_name_paths(self, obj="CPU0",table=None):
        return self.get_path_of_type(obj_type="Name",obj=obj,table=table)

    def get_processor_paths(self, obj_type="Processor",table=None):
        return self.get_path_of_type(obj_type=obj_type,obj="",table=table)

    def get_device_paths_with_id(self,_id="PNP0A03",id_types=("_HID","_CID"),table=None):
        if not table: table = self.get_dsdt_or_only()
        if not table: return []
        if not isinstance(id_types,(list,tuple)): return []
        # Strip non-strings from the list
        id_types = [x.upper() for x in id_types if isinstance(x,str)]
        if not id_types: return []
        _id = _id.upper() # Ensure case
        devs = []
        for p in table.get("paths",[]):
            try:
                for type_check in id_types:
                    if p[0].endswith(type_check) and _id in table.get("lines")[p[1]]:
                        # Save the path, strip the suffix and trailing periods
                        devs.append(p[0][:-len(type_check)].rstrip("."))
                        # Leave this loop to avoid adding the same device
                        # multiple times
                        break
            except Exception as e:
                print(e)
                continue
        devices = []
        # Walk the paths again - and save any devices
        # that match our prior list
        for p in table.get("paths",[]):
            if p[0] in devs and p[-1] == "Device":
                devices.append(p)
        return devices

    def get_device_paths_with_cid(self,cid="PNP0A03",table=None):
        return self.get_device_paths_with_id(_id=cid,id_types=("_CID",),table=table)

    def get_device_paths_with_hid(self,hid="ACPI000E",table=None):
        return self.get_device_paths_with_id(_id=hid,id_types=("_HID",),table=table)
