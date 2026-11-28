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

## Where it stopped

Answering both messages with `<n> OK <command>` got the listener listed as a client of the stream, but no RTP
arrived in ten seconds. Not yet tried: answering the session message differently, sending RTCP receiver
reports to the port it names, or taking part in the network clock (`sclock`), any of which a real client does.

## Cautions

- `ADDCLI` changes a live audio system. Always pair it with `REMCLI`, and check with `STATUS` afterwards.
- The server was briefly slow to answer during one subscription.
- **It interrupted playback.** During the last attempt the stream ended, the music stopped, and the room
  fell back to its previous source (a TV). Confirmed by the person in the room: they had touched nothing.
  A half-working client appears to be worse for the stream than no client. Do not run this while anyone is
  listening.
- An analogue input on an amplifier may only become a network stream when another room shares it.
