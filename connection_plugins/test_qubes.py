import sys, os ; sys.path.append(os.path.dirname(__file__))

import contextlib
try:
    from StringIO import StringIO
    BytesIO = StringIO
except ImportError:
    from io import StringIO, BytesIO
import unittest
import tempfile

import qubes



if sys.version_info.major == 3:
    cases = [
        (['true'], '', b'Y\n0\n0\n0\n'),
        (['false'], '', b'Y\n1\n0\n0\n'),
        (['sh', '-c', 'echo yes'], '', b'Y\n0\n4\nyes\n0\n'),
        (['sh', '-c', 'echo yes >&2'], '', b'Y\n0\n0\n4\nyes\n'),
    ]
    cases_with_harness = [
        (['true'], '', 0, '', ''),
        (['false'], '', 1, '', ''),
        (['sh', '-c', 'echo yes'], '', 0, b'yes\n', ''),
        (['sh', '-c', 'echo yes >&2'], '', 0, '', b'yes\n'),
    ]
else:
    cases = []
    cases_with_harness = []


class MockPlayContext(object):
    shell = 'sh'
    executable = 'sh'
    become = False
    become_method = 'sudo'
    remote_addr = '127.0.0.7'


@contextlib.contextmanager
def local_connection():
    c = qubes.Connection(
        MockPlayContext(), None,
        transport_cmd=['sh', '-c', '"$@"']
    )
    c._options = {"management_proxy": None}
    try:
        yield c
    finally:
        c.close()


class TestBasicThings(unittest.TestCase):

    def test_popen(self):
        for cmd, in_, out in cases:
            outf = BytesIO()
            qubes.popen(cmd, in_, outf=outf)
            self.assertEqual(
                outf.getvalue(),
                out
            )

    def test_exec_command_with_harness(self):
        for cmd, in_, ret, out, err in cases_with_harness:
            with local_connection() as c:
                retcode, stdout, stderr = c.exec_command(cmd)
                self.assertEqual(ret, retcode)
                self.assertEqual(out, stdout)
                self.assertEqual(err, stderr)
            self.assertEqual(c._transport, None)

    def test_fetch_file_with_harness(self):
        if sys.version_info.major == 2:
            in_text = "abcd"
        else:
            in_text = b"abcd"
        with tempfile.NamedTemporaryFile() as x:
            x.write(in_text)
            x.flush()
            with tempfile.NamedTemporaryFile() as y:
                with local_connection() as c:
                    c.fetch_file(in_path=x.name, out_path=y.name)
                    y.seek(0)
                    out_text = y.read()
        self.assertEqual(in_text, out_text)

    def test_put_file_with_harness(self):
        if sys.version_info.major == 2:
            in_text = "abcd"
        else:
            in_text = b"abcd"
        with tempfile.NamedTemporaryFile() as x:
            x.write(in_text)
            x.flush()
            with tempfile.NamedTemporaryFile() as y:
                with local_connection() as c:
                    c.put_file(in_path=x.name, out_path=y.name)
                    y.seek(0)
                    out_text = y.read()
        self.assertEqual(in_text, out_text)
