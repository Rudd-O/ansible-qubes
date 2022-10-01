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
        - Use the qrun command to run commands in Qubes OS VMs.

    version_added: "2.0"

    requirements:
      - qrun (Python script from ansible-qubes)

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
import inspect
import traceback
import textwrap
import os
import shlex
import sys
import subprocess
import pipes
from ansible import errors
from ansible import utils
from ansible.plugins.loader import connection_loader
from ansible.plugins.connection import ConnectionBase
from ansible.utils.vars import combine_vars
from ansible.module_utils._text import to_bytes
from ansible.utils.path import unfrackpath
from ansible import constants as C
try:
    from __main__ import display
except ImportError:
    from ansible.utils.display import Display
    display = Display()
class x(object):
    def vvvv(self, text, host=None):
        with open(os.path.expanduser("~/ansible-qubes.log"), "a") as f:
            print(text, host, file=f)
    def vvv(self, text, host=None):
        with open(os.path.expanduser("~/ansible-qubes.log"), "a") as f:
            print(text, host, file=f)
display = x()


BUFSIZE = 64*1024  # any bigger and it causes issues because we don't read multiple chunks until completion
CONNECTION_TRANSPORT = "qubes"
CONNECTION_OPTIONS = {
    'management_proxy': '--management-proxy',
}


def debug(text):
    return
    print(text, file=sys.stderr)


def encode_exception(exc, stream):
    debug("encoding exception")
    stream.write('{}\n'.format(len(exc.__class__.__name__)).encode('ascii'))
    stream.write('{}'.format(exc.__class__.__name__).encode('ascii'))
    for attr in "errno", "filename", "message", "strerror":
        stream.write('{}\n'.format(len('{}'.format(getattr(exc, attr)))).encode('ascii'))
        stream.write('{}'.format('{}'.format(getattr(exc, attr))).encode('ascii'))


def decode_exception(stream):
    debug("decoding exception")
    name_len = stream.readline(16)
    name_len = int(name_len)
    name = stream.read(name_len)
    keys = ["errno", "filename", "message", "strerror"]
    vals = dict((a, None) for a in keys)
    for k in keys:
        v_len = stream.readline(16)
        v_len = int(v_len)
        v = stream.read(v_len)
        if v == 'None':
            vals[k] = None
        else:
            try:
                vals[k] = int(v)
            except Exception:
                vals[k] = v
    if name == "IOError":
        e = IOError()
    elif name == "OSError":
        e = OSError()
    else:
        raise TypeError("Exception %s cannot be decoded" % name)
    for k, v in vals.items():
        setattr(e, k, v)
    return e


def popen(cmd, in_data, outf=sys.stdout):
    debug("popening on remote %s" % type(in_data))
    try:
        p = subprocess.Popen(
            cmd, shell=False, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        out, err = p.communicate(in_data)
        ret = p.wait()
        outf.write('{}\n'.format('Y').encode('ascii'))
    except (IOError, OSError) as e:
        outf.write('{}\n'.format('N').encode('ascii'))
        encode_exception(e, out)
    outf.write('{}\n'.format(ret).encode('ascii'))
    outf.write('{}\n'.format(len(out)).encode('ascii'))
    outf.write(out)
    outf.write('{}\n'.format(len(err)).encode('ascii'))
    outf.write(err)
    outf.flush()
    debug("finished popening")


def put(out_path):
    debug("dest writing %s" % out_path)
    try:
        f = open(out_path, "wb")
        sys.stdout.write(b'Y\n')
    except (IOError, OSError) as e:
        sys.stdout.write(b'N\n')
        encode_exception(e, sys.stdout)
        return
    while True:
        chunksize = int(sys.stdin.readline(16))
        if not chunksize:
            debug("looks like we have no more to read")
            break
        while chunksize:
            debug(type(chunksize))
            chunk = sys.stdin.read(chunksize)
            assert chunk
            debug("dest writing %s" % len(chunk))
            try:
                f.write(chunk)
            except (IOError, OSError) as e:
                sys.stdout.write(b'N\n')
                encode_exception(e, sys.stdout)
                f.close()
                return
            chunksize = chunksize - len(chunk)
            debug("remaining %s" % chunksize)
        sys.stdout.write(b'Y\n')
        sys.stdout.flush()
    try:
        f.flush()
    except (IOError, OSError) as e:
        sys.stdout.write(b'N\n')
        encode_exception(e, sys.stdout)
        return
    finally:
        debug("finished writing dest")
        f.close()


def fetch(in_path, bufsize):
    debug("Fetching from remote %s" % in_path)
    try:
        f = open(in_path, "rb")
    except (IOError, OSError) as e:
        sys.stdout.write(b'N\n')
        encode_exception(e, sys.stdout)
        return
    try:
        while True:
            try:
                data = f.read(bufsize)
            except (IOError, OSError) as e:
                sys.stdout.write(b'N\n')
                encode_exception(e, sys.stdout)
                f.close()
                return
            sys.stdout.write('{}\n'.format(len(data)).encode('ascii'))
            if len(data) == 0:
                sys.stdout.flush()
                break
            sys.stdout.write(data)
            sys.stdout.flush()
    finally:
        f.close()


if __name__ == '__main__':
    # FIXME: WRITE TESTS!
    import StringIO
    s = StringIO.StringIO()
    try:
        open("/doesnotexist")
    except Exception as e:
        encode_exception(e, s)
        s.seek(0)
        dec = decode_exception(s)


preamble = b'''
from __future__ import print_function
import sys, os, subprocess
sys.ps1 = ''
sys.ps2 = ''
sys.stdin = os.fdopen(sys.stdin.fileno(), 'rb', 0) if hasattr(sys.stdin, 'buffer') else sys.stdin
sys.stdout = sys.stdout.buffer if hasattr(sys.stdout, 'buffer') else sys.stdout
'''
payload = b'\n\n'.join(
    inspect.getsource(x).encode("utf-8")
    for x in (debug, encode_exception, popen, put, fetch)
) + \
b'''

_ = sys.stdout.write(b'OK\\n')
sys.stdout.flush()
'''


def _prefix_login_path(remote_path):
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
    become_from_methods = frozenset(["sudo"])
    has_pipelining = True
    transport_cmd = None
    _transport = None

    def set_options(self, task_keys=None, var_options=None, direct=None):
        super(Connection, self).set_options(task_keys=task_keys, var_options=var_options, direct=direct)
        # FIXME HORRIBLE WORKAROUND FIXME
        if task_keys and task_keys['delegate_to'] and self._options and 'management_proxy' in self._options:
            self._options['management_proxy'] = ''

    def __init__(self, play_context, new_stdin, *args, **kwargs):
        super(Connection, self).__init__(play_context, new_stdin, *args, **kwargs)
        display.vvv("INSTANTIATING %s %s" % (os.getppid(), id(self)), host=play_context.remote_addr)

        if 'transport_cmd' in kwargs:
            self.transport_cmd = kwargs['transport_cmd']
            return
        self.transport_cmd = distutils.spawn.find_executable('qrun')
        if not self.transport_cmd:
            self.transport_cmd = os.path.join(
                os.path.dirname(__file__),
                os.path.pardir,
                "bin",
                "qrun",
            )
            if not os.path.exists(self.transport_cmd):
              self.transport_cmd = None
        if not self.transport_cmd:
            raise errors.AnsibleError("qrun command not found in PATH")
        self.transport_cmd = [self.transport_cmd]
        display.vvvv("INSTANTIATED %s" % (os.getppid(),), host=play_context.remote_addr)

    def _connect(self):
        '''Connect to the VM.

        Unlike in earlier editions of this program, in this edition the
        program attempts to create a persistent Python session with the
        machine it's trying to connect to, speeding up greatly the exec-
        ution of Ansible modules against VMs, whether local or remote
        via SSH.  In other words, we have pipelining now.
        '''
        display.vvv("CONNECTING %s %s %s" % (os.getppid(), id(self), self.get_option("management_proxy")), host=self._play_context.remote_addr)
        super(Connection, self)._connect()
        if not self._connected:
            remote_cmd = [to_bytes(x, errors='surrogate_or_strict') for x in [
                # 'strace', '-s', '2048', '-o', '/tmp/log',
                 'python3', '-u', '-i', '-c', preamble
            ]]
            addr = self._play_context.remote_addr
            proxy = to_bytes(self.get_option("management_proxy")) if self.get_option("management_proxy") else ""
            if proxy:
                proxy = [b"--proxy=%s" % proxy] if proxy else []
                addr = addr.split(".")[0]
            else:
                proxy = []
            addr = to_bytes(addr)
            cmd = [to_bytes(x) for x in self.transport_cmd] + proxy + [addr] + remote_cmd
            display.vvvv("CONNECT %s" % (cmd,), host=self._play_context.remote_addr)
            self._transport = subprocess.Popen(
                cmd, shell=False, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE
            )
            try:
                self._transport.stdin.write(payload)
                self._transport.stdin.flush()
                ok = self._transport.stdout.readline(16)
                if not ok.startswith(b"OK\n"):
                    cmdquoted =  " ".join(pipes.quote(x.decode("utf-8")) for x in cmd)
                    raise errors.AnsibleError("the remote end of the Qubes connection was not ready: %s yielded %r" % (cmdquoted, ok))
            except Exception:
                self._abort_transport()
                raise
            display.vvvv("CONNECTED %s" % (cmd,), host=self._play_context.remote_addr)
            self._connected = True

    def _abort_transport(self):
        display.vvvv("ABORT", host=self._play_context.remote_addr)
        if self._transport:
            display.vvvv("ABORTING", host=self._play_context.remote_addr)
            try:
                self._transport.kill()
            except Exception:
                pass
            display.vvvv("ABORTED", host=self._play_context.remote_addr)
        self.close()

    def close(self):
        '''Terminate the connection.'''
        super(Connection, self).close()
        display.vvvv("CLOSE %s" % (os.getppid(),), host=self._play_context.remote_addr)
        if self._transport:
            display.vvvv("CLOSING %s" % (os.getppid(),), host=self._play_context.remote_addr)
            self._transport.stdin.close()
            self._transport.stdout.close()
            retcode = self._transport.wait()
            self._transport = None
            self._connected = False
            display.vvvv("CLOSED %s" % (os.getppid(),), host=self._play_context.remote_addr)

    def exec_command(self, cmd, in_data=None, sudoable=False):
        '''Run a command on the VM.'''
        super(Connection, self).exec_command(cmd, in_data=in_data, sudoable=sudoable)
        try: basestring
        except NameError: basestring = str
        if isinstance(cmd, basestring):
            cmd = shlex.split(cmd)
        display.vvvv("EXEC %s" % cmd, host=self._play_context.remote_addr)
        try:
            payload = ('popen(%r, %r)\n\n' % (cmd, in_data)).encode("utf-8")
            self._transport.stdin.write(payload)
            self._transport.stdin.flush()
            yesno = self._transport.stdout.readline(2)
            debug("Reading yesno")
        except Exception:
            self._abort_transport()
            raise
        if yesno == "Y\n" or yesno == b"Y\n":
            try:
                retcode = self._transport.stdout.readline(16)
                debug("Reading retcode")
                try:
                    retcode = int(retcode)
                except Exception:
                    raise errors.AnsibleError("return code from remote end is unexpected: %r" % retcode)
                if retcode > 65536 or retcode < -65535:
                    raise errors.AnsibleError("return code from remote end is outside the range: %r" % retcode)
                stdout_len = self._transport.stdout.readline(16)
                try:
                    stdout_len = int(stdout_len)
                except Exception:
                    raise errors.AnsibleError("stdout size from remote end is unexpected: %r" % stdout_len)
                if stdout_len > 1024*1024*1024 or stdout_len < 0:
                    raise errors.AnsibleError("stdout size from remote end is invalid: %r" % stdout_len)
                stdout = self._transport.stdout.read(stdout_len) if stdout_len != 0 else ''
                if len(stdout) != stdout_len:
                    raise errors.AnsibleError("stdout size from remote end does not match actual stdout length: %s != %s" % (stdout_len, len(stdout)))
                stderr_len = self._transport.stdout.readline(16)
                try:
                    stderr_len = int(stderr_len)
                except Exception:
                    raise errors.AnsibleError("stderr size from remote end is unexpected: %r" % stderr_len)
                if stdout_len > 1024*1024*1024 or stdout_len < 0:
                    raise errors.AnsibleError("stderr size from remote end is invalid: %s" % stderr_len)
                stderr = self._transport.stdout.read(stderr_len) if stderr_len != 0 else ''
                if len(stderr) != stderr_len:
                    raise errors.AnsibleError("stderr size from remote end does not match actual stderr length: %s != %s" % (stderr_len, len(stderr)))
                return (retcode, stdout, stderr)
            except Exception:
                self._abort_transport()
                raise
        elif yesno == "N\n" or yesno == b"N\n":
            exc = decode_exception(self._transport.stdin)
            raise exc
        else:
            self._abort_transport()
            raise errors.AnsibleError("pass/fail from remote end is unexpected: %r" % yesno)
        debug("finished popening on master")

    def put_file(self, in_path, out_path):
        '''Transfer a file from local to VM.'''
        super(Connection, self).put_file(in_path, out_path)
        display.vvvv("PUT %s to %s" % (in_path, out_path), host=self._play_context.remote_addr)
        out_path = _prefix_login_path(out_path)
        payload = 'put(%r)\n' % (out_path,)
        self._transport.stdin.write(payload.encode("utf-8"))
        self._transport.stdin.flush()
        yesno = self._transport.stdout.readline(2)
        if yesno == "Y\n" or yesno == b"Y\n":
            pass
        elif yesno == "N\n" or yesno == b"N\n":
            exc = decode_exception(self._transport.stdin)
            raise exc
        else:
            self._abort_transport()
            raise errors.AnsibleError("pass/fail from remote end is unexpected: %r" % yesno)
        with open(in_path, 'rb') as in_file:
            while True:
                chunk = in_file.read(BUFSIZE)
                debug("source writing %s bytes" % len(chunk))
                try:
                    self._transport.stdin.write(("%s\n" % len(chunk)).encode("utf-8"))
                    self._transport.stdin.flush()
                    if len(chunk) == 0:
                        break
                    self._transport.stdin.write(chunk)
                    self._transport.stdin.flush()
                except Exception:
                    self._abort_transport()
                    raise
                yesno = self._transport.stdout.readline(2)
                if yesno == "Y\n" or yesno == b"Y\n":
                    pass
                elif yesno == "N\n" or yesno == b"N\n":
                    exc = decode_exception(self._transport.stdin)
                    raise exc
                else:
                    self._abort_transport()
                    raise errors.AnsibleError("pass/fail from remote end is unexpected: %r" % yesno)
                debug("on this side it's all good")

        self._transport.stdin.write(("%s\n" % 0).encode("utf-8"))
        self._transport.stdin.flush()
        debug("finished writing source")

    def fetch_file(self, in_path, out_path):
        '''Fetch a file from VM to local.'''
        debug("fetching to local")
        super(Connection, self).fetch_file(in_path, out_path)
        display.vvvv("FETCH %s to %s" % (in_path, out_path), host=self._play_context.remote_addr)
        in_path = _prefix_login_path(in_path)
        with open(out_path, "wb") as out_file:
            try:
                payload = 'fetch(%r, %r)\n' % (in_path, BUFSIZE)
                self._transport.stdin.write(payload.encode("utf-8"))
                self._transport.stdin.flush()
                while True:
                    chunk_len = self._transport.stdout.readline(16)
                    try:
                        chunk_len = int(chunk_len)
                    except Exception:
                        if chunk_len == "N\n":
                            exc = decode_exception(self._transport.stdin)
                            raise exc
                        else:
                            self._abort_transport()
                            raise errors.AnsibleError("chunk size from remote end is unexpected: %r" % chunk_len)
                    if chunk_len > BUFSIZE or chunk_len < 0:
                        raise errors.AnsibleError("chunk size from remote end is invalid: %r" % chunk_len)
                    if chunk_len == 0:
                        break
                    chunk = self._transport.stdout.read(chunk_len)
                    if len(chunk) != chunk_len:
                        raise errors.AnsibleError("stderr size from remote end does not match actual stderr length: %s != %s" % (chunk_len, len(chunk)))
                    out_file.write(chunk)
            except Exception:
                self._abort_transport()
                raise
