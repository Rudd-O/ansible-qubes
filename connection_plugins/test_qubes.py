import sys, os ; sys.path.append(os.path.dirname(__file__))

import StringIO
import qubes
import unittest
import tempfile


cases = [
    (['true'], '', 'Y\n0\n0\n0\n'),
    (['false'], '', 'Y\n1\n0\n0\n'),
    (['sh', '-c', 'echo yes'], '', 'Y\n0\n4\nyes\n0\n'),
    (['sh', '-c', 'echo yes >&2'], '', 'Y\n0\n0\n4\nyes\n'),
]
cases_with_harness = [
    (['true'], '', 0, '', ''),
    (['false'], '', 1, '', ''),
    (['sh', '-c', 'echo yes'], '', 0, 'yes\n', ''),
    (['sh', '-c', 'echo yes >&2'], '', 0, '', 'yes\n'),
]


class MockPlayContext(object):
    shell = 'sh'
    become = False
    become_method = 'sudo'
    remote_addr = '127.0.0.7'


def local_connection():
    c = qubes.Connection(
        MockPlayContext(), None,
        transport_cmd=['sh', '-c', '"$@"']
    )
    c._options = {"management_proxy": None}
    return c


class TestBasicThings(unittest.TestCase):

    def test_popen(self):
        for cmd, in_, out in cases:
            outf = StringIO.StringIO()
            qubes.popen(cmd, in_, outf=outf)
            self.assertMultiLineEqual(
                outf.getvalue(),
                out
            )

    def test_exec_command_with_harness(self):
        for cmd, in_, ret, out, err in cases_with_harness:
            c = local_connection()
            retcode, stdout, stderr = c.exec_command(cmd)
            self.assertEqual(ret, retcode)
            self.assertMultiLineEqual(out, stdout)
            self.assertMultiLineEqual(err, stderr)
            c.close()
            self.assertEqual(c._transport, None)

    def test_fetch_file_with_harness(self):
        in_text = "abcd"
        with tempfile.NamedTemporaryFile() as x:
            x.write(in_text)
            x.flush()
            with tempfile.NamedTemporaryFile() as y:
                c = local_connection()
                c.fetch_file(in_path=x.name, out_path=y.name)
                out_text = y.read()
        self.assertEqual(in_text, out_text)


    def test_put_file_with_harness(self):
        in_text = "abcd"
        with tempfile.NamedTemporaryFile() as x:
            x.write(in_text)
            x.flush()
            with tempfile.NamedTemporaryFile() as y:
                c = local_connection()
                c.put_file(in_path=x.name, out_path=y.name)
                out_text = y.read()
        self.assertEqual(in_text, out_text)
