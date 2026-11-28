"""Listen to a Control4 room's audio over the home network, so that music with no song information (a record
on a turntable) can be recognised by its sound. See docs/control4-audio-notes.md for how this was worked out.

A Control4 amplifier or controller that is playing something runs an audio server (TCP 6000). We ask it to add
us as a client of the stream, answer its handshake the way its own clients do, and it sends the stream to us
as RTP: FLAC frames in GStreamer's "rtpgstpay" wrapping. We put the frames back together into a FLAC file.

Usage: python c4audio.py <amplifier address> [seconds] [out.flac]     (listens to its first playing stream)
"""
import collections
import re
import select
import socket
import struct
import sys
import threading
import time

RTP, CONTROL = 6200, 6100       # where a Control4 audio client receives audio, and takes its instructions


def ask(server, text, wait=6.0, tries=4):
    """One command to an audio server; its answer as text ("" if it never answered)."""
    for attempt in range(tries):
        s = socket.socket()
        s.settimeout(wait)
        try:
            s.connect((server, 6000))
            s.sendall(("0001 %s\r\n" % text).encode())
            out = b""
            while not re.search(rb"0001 (OK|NO|BAD) ", out):
                chunk = s.recv(8192)
                if not chunk:
                    break
                out += chunk
            if out:
                return out.decode(errors="replace")
        except OSError:
            pass
        finally:
            s.close()
        time.sleep(1.5)
    return ""


def streams(server):
    """The streams an audio server is playing: {id: {"source", "clients"}}."""
    found, current = {}, None
    for line in ask(server, "STATUS").splitlines():
        line = line.replace("0001 STATUS", "").strip()
        if line.startswith("STREAM="):
            current = found.setdefault(int(line[7:]), {"source": "", "clients": [], "state": ""})
        elif current is not None and " = " in line:
            key, value = line.split(" = ", 1)
            if key == "Client":
                current["clients"].append(value)
            elif key in ("Source", "State"):
                current[key.lower()] = value
    return {i: s for i, s in found.items() if s["state"] == "PLAY"}


def answer(conn):
    """Be an audio client on the control connection the server opens to us. Its own clients answer every command
    with "<tag> OK <command>", and "session" with a reply line first. A server sent the acknowledgement without
    that line stops the whole stream, for every room on it."""
    conn.settimeout(30)
    buffer = b""
    try:
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                parts = line.decode(errors="replace").strip().split(" ", 2)
                if len(parts) < 2:
                    continue
                tag, command = parts[0], parts[1]
                reply = "%s session session_reply;\r\n" % tag if command == "session" else ""
                conn.sendall((reply + "%s OK %s\r\n" % (tag, command)).encode())
    except OSError:
        pass
    finally:
        conn.close()


def listen(server, stream, seconds, me):
    """Join a stream for some seconds and return what was heard as FLAC file bytes (b"" if nothing came).
    me: this computer's address, as the server should reach it."""
    control = socket.socket()
    control.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    control.bind(("", CONTROL))
    control.listen(4)
    control.settimeout(0.2)
    audio = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    audio.bind(("", RTP))
    reports = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)       # RTCP comes here; taken in and ignored
    reports.bind(("", RTP + 50))
    done, packets = threading.Event(), []

    def welcome():
        while not done.is_set():
            try:
                conn, _ = control.accept()
                threading.Thread(target=answer, args=(conn,), daemon=True).start()
            except socket.timeout:
                pass
    threading.Thread(target=welcome, daemon=True).start()
    try:
        if " OK " not in ask(server, "ADDCLI %d %s %d" % (stream, me, RTP)):
            return b""
        try:
            end = time.time() + seconds
            while time.time() < end:
                ready, _, _ = select.select([audio, reports], [], [], 0.2)
                for s in ready:
                    data, _ = s.recvfrom(65535)
                    if s is audio:
                        packets.append(data)
        finally:
            ask(server, "REMCLI %d %s %d" % (stream, me, RTP))          # whatever happened, leave the stream
            time.sleep(0.5)                                             # the server says goodbye on the control port
    finally:
        done.set()
        for s in (control, audio, reports):
            s.close()
    return flac(packets)


def flac(packets):
    """RTP packets (rtpgstpay carrying FLAC frames) -> a FLAC file's bytes.
    Each packet: 12 bytes of RTP header, 4 of flags, 4 of offset into the frame, then a piece of the frame.
    A frame's first piece starts with 8 more bytes that are not part of it."""
    frames = collections.OrderedDict()
    for p in packets:
        if len(p) > 20:
            stamp, offset = struct.unpack("!I", p[4:8])[0], struct.unpack("!I", p[16:20])[0]
            frames.setdefault(stamp, {})[offset] = p[20:]
    whole = [b"".join(parts[o] for o in sorted(parts))[8:] for parts in frames.values() if 0 in parts]
    whole = [f for f in whole if f[:2] == b"\xff\xf8"]
    if not whole:
        return b""
    h = whole[0]        # every frame says what it is; the file's header has to say it once
    block = {1: 192, 2: 576, 3: 1152, 4: 2304, 5: 4608, 8: 256, 9: 512, 10: 1024, 11: 2048, 12: 4096, 13: 8192}.get(h[2] >> 4, 4608)
    rate = {8: 32000, 9: 44100, 10: 48000, 11: 96000}.get(h[2] & 15, 48000)
    bits = {4: 16, 5: 20, 6: 24}.get((h[3] >> 1) & 7, 24)
    channels = 2 if (h[3] >> 4) >= 8 else (h[3] >> 4) + 1
    info = (struct.pack(">HH", block, block) + b"\x00" * 6
            + struct.pack(">Q", (rate << 44) | ((channels - 1) << 41) | ((bits - 1) << 36)) + b"\x00" * 16)
    return b"fLaC" + bytes([0x80, 0, 0, 34]) + info + b"".join(whole)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    server, seconds = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 8
    playing = streams(server)
    print("playing:", playing)
    if playing:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect((server, 6000))
        heard = listen(server, min(playing), seconds, probe.getsockname()[0])
        out = sys.argv[3] if len(sys.argv) > 3 else "heard.flac"
        open(out, "wb").write(heard)
        print("heard %d bytes -> %s" % (len(heard), out), "| still playing:", streams(server))
