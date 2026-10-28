MLWW_Listener - nearby voiced line listener for Mantella Living World - World
Copyright (C) 2026 itsPigeon2000

This program is free software: you can redistribute it and/or modify it under the terms of
the GNU General Public License as published by the Free Software Foundation, either
version 3 of the License, or (at your option) any later version. See LICENSE.txt.

Built against CommonLibSSE-NG (GPL-3.0). Skyrim SE 1.5.97 and AE 1.6.x, needs SKSE and
Address Library. Install as SKSE/Plugins/MLWW_Listener.dll.


What it does
------------
When an NPC starts a dialogue line (idle chatter, follower comments, greetings, scene lines):

1. Mod event "MLWW_VoicedLine"
     Event OnVoicedLine(string eventName, string strArg, float numArg, Form sender)
     sender = speaking Actor, strArg = line text, numArg = distance to the player (units).
2. Appends the line to
     Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/said_nearby.json
   keeping the newest 10, written atomically (said_nearby.json.tmp, then rename):
     {"lines": [{"speaker": "Serana", "base_id": "002B6C", "text": "...", "time": 1761630000.0}]}
   base_id = FormID of GetActorBase() & 0xFFFFFF as 6 uppercase hex digits.
   time    = Unix epoch seconds.

Filters for MLWW_VoicedLine and the file:
  - speaker must be an Actor and not the player
  - info not defined by Mantella.esp
  - speaker within 2048 units of the player
  - at least 6 words
  - not the same text from the same speaker within the last 10 seconds

Lines whose topic info is defined by Mantella.esp are not written and do not send
MLWW_VoicedLine. They send "MLWW_MantellaLine" instead (no word or distance limit):
  sender = speaking Actor, strArg = subtitle text (may be empty),
  numArg = rough duration in seconds = max(2, words * 0.4).
This event fires about 0.5 s after the line starts.


How it works (and why)
----------------------
Mechanism: a BSTEventSink<TESTopicInfoEvent> on ScriptEventSourceHolder. No hooks, no polling.

  - TESTopicInfoEvent (kTopicBegin) is the engine event behind topic info OnBegin
    fragments. It carries the speaker reference and the TESTopicInfo FormID, and it does
    not depend on the subtitle settings.
  - Line text: response text is not kept in memory after load, so the plugin builds the
    same DialogueItem the engine builds to speak the info (engine function, Address Library
    IDs 34413 / 35220) and joins its response texts. All responses of a multi-response info
    are joined into one line. Text-replacement tags, if a line has any, are left as written.
  - Mantella lines: Mantella speaks every generated line through a few fixed topics and injects
    the real text into the subtitle (MantellaSubtitles.dll). The info's own text is a
    placeholder, and building a DialogueItem for it could interfere with that injection,
    so for these infos the text is read from RE::SubtitleManager instead.

Rejected:
  - SubtitleManager as the main source: entries are only added through the subtitle display
    path (ShowSubtitle). Floating Subtitles notes that general and dialogue subtitles must be
    enabled for subtitles to exist, so with subtitles off there would be nothing to read.
    Reading it also needs polling or a hook on ShowSubtitle.
  - A hook: not needed, since the event gives both speaker and info.

Threading: the event sink only queues an SKSE task. All game reads and mod events run on
the main thread inside that task. File writes run on a small worker thread, so the main
thread never touches the disk for the JSON file.

Log: Documents/My Games/Skyrim Special Edition/SKSE/MLWW_Listener.log


Building
--------
  .\build.ps1      (VS 2022 Build Tools, CMake, Ninja, vcpkg; output build\release\MLWW_Listener.dll)
CommonLibSSE-NG is expected in lib\commonlibsse-ng.
