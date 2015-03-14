# g15keys

g15keys is a client for [g15daemon](http://sourceforge.net/projects/g15daemon/), aiming to be a g15macro replacement. You may only need to use this tool if you are using a G15/G19/G510(s) keyboard under Linux. It is intended for keyboards with 18 G-keys and 3 M-keys + MR-key, but it should work for keyboards with less or even more special keys.

At the moment, it is configured with a single file `$HOME/.g15keys/config` like the following:
```json
{
    "M1": {
        "M2": "switch-profile M2",
        "G1": "/usr/bin/xterm",
        "G2": "/usr/bin/xdg-email"
    },
    "M2": {
        "M1": "switch-profile M1",
        "G1": [ "/usr/bin/firefox", "/usr/bin/thunderbird" ],
        "G2": { "pressed": "emit k+133,k+10,k-10,k-133" }
    }
}
```

For each key, you can specifiy one or more action per key state. Valid states are `"pressed"` and `"released"`, the latter one is the default.

To start a program or a script, the full path, starting with `/` needs to be provided.

For emitting fake input: key presses are done with `k+<keycode>`, key releases with `k-<keycode>`; mouse buttons can be pressed and released with `m+<keycode>` / `m-<keycode>`. The required keycodes can be obtained by running `xev`.

For macro recording, assign the action `"record"` to some key (e.g. MR) and press it. Enter the macro you want to record and press a G-key or M-key to save the macro to this key.

The following is currently implemented:
* reacting upon key pressed and / or released
* executing programs or scripts
* capturing and emitting a series of key presses / releases (macro recording and playback)
* multiple profiles that can be switched by certain G-keys

Still outstanding:
* GUI tool for easier configuration
* automatic profile activation depending on certain conditions
* key tap repetition

Tested on the following keyboards:
* G510s
* test and feedback for other keyboards wanted

Patches and pull requests are welcome.
