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
from ansible.utils.display import Display
display = Display()
from ansible.plugins.connection import ConnectionBase
from ansible.inventory import Inventory
from ansible.utils.vars import combine_vars
from ansible.utils.unicode import to_bytes, to_unicode, to_str
from ansible import constants as C


BUFSIZE = 1024*1024


class QubesRPCError(subprocess.CalledProcessError):

    def __init__(self, returncode, cmd, output=None):
        subprocess.CalledProcessError.__init__(self, returncode, cmd, output)

    def __str__(self):
        r = subprocess.CalledProcessError.__str__(self)
        r = r + " while producing output %r" % self.output
        return r


class Connection(ConnectionBase):
    ''' Qubes based connections '''

    transport = "qubes"
    has_pipelining = False
    become_from_methods = frozenset(["sudo"])
    _management_proxy = None

    def set_host_overrides(self, host):
        host_vars = combine_vars(host.get_group_vars(), host.get_vars())
        _management_proxy = host_vars.get("_management_proxy", None)

    def __init__(self, play_context, new_stdin, *args, **kwargs):
        super(Connection, self).__init__(play_context, new_stdin, *args, **kwargs)
        self.chroot = self._play_context.remote_addr

        self.qrun = distutils.spawn.find_executable('qrun')
        if not self.qrun:
            self.qrun = os.path.join(
                os.path.dirname(__file__),
                os.path.pardir,
                os.path.pardir,
                "bin",
                "qrun",
            )
            if not os.path.exists(self.qrun):
              self.qrun = None
        if not self.qrun:
            raise errors.AnsibleError("qrun command not found in PATH")

        if self._management_proxy:
            assert 0, "still do not know how to deal with management proxy"

    def _connect(self):
        """Connect to the host we've been initialized with"""

        # Check if PE is supported
        if self._play_context.become:
            self._become_method_supported()

    def connect(self):
        ''' connect to the chroot; nothing to do here '''

        super(Connection, self)._connect()
        display.vvv("THIS IS A QUBES VM", host=self.chroot)

        return self

    def _produce_command(self, cmd):
        # FIXME
        # proxy = ["--proxy=%s" % self._management_proxy] if self._management_proxy else []
        chroot = self.chroot
        if isinstance(cmd, basestring):
            assert 0, "cannot deal with basestrings like " + cmd
        #if proxy:
        #  local_cmd = [self.qrun] + proxy + [chroot] + cmd
        #else:
        local_cmd = [self.qrun, self.chroot] + cmd
        local_cmd = map(to_bytes, local_cmd)
        return local_cmd

    def _buffered_exec_command(self, cmd, stdin=subprocess.PIPE):
        ''' run a command on the chroot.  This is only needed for implementing
        put_file() get_file() so that we don't have to read the whole file
        into memory.

        compared to exec_command() it looses some niceties like being able to
        return the process's exit code immediately.
        '''
        local_cmd = self._produce_command(["/bin/sh", "-c", cmd])
        display.vvv("EXEC %s" % (local_cmd), host=self.chroot)
        return subprocess.Popen(local_cmd, shell=False, stdin=stdin,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)

    def exec_command(self, cmd, in_data=None, sudoable=False):
        ''' run a command on the chroot '''
        super(Connection, self).exec_command(cmd, in_data=in_data, sudoable=sudoable)
        p = self._buffered_exec_command(cmd)
        stdout, stderr = p.communicate(in_data)
        return (p.returncode, stdout, stderr)

    def put_file(self, in_path, out_path):
        ''' transfer a file from local to VM '''
        super(Connection, self).put_file(in_path, out_path)
        display.vvv("PUT %s TO %s" % (in_path, out_path), host=self.chroot)

        out_path = pipes.quote(self._prefix_login_path(out_path))
        try:
            with open(in_path, 'rb') as in_file:
                try:
                    p = self._buffered_exec_command('dd of=%s bs=%s' % (out_path, BUFSIZE), stdin=in_file)
                except OSError:
                    raise AnsibleError("chroot connection requires dd command in the chroot")
                try:
                    stdout, stderr = p.communicate()
                except:
                    traceback.print_exc()
                    raise AnsibleError("failed to transfer file %s to %s" % (in_path, out_path))
                if p.returncode != 0:
                    raise AnsibleError("failed to transfer file %s to %s:\n%s\n%s" % (in_path, out_path, stdout, stderr))
        except IOError:
            raise AnsibleError("file or module does not exist at: %s" % in_path)

    def _prefix_login_path(self, remote_path):
        ''' Make sure that we put files into a standard path

            If a path is relative, then we need to choose where to put it.
            ssh chooses $HOME but we aren't guaranteed that a home dir will
            exist in any given chroot.  So for now we're choosing "/" instead.
            This also happens to be the former default.

            Can revisit using $HOME instead if it's a problem
        '''
        if not remote_path.startswith(os.path.sep):
            remote_path = os.path.join(os.path.sep, remote_path)
        return os.path.normpath(remote_path)

    def fetch_file(self, in_path, out_path):
        ''' fetch a file from VM to local '''
        super(Connection, self).fetch_file(in_path, out_path)
        display.vvv("FETCH %s TO %s" % (in_path, out_path), host=self.chroot)

        in_path = pipes.quote(self._prefix_login_path(in_path))

        try:
            p = self._buffered_exec_command('dd if=%s bs=%s' % (in_path, BUFSIZE))
        except OSError:
            raise AnsibleError("Qubes connection requires dd command in the chroot")

        with open(out_path, 'wb+') as out_file:
            try:
                chunk = p.stdout.read(BUFSIZE)
                while chunk:
                    out_file.write(chunk)
                    chunk = p.stdout.read(BUFSIZE)
            except:
                traceback.print_exc()
                raise AnsibleError("failed to transfer file %s to %s" % (in_path, out_path))
            stdout, stderr = p.communicate()
            if p.returncode != 0:
                raise AnsibleError("failed to transfer file %s to %s:\n%s\n%s" % (in_path, out_path, stdout, stderr))

    def close(self):
        ''' terminate the connection; nothing to do here '''
        pass
