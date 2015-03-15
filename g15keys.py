#!/bin/env python3

import getopt
import shlex
import socket
import logging
import math
import subprocess
import json
import struct
import signal
import os
import sys
import time
import collections
import traceback
import threading

from Xlib import X
from Xlib.display import Display
from Xlib.ext.xtest import fake_input
from Xlib.ext import record
from Xlib.protocol import rq 

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

G15_TEXTBUF  = b"TBUF"
G15_WBMPBUF  = b"WBUF"
G15_G15RBUF  = b"RBUF"
G15_PIXELBUF = b"GBUF"

G15DAEMON_KEY_HANDLER = 0x10
G15DAEMON_MKEYLEDS = 0x20
G15DAEMON_CONTRAST = 0x40
G15DAEMON_BACKLIGHT = 0x80
G15DAEMON_GET_KEYSTATE = 0x6b
G15DAEMON_SWITCH_PRIORITIES = 0x70
G15DAEMON_IS_FOREGROUND = 0x76
G15DAEMON_IS_USER_SELECTED = 0x75

G15_KEY_G1  = 1<<0
G15_KEY_G2  = 1<<1
G15_KEY_G3  = 1<<2
G15_KEY_G4  = 1<<3
G15_KEY_G5  = 1<<4
G15_KEY_G6  = 1<<5
G15_KEY_G7  = 1<<6
G15_KEY_G8  = 1<<7
G15_KEY_G9  = 1<<8
G15_KEY_G10 = 1<<9
G15_KEY_G11 = 1<<10
G15_KEY_G12 = 1<<11
G15_KEY_G13 = 1<<12
G15_KEY_G14 = 1<<13
G15_KEY_G15 = 1<<14
G15_KEY_G16 = 1<<15
G15_KEY_G17 = 1<<16
G15_KEY_G18 = 1<<17
G15_KEY_G19 = 1<<28
G15_KEY_G20 = 1<<29
G15_KEY_G21 = 1<<30
G15_KEY_G22 = 1<<31

G15_KEYS_G = (
    G15_KEY_G1,
    G15_KEY_G2,
    G15_KEY_G3,
    G15_KEY_G4,
    G15_KEY_G5,
    G15_KEY_G6,
    G15_KEY_G7,
    G15_KEY_G8,
    G15_KEY_G9,
    G15_KEY_G10,
    G15_KEY_G11,
    G15_KEY_G12,
    G15_KEY_G13,
    G15_KEY_G14,
    G15_KEY_G15,
    G15_KEY_G16,
    G15_KEY_G17,
    G15_KEY_G18,
    G15_KEY_G19,
    G15_KEY_G20,
    G15_KEY_G21,
    G15_KEY_G22
)

G15_KEY_M1  = 1<<18
G15_KEY_M2  = 1<<19
G15_KEY_M3  = 1<<20
G15_KEY_MR  = 1<<21

G15_KEYS_M = (
    G15_KEY_M1,
    G15_KEY_M2,
    G15_KEY_M3,
    G15_KEY_MR
)

G15_KEY_L1  = 1<<22
G15_KEY_L2  = 1<<23
G15_KEY_L3  = 1<<24
G15_KEY_L4  = 1<<25
G15_KEY_L5  = 1<<26

G15_KEYS_L = (
    G15_KEY_L1,
    G15_KEY_L2,
    G15_KEY_L3,
    G15_KEY_L4,
    G15_KEY_L5
)

G15_KEY_LIGHT = 1<<27


class DaemonConnection:
    def __init__(self):
        self._disconnecting = False

    def _recv(self, length):
        received = 0
        data = b""
        while received < length:
            try:
                d = self._socket.recv(length - received)
                if len(d) == 0:
                    return None
            except InterruptedError:
                continue
            except OSError:
                if not self._disconnecting:
                    raise
                else:
                    sys.exit()
            received += len(d)
            data += d
        return data

    def reconnect(self):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        while True:
            try:
                self._socket.connect(("localhost", 15550))
            except socket.error as e:
                msg = os.strerror(e.errno)
                log.error("Could not connect to daemon: %s. Will try again in 10 seconds.", msg)
            else:
                gr = self._recv(16)
                if gr != b"G15 daemon HELLO":
                    log.error("Wrong daemon greeting: %s. Will try again in 10 seconds.", gr)
                else:
                    break
            time.sleep(10)
        self._socket.send(self._screen_type)

    def connect(self, screen_type = G15_PIXELBUF):
        self._screen_type = screen_type
        self.reconnect()

    def disconnect(self):
        self._disconnecting = True
        self._socket.close()

    def cmd(self, cmd, val = 0):
        packet = cmd
        if cmd in (G15DAEMON_KEY_HANDLER, G15DAEMON_MKEYLEDS, G15DAEMON_CONTRAST, G15DAEMON_BACKLIGHT):
            if cmd in (G15DAEMON_KEY_HANDLER, G15DAEMON_MKEYLEDS):
                assert(0 <= val <= 1<<3)
            else:
                assert(0 <= val <= 1<<2)
            packet |= val
        log.debug("Sending packet (1 byte) to daemon: %s", str(packet))
        if self._socket.send(bytes([packet])) is None:
            return None
        if cmd == G15DAEMON_GET_KEYSTATE:
            ret = self._recv(4)
            if ret is None:
                return None
            return struct.unpack("I", ret)[0]
        elif cmd in (G15DAEMON_IS_FOREGROUND, G15DAEMON_IS_USER_SELECTED):
            ret = self._recv(2)
            if ret is None:
                return None
            return struct.unpack("H", ret)[0] - 48
        return 0

    def waitkey(self):
        ret = self._recv(4)
        if ret is None:
            return None
        return struct.unpack("I", ret)[0]


class G15KeysClient:
    def __init__(self, connect_signals = True):
        self._keys = 0
        self._profile = ''
        self._recording = False
        self._exiting = False
        self._display = None
        self._display_record = None
        if not self._load():
            return
        self._dc = DaemonConnection()
        self._dc.connect(G15_G15RBUF)
        self._reconnect(True)
        if connect_signals:
            for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT, signal.SIGPIPE):
                signal.signal(s, self._exit)
            signal.signal(signal.SIGUSR1, self._load)
        while True:
            try:
                key = self._dc.waitkey()
                if key is None:
                    self._reconnect()
                    continue
                self._handle(key)
            except Exception:
                traceback.print_exc()
            if self._dc.waitkey() is None:
                self._reconnect()

    def _reconnect(self, first = False):
        while True:
            if not first:
                log.error("Lost connection to daemon.")
                time.sleep(1)
                self._dc.reconnect()
            if self._dc.cmd(G15DAEMON_KEY_HANDLER) is None or self._dc.cmd(G15DAEMON_MKEYLEDS, 1<<2) is None:
                first = False
                continue
            if not first:
                log.info("Reconnected.")
            return

    def _exit(self, signum = 0, frame = 0):
        log.info("Graceful shutdown")
        self._dc.disconnect()
        self._exiting = True
        sys.exit()

    def _load(self, signum = 0, frame = 0):
        log.info("Loading configuration")
        with open(os.path.join(os.environ['HOME'], ".g15keys", "config")) as f:
            conf = json.load(f, object_pairs_hook=collections.OrderedDict)
        if not conf.keys:
            log.error("No profile found")
            return False
        if self._profile not in conf.keys():
            self._profile = next(iter(conf.keys()))
        self._conf = conf
        return True

    def _save(self):
        with open(os.path.join(os.environ['HOME'], ".g15keys", "config"), "w") as f:
            json.dump(self._conf, f, sort_keys=True, indent=4)
    
    def _handle(self, keys):
        changed = self._keys ^ keys
        pressed = self._keys
        self._keys = keys
        p = pressed < keys
        for g in G15_KEYS_G:
            if changed & g:
                key = int(math.log2(g)) + 1
                if key > 18:
                    key -= 10
                self._key("G" + str(key), p)
        for m in G15_KEYS_M:
            if changed & m:
                key = int(math.log2(m)) - 17
                if 1 <= key <= 3:
                    self._key("M" + str(key), p)
                else:
                    self._key("MR", p)
        for l in G15_KEYS_L:
            if changed & l:
                key = int(math.log2(l)) - 21
                self._key("L" + str(key), p)    

    def _key(self, key, pressed):
        log.debug("%s button %s", key, "pressed" if pressed else "released")
        if self._recording:
            if not pressed:
                self._stop_recording(key)
        else:
            c = self._conf[self._profile].get(key)
            if isinstance(c, dict):
                if pressed:
                    c = c.get("pressed")
                else:
                    c = c.get("released")
            elif isinstance(c, str) and not pressed:
                pass
            elif isinstance(c, list) and not pressed:
                pass
            else:
                c = None
            if c is not None:
                self._do(c)

    def _do(self, cmd):
        log.debug("Executing the following command: %s", cmd)
        if isinstance(cmd, list):
            for c in cmd:
                self._do(c)
            return
        if cmd.startswith("switch-profile "):
            self._switch_profile(cmd[15:])
        elif cmd.startswith("set-leds "):
            self._set_leds(cmd[9:])
        elif cmd.startswith("emit "):
            self._emit(cmd[5:])
        elif cmd == "record":
            self._start_recording()
        else:
            FNULL = open(os.devnull, 'w')
            subprocess.Popen(shlex.split(cmd), stdout=FNULL, stderr=FNULL, preexec_fn=os.setpgrp)

    def _switch_profile(self, p):
        if p in self._conf.keys():
            log.info("Switching profile to", p)
            self._profile = p
        else:
            log.warn("Profile not found:", p)

    def _set_leds(self, leds):
        log.debug("Setting LED state")
        for led in leds.split(','):
            if self._dc.cmd(G15DAEMON_MKEYLEDS, 2**(int(led[1])-1)) is None:
                self._reconnect()
                return

    def _emit(self, keys):
        if self._display is None:
            self._display = Display()
        log.debug("Emitting key presses")
        for key in keys.split(','):
            mouse = key[0] == 'm'
            press = key[1] == '+'
            num = int(key[2:])
            if mouse:
                ev = X.ButtonPress if press else X.ButtonRelease
            else:
                if key[0] == 's':
                    self._display.sync()
                    time.sleep(num/1000)
                    continue
                ev = X.KeyPress if press else X.KeyRelease
            fake_input(self._display, ev, num)
        self._display.sync()

    def _start_recording(self):
        if self._display is None:
            self._display = Display()
        if self._display_record is None:
            self._display_record = Display()
        log.debug("Started recording macro")
        self._recording = True
        self._record = []
        self._record_ctx = self._display_record.record_create_context(0, [record.AllClients], [{
            'core_requests': (0, 0),
            'core_replies': (0, 0),
            'ext_requests': (0, 0, 0, 0),
            'ext_replies': (0, 0, 0, 0),
            'delivered_events': (0, 0),
            'device_events': (X.KeyPress, X.KeyRelease),
            'errors': (0, 0),
            'client_started': False,
            'client_died': False
        }])
        thread = threading.Thread(target = self._display_record.record_enable_context, args=(self._record_ctx, self._record_key))
        thread.start()

    def _stop_recording(self, key):
        self._display.record_disable_context(self._record_ctx)
        self._display.record_free_context(self._record_ctx)
        self._display.flush()

        log.debug("Finished recording, saving macro: %s", str(self._record))
        self._recording = False
        self._conf[self._profile][key] = "emit " + ",".join(self._record)
        self._save()

    def _record_key(self, reply):
        log.debug("Received X event")
        if reply.category != record.FromServer or reply.client_swapped or not len(reply.data) or reply.data[0] < 2:
            return

        data = reply.data
        while len(data):
            event, data = rq.EventField(None).parse_binary_value(data, self._display_record.display, None, None)
            if event.type in [X.KeyPress, X.KeyRelease]:
                log.debug("Detected key: %d", event.detail)
                self._record.append("k" + (event.type == X.KeyPress and "+" or "-") + str(event.detail))

if __name__ == "__main__":
    def usage():
        print("Usage:", sys.argv[0], "[-h|--help] [-d|--debug] [-b|--background]")
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hdb", ["help", "debug", "background"])
    except getopt.GetoptError:
        usage()
        sys.exit(2)
    debug = False
    for opt, arg in opts:
        if opt in ("-h", "--help"):
            usage()
            sys.exit()
        if opt in ("-d", "--debug"):
            debug = True
            log.setLevel(logging.DEBUG)
        if opt in ("-b", "--background"):
            if os.fork() > 0:
                sys.exit(0)
    G15KeysClient(not debug)

