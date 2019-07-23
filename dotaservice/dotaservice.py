from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from struct import unpack
import asyncio
import atexit
import glob
import json
import logging
import math
import os
import psutil
import shutil
import signal
import subprocess
import time
import uuid

from aiohttp import web
from google.protobuf.json_format import MessageToDict
from grpclib.server import Server
import google.protobuf.text_format as txtf

from protobuf.CMsgBotWorldState_pb2 import CMsgBotWorldState
from protobuf.DotaService_grpc import DotaServiceBase
from protobuf.DotaService_pb2 import Observation

# logging.basicConfig(level=logging.DEBUG)
routes = web.RouteTableDef()


TICKS_PER_OBSERVATION = 9
TICKS_PER_SECOND = 30
DOTA_PATH = '/Users/tzaman/Library/Application Support/Steam/SteamApps/common/dota 2 beta/game'
PORT_WORLDSTATE_RADIANT = 12120
PORT_WORLDSTATE_DIRE = 12121
PORT_REST = 13337

# An enum from the game (should have been in the proto though).
DOTA_GAMERULES_STATE_PRE_GAME = 4
DOTA_GAMERULES_STATE_GAME_IN_PROGRESS = 5


if not os.path.exists(DOTA_PATH):
    raise ValueError('dota game path does not exist: {}'.format(DOTA_PATH))

BOTS_FOLDER_NAME = 'bots'
DOTA_BOT_PATH = os.path.join(DOTA_PATH, 'dota', 'scripts', 'vscripts', 'bots')

# Remove the dota bot directory
if os.path.exists(DOTA_BOT_PATH) or os.path.islink(DOTA_BOT_PATH):
    if os.path.isdir(DOTA_BOT_PATH) and not os.path.islink(DOTA_BOT_PATH):
        raise ValueError(
            'There is already a bots directory ({})! Please remove manually.'.format(DOTA_BOT_PATH))
    os.remove(DOTA_BOT_PATH)

GAME_ID = uuid.uuid1()
print('GAME_ID=', GAME_ID)

ACTION_FOLDER_ROOT = '/Volumes/ramdisk/'
if not os.path.exists(ACTION_FOLDER_ROOT):
    raise ValueError('Action folder does not exist. Please mount! ({})'.format(ACTION_FOLDER_ROOT))

SESSION_FOLDER = os.path.join(ACTION_FOLDER_ROOT, str(GAME_ID))
os.mkdir(SESSION_FOLDER)

BOT_PATH = os.path.join(SESSION_FOLDER, BOTS_FOLDER_NAME)
os.mkdir(BOT_PATH)

ACTION_SUBFOLDER_NAME = 'actions'
ACTION_FOLDER = os.path.join(BOT_PATH, ACTION_SUBFOLDER_NAME)
os.mkdir(ACTION_FOLDER)

# Copy all the bot files into the action folder
for filename in glob.glob('../bot_script/*.lua'):
    shutil.copy(filename, BOT_PATH)

# Symlink DOTA to this folder
os.symlink(src=BOT_PATH, dst=DOTA_BOT_PATH)

# Write the config file to a lua file, so that it can be imported from multiple .lua files.
SETTINGS_FILE = os.path.join(BOT_PATH, 'config_auto.lua')
settings = {
    'game_id': str(GAME_ID),
    'ticks_per_observation': TICKS_PER_OBSERVATION,
    'action_subfolder_name': ACTION_SUBFOLDER_NAME,
    'ticks_per_second': TICKS_PER_SECOND,
    'port_rest': PORT_REST,
}

settings_data = """
-- THIS FILE IS AUTO GENERATED
return '{}'
""".format(json.dumps(settings, separators=(',',':')))

with open(SETTINGS_FILE, 'w') as f:
    f.write(settings_data)

def atomic_file_write(filename, data):
    filename_tmp = "{}_".format(filename)
    f = open(filename_tmp, 'w')
    f.write(data)
    f.flush()
    os.fsync(f.fileno()) 
    f.close()
    os.rename(filename_tmp, filename)


# fut = asyncio.get_event_loop().create_future()

first_tick_future = asyncio.get_event_loop().create_future()

class DotaService(DotaServiceBase):

    tick = None

    async def reset(self, stream):
        """reset method.

        This method should start up the dota game and the other required services.
        """
        print('DotaService::reset()')
        
        # Create all the processes here. 

        # TODO(tzaman)

        # We then have to wait for the first tick to come in
        first_tick = await first_tick_future
        print('(py) DotaService::reset, first_tick=', first_tick)

        # Then we search through out worldstate queue we receive for the corresponding tick
        while True:
            print('(py) DotaService::reset, queue size=', worldstate_queue.qsize())
            data = await worldstate_queue.get()
            tick = dotatime_to_tick(data.dota_time)
            if tick == first_tick:
                print('(py) DotaService::reset, FOUND IT!')
                break
        self.tick = tick

        # Return the reponse
        await stream.send_message(Observation(world_state=data))

    async def step(self, stream):
        print('DotaService::step()')
        # global fut

        request = await stream.recv_message()
        print('  request={}'.format(request))
        # data = CMsgBotWorldState()

        filename = os.path.join(ACTION_FOLDER, "{}.lua".format(self.tick))
        data_dict = MessageToDict(request)

        data = "data = '{}'".format(json.dumps(data_dict, separators=(',',':')))
        print('(python) action data=', data)

        atomic_file_write(filename, data)

        # We've started to assume our queue will only have 1 item.
        data = await worldstate_queue.get()
        tick = dotatime_to_tick(data.dota_time)

        # Update the tick
        self.tick = tick

        # Make sure indeed the queue is empty and we're entirely in sync.
        assert worldstate_queue.qsize() == 0

        # Return the reponse.
        await stream.send_message(Observation(world_state=data))




async def serve(server, *, host='127.0.0.1', port=50051):
    await server.start(host, port)
    print('Serving on {}:{}'.format(host, port))
    try:
        await server.wait_closed()
    except asyncio.CancelledError:
        server.close()
        await server.wait_closed()


async def grpc_main(loop):
    server = Server([DotaService()], loop=loop)
    await serve(server)





def dotatime_to_tick(dotatime):
    return math.floor(dotatime * TICKS_PER_SECOND + 0.5)  # 0.5 for rounding


def kill_processes_and_children(pid, sig=signal.SIGTERM):
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    for process in children:
        process.send_signal(sig)


async def run_dota():
    script_path = os.path.join(DOTA_PATH, 'dota.sh')
    args = [
        script_path,
        # "-botworldstatesocket_threaded",
        "-botworldstatetosocket_dire 12121",
        "-botworldstatetosocket_frames {}".format(TICKS_PER_OBSERVATION),
        "-botworldstatetosocket_radiant 12120",
        "-console,",
        "-dedicated",
        # "-dev",  # Not sure what this does
        "-fill_with_bots",
        "-host_force_frametime_to_equal_tick_interval 1",
        "-insecure",
        "-nowatchdog",  # WatchDog will quit the game if e.g. the lua api takes a few seconds.
        "+clientport 27006",  # Relates to steam client.
        "+dota_1v1_skip_strategy 1",  # doesn't work icm `-fill_with_bots`
        "+dota_auto_surrender_all_disconnected_timeout 0",
        "+dota_bot_practice_gamemode 11",  # Mid Only -> doesn't work icm `-fill_with_bots`
        "+dota_force_gamemode 11",  # Mid Only -> doesn't work icm `-fill_with_bots`
        "+dota_start_ai_game 1",
        "+dota_surrender_on_disconnect 0",
        "+host_timescale 10",
        "+map start",  # the `start` map works with replays when dedicated, map `dota` doesn't.
        "+sv_cheats 1",
        "+sv_hibernate_when_empty 0",
        "+sv_lan 1",
        "+tv_autorecord 1",
        "+tv_delay 0 ",
        "+tv_dota_auto_record_stressbots 1",
        "+tv_enable 1",
    ]
    create = asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        # stdout=asyncio.subprocess.PIPE,
        # stderr=asyncio.subprocess.PIPE,
    )
    proc = await create
    try:
        await proc.wait()
    except asyncio.CancelledError:
        kill_processes_and_children(pid=proc.pid)
        raise


async def data_from_reader(reader):
    port = None  # HACK
    print('data_from_reader()')
    # Receive the package length.
    data = await reader.read(4)
    # eternity(), timeout=1.0)
    n_bytes = unpack("@I", data)[0]
    # print('n_bytes=', n_bytes)
    # Receive the payload given the length.
    data = await asyncio.wait_for(reader.read(n_bytes), timeout=5.0)
    # Decode the payload.
    # print('data=', data)
    parsed_data = CMsgBotWorldState()
    parsed_data.ParseFromString(data)
    dotatime = parsed_data.dota_time
    gamestate = parsed_data.game_state
    tick = dotatime_to_tick(dotatime)
    # print('worlstate recevied dotatime=', dotatime)
    print('worldstate received @dotatime={} @tick={} @gamestate={}'.format(dotatime, tick, gamestate))
    return tick, parsed_data




async def worldstate_listener(port):
    print('creating worldstate_listener @ port %s' % port)
    await asyncio.sleep(2)
    print('opening reader..!')
    # global reader
    reader, writer = await asyncio.open_connection('127.0.0.1', port)#, loop=loop)
    print('reader opened!')
    try:
        while True:
            # This reader is always going to need to keep going

            tick, parsed_data = await data_from_reader(reader)
            # print('received workstate tick=', tick)
            # We will receive world states from all game states. We are only interested in the ones
            # pre/during/post game.
            if not worldstate_calibration_tick_future.done() and \
                parsed_data.game_state == DOTA_GAMERULES_STATE_PRE_GAME:
                # On the first occurance of the pre game worldstate, send the calibration tick.
                worldstate_calibration_tick_future.set_result(tick)

            print('py) worldstate_listener, putting in queue (tick):', dotatime_to_tick(parsed_data.dota_time))
            worldstate_queue.put_nowait(parsed_data)
            print('(py) worldstate_listener, queue size=', worldstate_queue.qsize())

            # # Next, we want to know what the next state is on that we're actionable.
            # # Maybe the bot can do a POST, indicating it's waiting for an action with a specific
            # # tick.
            # if fut is not None:
            #     print('setting result on future')
            #     fut.set_result(parsed_data)  # Maybe just always set the latest data?
            #     print('END setting result on future')

    except asyncio.CancelledError:
        raise





@routes.post('/calibration')
async def handler(request):
    settings = {
        'calibration_tick': await worldstate_calibration_tick_future
        }
    return web.json_response(data=settings)

@routes.post('/step')
async def handler(request):
    tick = request.query['tick']
    # Now give this tick to dotaservice.reset somehow..
    first_tick_future.set_result(int(tick))
    return web.Response()


async def rest_api(loop):
    app = web.Application()#loop=loop)
    app.router.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', PORT_REST)
    await site.start()


loop = asyncio.get_event_loop()

worldstate_queue = asyncio.Queue(loop=loop)

worldstate_calibration_tick_future = loop.create_future()

tasks =  asyncio.gather(
    rest_api(loop),
    run_dota(),
    grpc_main(loop),
    worldstate_listener(port=PORT_WORLDSTATE_RADIANT),
    # worldstate_listener(port=PORT_WORLDSTATE_DIRE),
)



try:
    loop.run_until_complete(tasks)
except KeyboardInterrupt:
    # Optionally show a message if the shutdown may take a while
    print("Attempting graceful shutdown, press Ctrl+C again to exit…", flush=True)

    # Do not show `asyncio.CancelledError` exceptions during shutdown
    # (a lot of these may be generated, skip this if you prefer to see them)
    def shutdown_exception_handler(loop, context):
        if "exception" not in context \
        or not isinstance(context["exception"], asyncio.CancelledError):
            loop.default_exception_handler(context)
    loop.set_exception_handler(shutdown_exception_handler)

    # Handle shutdown gracefully by waiting for all tasks to be cancelled
    tasks = asyncio.gather(*asyncio.Task.all_tasks(loop=loop), loop=loop, return_exceptions=True)
    tasks.add_done_callback(lambda t: loop.stop())
    tasks.cancel()

    # Keep the event loop running until it is either destroyed or all
    # tasks have really terminated
    while not tasks.done() and not loop.is_closed():
        loop.run_forever()
finally:
    loop.close()
