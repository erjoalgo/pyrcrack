"""Pyrcrack-ng Executor helper."""

from contextlib import suppress
import abc
import asyncio
import functools
import itertools
import logging
import subprocess
import uuid

import docopt
import stringcase

from async_timeout import timeout

logging.basicConfig(level=logging.INFO)


async def search_in(stream, searcher, max_len=1024,
                    expect_timeout=30, start=''):
    """As python-pexpect does not work with coroutines, we do it here."""

    expected = None
    current = start

    with timeout(expect_timeout):
        while not expected:
            current += await stream.read(max_len)
            if isinstance(searcher, bytes):
                expected = searcher in current
            elif callable(searcher):
                expected = searcher(current)
                if asyncio.iscoroutine(expected):
                    expected = await(expected)
            else:
                raise Exception("Unsupported search method")


class Option:
    """Represents a single option (e.g, -e)."""

    def __init__(self, usage, word=None, value=None, logger=None):
        """Set option parameters."""
        self.usage = usage
        self.word = word
        self.logger = logger
        self.value = value
        keys = usage.keys()
        self.is_short = Option.short(word) in keys
        self.is_long = Option.long(word) in keys
        self.expects_args = bool(usage[self.formatted])
        self.logger.debug("Parsing option %s:%s", self.word, self.value)

    @property
    @functools.lru_cache()
    def formatted(self):
        """Format given option acording to definition."""
        result = (Option.short(self.word) if self.is_short
                  else Option.long(self.word))

        if self.usage.get(result):
            return result

        sword = self.word.replace('_', '-')
        return (Option.short(sword) if self.is_short
                else Option.long(sword))

    @staticmethod
    def long(word):
        """Extract long format option."""
        return "--{}".format(word)

    @staticmethod
    def short(word):
        """Extract short format option."""
        return "-{}".format(word)

    @property
    def parsed(self):
        """Returns key, value if value is required."""
        if self.expects_args:
            return (self.formatted, str(self.value))
        return (self.formatted,)

    def __repr__(self):
        return f"Option(<{self.parsed}>, {self.is_short}, {self.expects_args})"


class ExecutorHelper:
    """Abstract class interface to a shell command."""

    def __init__(self, loop=None):
        """Set docstring."""
        if not self.__doc__:
            self.__doc__ = self.helpstr
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG)
        self.loop = loop

    @abc.abstractproperty
    def sync(self):
        """Synchronous mode."""

    @abc.abstractproperty
    def command(self):
        """Specify command to execute."""

    @property
    @functools.lru_cache()
    def helpstr(self):
        """Extract help string for current command."""
        helpcmd = '{} 2>&1; echo'.format(self.command)
        return subprocess.check_output(helpcmd, shell=True).decode()

    @property
    @functools.lru_cache()
    def usage(self):
        """Extract usage from a specified command.

        This is useful if usage not defined in subclass, but it is recommended
        to define them there.
        """
        opt = docopt.parse_defaults(self.__doc__)
        return dict({a.short or a.long: bool(a.argcount) for a in opt})

    def run(self, *args, **kwargs):
        """Check command usage and execute it.

        If self.sync is defined, it will return process call output,
        and launch it blockingly.

        Otherwise it will call asyncio.create_subprocess_exec()
        """
        self.logger.debug("Parsing options: %s", kwargs)
        options = list(
            (Option(self.usage, a, v, self.logger) for a, v in kwargs.items()))
        self.logger.debug("Got options: %s", options)

        opts = [self.command] + list(args) + list(
            itertools.chain(*(o.parsed for o in options)))

        self.logger.debug("Running command: %s", opts)
        if self.sync:
            try:
                return subprocess.check_output(opts)
            except subprocess.CalledProcessError as excp:
                return excp.output
        kwargs = {'loop': self.loop} if self.loop else {}
        return asyncio.create_subprocess_exec(opts, **kwargs)


def stc(command):
    """Convert snake case to camelcase in class format."""
    return stringcase.pascalcase(command.replace('-', '_'))


class CommandWrapper:
    def __init__(self, loop, command):
        self.processes = {}
        self.command = command(loop)
        self.command.sync = False

    async def launch(self, *args, **kwargs):
        """Launch a command via asyncio."""
        uid = uuid.uuid4()
        self.processes[uid] = self.command.run(*args, **kwargs)
        return uid

    async def stop(self, key, *args, **kwargs):
        """Stop a process."""
        with suppress(Exception):
            self.processes[key].terminate()
        self.processes.pop(key)

    async def list_available(self):
        """List available processes"""
        return self.processes.keys()

    async def send_signal(self, key, signal):
        """Send a signal to a specific running process"""
        self.processes[key].send_signal(signal)
        if signal in (9, 15):
            self.stop()

    async def write_to_stdin(self, key, data):
        self.processes[key].write(data)

    async def read(self, key, num=None, search_for=None, separator='\n'):
        """Read until given bytes number or given separator found."""
        if num:
            return await self.processes[key].stdout.read(n=num)
        if search_for:
            return await search_in(self.processes[key].stdout, search_for)
        return await self.processes[key].stdout.readuntil(separator)
