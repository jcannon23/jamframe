# Notes: listening to Control4's network audio

An experiment, not a feature. The aim: let JamFrame hear what a Control4 room is playing, so that sources with
no song information (a turntable) can be recognised by sound. Found on a Core 1 with Triad One amplifiers,
OS 4.0. Nothing here is from Control4's documentation.

## What is there

Each controller and amplifier runs an **audio server** (TCP 6000) and an **audio client** (TCP 6100). Both
speak a tagged text protocol with no sign-in: `<tag> <COMMAND> [arguments]`, answered `<tag> OK <COMMAND>`.
`HELP` and `STATUS` work on both and list everything.

- The box that owns a room's music runs the stream. `GETSTR` lists its streams; `STATUS` shows each stream's
  state, format (seen: 44.1 kHz 16-bit stereo for Spotify Connect), source and the clients it is sent to.
- The room's `CURRENT MEDIA INFO` in the Director API names the stream (`streamid`).
- Audio travels as RTP to each client's port 6200, with RTCP beside it and a network clock on the server.

## Subscribing

`ADDCLI <stream> <host> <port>` adds a listener; `REMCLI` with the same arguments removes it. The server then
connects to the listener's TCP 6100 and expects an audio client there:

1. `<n> PING` — answered `<n> OK PING`.
2. `<n> session "session_cmd, cmd=(int)0, port=(int)6200, rtcp=(int)6007, btime=(guint64)…, sclock=(string)<server>:6008;"`
   — a session description in GStreamer's notation: where to listen, where to send RTCP, a base time, and the
   address of the server's network clock.

## The reply that matters

A real client answers the session message with **two** lines:

    <n> session session_reply;
    <n> OK session

Sent only the second, the server's streamer stops the stream within seconds, for every room on it. Sent
both, it starts sending RTP to the listener and carries on serving everyone else. On removal it sends
`session "session_cmd, cmd=(int)2, port=(int)6200;"`, answered the same way.

How that was found: by playing the server's part toward an **idle** amplifier's client port and reading its
answer, and by testing on a private stream (below) rather than a room's.

## What arrives

RTP, payload type 96, to UDP 6200; RTCP to 6250, which can be ignored. The payload is GStreamer's
`rtpgstpay` wrapping around **FLAC** frames, 48 kHz 24-bit stereo whatever the source:

- bytes 0–11: RTP header. All pieces of one frame share a timestamp.
- bytes 12–15: flags. Bytes 16–19: this piece's offset into the frame.
- then the piece. A frame's first piece starts with 8 bytes that are not part of the frame.

Joined in offset order, each frame starts `FF F8` and describes itself, so prefixing `fLaC` and one
STREAMINFO block makes a file any FLAC decoder reads. `c4audio.py` does all of this.

Confirmed: a 440 Hz test tone came back as 440 Hz at the level sent; eight seconds of a record on a
turntable (an amplifier's analogue input, `dsp://dev/dsp0`, shared to a second room) were captured while
that room carried on playing.

## A safe place to experiment

An idle amplifier's audio server will play a file for no one: `ADDSTR` (answers `STREAM=<id>`),
`ADDMED <id> http://<your computer>/tone.wav`, `SETSTA <id> PLAY`, then `ADDCLI` yourself, and `REMSTR <id>`
at the end. A stream with no room on it can be broken freely.

## Cautions

- `ADDCLI` changes a live audio system. Always pair it with `REMCLI`, and check with `STATUS` afterwards.
- **A wrong handshake interrupts playback.** Twice, an acknowledgement without the reply line ended the
  stream: the music stopped and the room fell back to its previous source.
- A subscribed address that answers nothing on TCP 6100 is harmless: the server pings it and sends nothing.
- A bare `TEST` to a client port made that amplifier's audio client restart. Do not send it.
- An analogue input only becomes a network stream while another room is sharing it. Played only in its own
  room, there is nothing on the network to hear.
- All of this is unauthenticated on the home network, and none of it is documented by Control4: a firmware
  update could change it.
