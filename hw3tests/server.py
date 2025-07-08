from asyncio.subprocess import PIPE
from multiprocessing.dummy import current_process
from posixpath import basename
from subprocess import Popen, PIPE
import sys
import os
import pytest


class Server:
    def __init__(self, path, port, threads, queue_size):
        self.path = str(path)
        self.port = str(port)
        self.threads = str(threads)
        self.queue_size = str(queue_size)

    def __enter__(self):
        self.process = Popen([self.path, self.port, self.threads, self.queue_size], stdout=PIPE, stderr=PIPE, cwd="..", bufsize=0, encoding=sys.getdefaultencoding())
        return self.process

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.process.terminate()

@pytest.fixture
def server_port(request):
    return 8000 + (abs(hash(basename(request.node.fspath) + request.node.name)) % 20000)
