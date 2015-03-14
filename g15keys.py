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

from Xlib import X
from Xlib.display import Display
from Xlib.ext.xtest import fake_input

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
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._disconnecting = False

    def _recv(self, length):
        received = 0
        data = b""
        while received < length:
            try:
                d = self._socket.recv(length - received)
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

    def connect(self, screen_type = G15_PIXELBUF):
        self._socket.connect(("localhost", 15550))
        if self._recv(16) != b"G15 daemon HELLO":
            log.error("Wrong daemon greeting!")
            sys.exit(3)
        self._socket.send(screen_type)

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
        self._socket.send(bytes([packet]))
        if cmd == G15DAEMON_GET_KEYSTATE:
            return struct.unpack("I", self._recv(4))[0]
        elif cmd in (G15DAEMON_IS_FOREGROUND, G15DAEMON_IS_USER_SELECTED):
            return struct.unpack("H", self._recv(2))[0] - 48

    def waitkey(self):
        return struct.unpack("I", self._recv(4))[0]

class G15KeysClient:
    def __init__(self):
        self._keys = 0
        self._profile = ''
        self._recording = False
        self._exiting = False
        if not self._load():
            return
        self._dc = DaemonConnection()
        self._dc.connect(G15_G15RBUF)
        self._dc.cmd(G15DAEMON_KEY_HANDLER)
        self._dc.cmd(G15DAEMON_MKEYLEDS, 1<<2)
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT, signal.SIGPIPE):
            signal.signal(s, self._exit)
        signal.signal(signal.SIGUSR1, self._load)
        while True:
            try:
                self._handle(self._dc.waitkey())
            except Exception:
                traceback.print_exc()
            self._dc.waitkey()

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
                log.debug("Finished recording, saving macro: %s", str(self._record))
                self._recording = False
                self._conf[self._profile][key] = "emit " + ",".join(self._record)
                self._save()
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
            self._record()
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
            self._dc.cmd(G15DAEMON_MKEYLEDS, 2**(int(led[1])-1))

    def _emit(self, keys):
        log.debug("Emitting key presses")
        d = Display()
        for key in keys.split(','):
            mouse = key[0] == 'm'
            press = key[1] == '+'
            num = int(key[2:])
            if mouse:
                ev = X.ButtonPress if press else X.ButtonRelease
            else:
                ev = X.KeyPress if press else X.KeyRelease
            fake_input(d, ev, num)
        d.sync()

    def _record(self):
        log.debug("Started recording macro")
        self._recording = True
        self._record = []

if __name__ == "__main__":
    def usage():
        print("Usage:", sys.argv[0], "[-h|--help] [-d|--debug] [-b|--background]")
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hdb", ["help", "debug", "background"])
    except getopt.GetoptError:
        usage()
        sys.exit(2)
    for opt, arg in opts:
        print(opt)
        if opt in ("-h", "--help"):
            usage()
            sys.exit()
        if opt in ("-d", "--debug"):
            logging.basicConfig(level=logging.DEBUG)
        if opt in ("-b", "--background"):
            if os.fork() > 0:
                sys.exit(0)
    G15KeysClient()

