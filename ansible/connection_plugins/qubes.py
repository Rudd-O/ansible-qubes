# Based on local.py (c) 2012, Anon <anon@anon.anon>
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

import distutils.spawn
import traceback
import os
import shutil
import subprocess
import pipes
from ansible import errors
from ansible import utils
from ansible.callbacks import vvv
from ansible.inventory import Inventory

class Connection(object):
    ''' Qubes based connections '''

    def __init__(self, runner, host, port, *args, **kwargs):
        self.runner = runner
        host_vars = self.runner.inventory.get_host(host).get_variables()
        self.proxy = host_vars.get("management_proxy")
        self.has_pipelining = False

        self.chroot_cmd = distutils.spawn.find_executable('qrun')
        if not self.chroot_cmd:
            self.chroot_cmd = os.path.join(
                os.path.dirname(__file__),
                os.path.pardir,
                os.path.pardir,
                "bin",
                "qrun",
            )
            if not os.path.exists(self.chroot_cmd):
              self.chroot_cmd = None
        if not self.chroot_cmd:
            raise errors.AnsibleError("qrun command not found in PATH")

        self.host = host
        if self.proxy:
            self.chroot = ".".join(self.host.split(".")[:-1])
        else:
            self.chroot = None
        # port is unused, since this is local
        self.port = port

    def connect(self, port=None):
        ''' connect to the chroot; nothing to do here '''

        vvv("THIS IS A QUBES VM", host=self.chroot)

        return self

    def produce_command(self, cmd, executable='/bin/sh'):
        proxy = ["--proxy=%s" % self.proxy] if self.proxy else []
        chroot = "%s" % self.chroot if self.chroot else self.host
        if executable:
            local_cmd = [self.chroot_cmd] + proxy + [chroot, cmd]
            vvv("EXEC (with executable %s) %s" % (executable, local_cmd), host=self.chroot)
        else:
            if proxy:
              local_cmd = '%s %s "%s" %s' % (self.chroot_cmd, proxy, chroot, cmd)
            else:
              local_cmd = '%s "%s" %s' % (self.chroot_cmd, chroot, cmd)
            vvv("EXEC (without executable) %s" % (local_cmd), host=self.chroot)
        return local_cmd

    def exec_command(self, cmd, tmp_path, become_user=None, sudoable=False, executable='/bin/sh', in_data=None):
        ''' run a command on the chroot '''

        # We enter qrun as root so sudo stuff can be ignored
        local_cmd = self.produce_command(cmd, executable)

        p = subprocess.Popen(local_cmd, shell=isinstance(local_cmd, basestring),
                             cwd=self.runner.basedir,
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if in_data is None:
            stdout, stderr = p.communicate()
        else:
            stdout, stderr = p.communicate(in_data)
        return (p.returncode, '', stdout, stderr)

    def put_file(self, in_path, out_path):
        ''' transfer a file from local to VM '''

        if not out_path.startswith(os.path.sep):
            out_path = os.path.join(os.path.sep, out_path)
        normpath = os.path.normpath(out_path)
        out_path = os.path.join("/", normpath[1:])

        vvv("PUT %s TO %s" % (in_path, out_path), host=self.chroot)
        if not os.path.exists(in_path):
            raise errors.AnsibleFileNotFound("file or module does not exist: %s" % in_path)
        cmd = self.produce_command("cat > %s" % pipes.quote(out_path))
        try:
          p = subprocess.Popen(
            cmd,
            stdin = subprocess.PIPE
          )
          p.communicate(file(in_path).read())
          retval = p.wait()
          if retval != 0:
            raise subprocess.CalledProcessError(retval, cmd)
        except subprocess.CalledProcessError:
            traceback.print_exc()
            raise errors.AnsibleError("failed to transfer file to %s" % out_path)

    def fetch_file(self, in_path, out_path):
        ''' fetch a file from VM to local '''

        if not in_path.startswith(os.path.sep):
            in_path = os.path.join(os.path.sep, in_path)
        normpath = os.path.normpath(in_path)
        in_path = os.path.join("/", normpath[1:])

        vvv("FETCH %s TO %s" % (in_path, out_path), host=self.chroot)
        f = pipes.quote(in_path)
        cmd = self.produce_command("test -f %s && cat %s || exit 7" % (f,f))
        try:
          p = subprocess.Popen(
            cmd,
            stdout = subprocess.PIPE
          )
          out, err = p.communicate("")
          retval = p.wait()
          if retval == 7:
            raise errors.AnsibleFileNotFound("file or module does not exist: %s" % in_path)
          elif retval != 0:
            raise subprocess.CalledProcessError(retval, cmd)
          file(out_path, "wb").write(out)
        except subprocess.CalledProcessError:
            traceback.print_exc()
            raise errors.AnsibleError("failed to transfer file to %s" % out_path)
        except IOError:
            traceback.print_exc()
            raise errors.AnsibleError("failed to transfer file to %s" % out_path)

    def close(self):
        ''' terminate the connection; nothing to do here '''
        pass
