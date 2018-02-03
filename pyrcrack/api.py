"""API."""

from aiohttp.web import Application
from aiohttp.web import run_app
from aiohttp.web import json_response

from . import AircrackNg

import docopt


async def command(request):
    """Receive a command."""
    res = await request.json()
    match_methods = {
        'put': 'launch',
        'post': 'read',
        'get': 'list_available',
        'patch': 'write_to_stdin',
        'delete': 'stop'}

    command = request.app['commands'][request.match_info['command']]
    return json_response({
        'res': await getattr(command, match_methods[request.method])(
            *res["args"], **res["kwargs"])})


def main():
    """Aircrack-ng asyncio API

    Usage: esim [options]

    Options:
        -h, --host=<host>              Host to listen on. [default: 0.0.0.0]
        -P, --port=<port>              Port to listen on. [default: 8080]
        -d, --debug                    Enable debug
    """
    args = docopt.docopt(main.__doc__)
    app = Application(debug=args['--debug'])
    app['commands'] = {'aircrack_ng': AircrackNg()}
    run_app(app, host=args['--host'], port=int(args['--port']))
