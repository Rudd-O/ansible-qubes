# Based on local.py (c) 2012, Anon <anon@anon.anon>
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.
__metaclass__ = type

DOCUMENTATION = """
    author:
        - Manuel Amador (Rudd-O)

    connection: qubes

    short_description: Execute tasks in Qubes VMs.

    description:
        - Use the qssh command to run commands in Qubes OS VMs.

    version_added: "2.0"

    requirements:
      - qssh (Python script from ansible-qubes)

    options:
      management_proxy:
        description:
          - Management proxy.  A machine accessible via SSH that can run qrexec.
        default: ''
        vars:
          - name: management_proxy
        env:
          - name: MANAGEMENT_PROXY
"""

import distutils.spawn
import traceback
import os
import shlex
import subprocess
import pipes
from ansible import errors
from ansible import utils
from ansible.utils.display import Display
display = Display()
from ansible.plugins.connection import ConnectionBase
from ansible.utils.vars import combine_vars
from ansible.module_utils._text import to_bytes
from ansible import constants as C


BUFSIZE = 1024*1024
CONNECTION_TRANSPORT = "qubes"
CONNECTION_OPTIONS = {
    'management_proxy': '--management-proxy',
}


class QubesRPCError(subprocess.CalledProcessError):

    def __init__(self, returncode, cmd, output=None):
        subprocess.CalledProcessError.__init__(self, returncode, cmd, output)

    def __str__(self):
        r = subprocess.CalledProcessError.__str__(self)
        r = r + " while producing output %r" % self.output
        return r


class Connection(ConnectionBase):
    ''' Qubes based connections '''

    transport = CONNECTION_TRANSPORT
    connection_options = CONNECTION_OPTIONS
    documentation = DOCUMENTATION
    has_pipelining = False
    become_from_methods = frozenset(["sudo"])
    transport_cmd = None

    def __init__(self, play_context, new_stdin, *args, **kwargs):
        super(Connection, self).__init__(play_context, new_stdin, *args, **kwargs)

        self.transport_cmd = distutils.spawn.find_executable('qrun')
        if not self.transport_cmd:
            self.transport_cmd = os.path.join(
                os.path.dirname(__file__),
                os.path.pardir,
                os.path.pardir,
                "bin",
                "qrun",
            )
            if not os.path.exists(self.transport_cmd):
              self.transport_cmd = None
        if not self.transport_cmd:
            raise errors.AnsibleError("qrun command not found in PATH")

    def _connect(self):
        '''Connect to the VM; nothing to do here '''
        super(Connection, self)._connect()
        if not self._connected:
            display.vvv("THIS IS A QUBES VM", host=self._play_context.remote_addr)
            self._connected = True

    def _produce_command(self, cmd):
        addr = self._play_context.remote_addr
        proxy = self.get_option("management_proxy")
        if proxy:
            proxy = ["--proxy=%s" % proxy] if proxy else []
            addr = addr.split(".")[0]
        else:
            proxy = []
        if isinstance(cmd, basestring):
            cmd = shlex.split(cmd)
        cmd = [self.transport_cmd] + proxy + [addr] + cmd
        display.vvv("COMMAND %s" % (cmd,), host=self._play_context.remote_addr)
        return cmd

    def exec_command(self, cmd, in_data=None, sudoable=False):
        '''Run a command on the VM.'''
        super(Connection, self).exec_command(cmd, in_data=in_data, sudoable=sudoable)
        cmd = self._produce_command(cmd)
        cmd = [to_bytes(i, errors='surrogate_or_strict') for i in cmd]
        p = subprocess.Popen(cmd, shell=False, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        stdout, stderr = p.communicate(in_data)
        return (p.returncode, stdout, stderr)

    def put_file(self, in_path, out_path):
        ''' transfer a file from local to VM '''
        super(Connection, self).put_file(in_path, out_path)
        display.vvv("PUT %s TO %s" % (in_path, out_path), host=self._play_context.remote_addr)

        out_path = self._prefix_login_path(out_path)
        try:
            with open(in_path, 'rb') as in_file:
                try:
                    cmd = self._produce_command(['dd','of=%s' % out_path, 'bs=%s' % BUFSIZE])
                    p = subprocess.Popen(cmd, shell=False, stdin=in_file,
                                         stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE)
                except OSError:
                    raise errors.AnsibleError("chroot connection requires dd command in the chroot")
                try:
                    stdout, stderr = p.communicate()
                except:
                    traceback.print_exc()
                    raise errors.AnsibleError("failed to transfer file %s to %s" % (in_path, out_path))
                if p.returncode != 0:
                    raise errors.AnsibleError("failed to transfer file %s to %s:\n%s\n%s" % (in_path, out_path, stdout, stderr))
        except IOError:
            raise errors.AnsibleError("file or module does not exist at: %s" % in_path)

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
        display.vvv("FETCH %s TO %s" % (in_path, out_path), host=self._play_context.remote_addr)

        in_path = self._prefix_login_path(in_path)
        try:
            cmd = self._produce_command(['dd', 'if=%s' % in_path, 'bs=%s' % BUFSIZE])
            p = subprocess.Popen(cmd, shell=False, stdin=open(os.devnull),
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        except OSError:
            raise errors.AnsibleError("Qubes connection requires dd command in the chroot")

        with open(out_path, 'wb+') as out_file:
            try:
                chunk = p.stdout.read(BUFSIZE)
                while chunk:
                    out_file.write(chunk)
                    chunk = p.stdout.read(BUFSIZE)
            except:
                traceback.print_exc()
                raise errors.AnsibleError("failed to transfer file %s to %s" % (in_path, out_path))
            stdout, stderr = p.communicate()
            if p.returncode != 0:
                raise errors.AnsibleError("failed to transfer file %s to %s:\n%s\n%s" % (in_path, out_path, stdout, stderr))

    def close(self):
        ''' terminate the connection; nothing to do here '''
        super(Connection, self).close()
        self._connected = False
