import os, sys, json
sys.path.append(os.path.abspath(os.path.dirname(os.path.realpath(__file__))))
import downloader, utils, run

class Updater:
    def __init__(self, **kwargs):
        # Initialize modules
        self.dl          = downloader.Downloader()
        self.u           = utils.Utils()
        self.r           = run.Run()
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
        # Set defaults
        self.update_url  = kwargs.get("url", None)
        self.update_type = kwargs.get("update_type", "file") # file or json
        self.update_key  = kwargs.get("update_key", 2)       # the json key, or line of the target file
        self.prompt      = kwargs.get("prompt", False)       # do we prompt the user for update notifications?
        self.prompt_key  = kwargs.get("prompt_key", None)    # the json key for an update description
        self.file        = kwargs.get("file", None)          # our current file for local version access
        self.update_mode = kwargs.get("mode", "clone")       # clone/file; clone a repo, or just curl a file
        self.chmod       = kwargs.get("chmod", [])            # list of files to chmod
        self.restart     = kwargs.get("restart", True)       # restart on update?
        self.start_file  = kwargs.get("restart_file", None)  # path to the file to restart

    def _get_file_version(self, local = False):
        return
    
    def _get_json_version(self, local = False):
        return

    def check_update(self):
        # Returns whether or not 
        if not self.update_url:
            return None