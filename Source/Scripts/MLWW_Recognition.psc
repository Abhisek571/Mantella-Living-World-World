Scriptname MLWW_Recognition extends MLWW_Job
{Mantella Living World - World: hiding and recognition. When an NPC joins a conversation while the player sneaks
unseen, or hides their face under a hood or helmet in a hold where they are not famous, Mantella is told the NPC
does not recognise the player. People who know the player personally still do: friends, family, followers, a
Thane's hold, and anyone who has seen the player's face in a talk before. Outside any hold a hood hides nothing. Uncanny observers (observation 4+
in Knowledge's observation.json, else the NPC's file npc/<baseid>.json, default 2) see through it, and Mantella is told that instead.
Whether a hood or helmet covers the player's face is also kept in MantellaLivingWorld/recognition.json (int face_hidden),
written whenever the player's gear changes and on each game load, so Mantella's side knows it before a talk starts and
can tell the NPC in the greeting itself (the event below only reaches the talk after the greeting).}

MLWW_State Property World Auto

string Property NPC_FOLDER = "MantellaLivingWorld/npc/" AutoReadOnly
int Property OBSERVATION_DEFAULT = 2 AutoReadOnly
int Property UNCANNY = 4 AutoReadOnly
; Fame in this hold at which a face under a hood is still known.
int Property FAME_KNOWN = 3 AutoReadOnly
; Biped slots 30 (head) and 31 (hair): hoods, helmets, masks.
int Property SLOT_HEAD = 0x00000001 AutoReadOnly
int Property SLOT_HAIR = 0x00000002 AutoReadOnly
string Property KEY_MET = "MLWW_RecogMet" AutoReadOnly
string Property FACE_FILE = "MantellaLivingWorld/recognition.json" AutoReadOnly

Function Register()
	RegisterForModEvent("MantellaConversation_NPC_Added", "OnNpcAdded")
	WriteFace()
EndFunction

Function PlayerGearChanged()
	WriteFace()
EndFunction

; 1 while a hood, helmet or mask covers the player's face; written only when it changed.
Function WriteFace()
	int hidden = 0
	If FaceHidden()
		hidden = 1
	EndIf
	If !JsonUtil.HasIntValue(FACE_FILE, "face_hidden") || JsonUtil.GetIntValue(FACE_FILE, "face_hidden", -1) != hidden
		JsonUtil.SetIntValue(FACE_FILE, "face_hidden", hidden)
		JsonUtil.Save(FACE_FILE)
	EndIf
EndFunction

Event OnNpcAdded(Form akActor)
	If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1  ; speed testing (off by default): one stage-time row
		MiscUtil.WriteToFile("Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/timing_game.csv", StorageUtil.GetIntValue(None, "MLW_TimingTalk", 0) + "," + Utility.GetCurrentRealTime() + ",MLWW_Recognition,OnNpcAdded_start,\n", true, false)
	EndIf
	Actor npc = akActor as Actor
	If !npc || npc == PlayerRef || npc.IsDead()
		Return
	EndIf
	WriteFace()  ; kept fresh for the next talk's greeting
	string line = Verdict(npc)
	; kept for Meetings in the same join, so the verdict is worked out once
	StorageUtil.SetStringValue(npc, "MLWW_Verdict", line)
	StorageUtil.SetFloatValue(npc, "MLWW_VerdictAt", Utility.GetCurrentRealTime())
	If line != ""
		MLWW_Util.Send("recognition", line)
	EndIf
	If !Unrecognised(line)
		StorageUtil.SetIntValue(npc, KEY_MET, 1)  ; they have seen the player as they are now
	EndIf
	If StorageUtil.GetIntValue(None, "MLW_TimingOn", 0) == 1  ; speed testing (off by default): one stage-time row
		MiscUtil.WriteToFile("Data/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/timing_game.csv", StorageUtil.GetIntValue(None, "MLW_TimingTalk", 0) + "," + Utility.GetCurrentRealTime() + ",MLWW_Recognition,OnNpcAdded_end,\n", true, false)
	EndIf
EndEvent

; True for a verdict line that says the NPC does not know who the player is (MLWW_Meetings asks too).
bool Function Unrecognised(string asVerdict)
	Return StringUtil.Find(asVerdict, " does not recognise ") >= 0
EndFunction

string Function Verdict(Actor akNpc)
	string npc = akNpc.GetDisplayName()
	string player = MLWW_Util.PlayerName()
	int observation = Observation(akNpc)
	bool seesThrough = observation >= UNCANNY
	If PlayerRef.IsSneaking() && !PlayerRef.IsDetectedBy(akNpc) && !KnowsPersonally(akNpc)
		If seesThrough
			Return npc + " senses " + player + " sneaking nearby and knows who it is."
		EndIf
		Return npc + " does not recognise the stranger who stays hidden out of sight."  ; never the name to someone who does not know it
	EndIf
	If !FaceHidden() || KnowsPersonally(akNpc)
		Return ""
	EndIf
	int hold = World.CurrentHold()
	; before the first scan fame and Thane read 0: no hood line rather than a wrong one
	If hold < 0 || !World.Ready() || World.Fame(hold) >= FAME_KNOWN || World.IsThane(hold)
		Return ""
	EndIf
	If seesThrough
		Return npc + " sees through " + player + "'s hood and knows who they are."
	EndIf
	Return npc + " does not recognise the hooded stranger: a hood hides their face."  ; never the name (live test 15)
EndFunction

int Function Observation(Actor akNpc)
	; Knowledge ships every NPC's observation in one file; without Knowledge the NPC's own file is read
	int known = JsonUtil.GetIntValue("MantellaLivingWorld/observation.json", MLWW_Util.BaseId(akNpc), -1)
	If known >= 0
		Return known
	EndIf
	string file = NPC_FOLDER + MLWW_Util.BaseId(akNpc) + ".json"
	If !JsonUtil.JsonExists(file)
		Return OBSERVATION_DEFAULT
	EndIf
	; an int field of the NPC's file (JsonUtil keeps it under "int"). The file is shared with the Hub, Relationships
	; and Missives, so it is never unloaded here: that would drop their unsaved writes.
	Return JsonUtil.GetIntValue(file, "observation", OBSERVATION_DEFAULT)
EndFunction

; Something in the head slot (a helmet, a mask), or a hood in the hair slot. The hair slot alone counts only for a piece
; made to be worn over the head (the ArmorHelmet or ClothingHead keyword): wigs and hair pieces use that slot too, and
; never hide the face (live test 18: a wig made every NPC see a hooded stranger). A piece named as a wig never counts.
bool Function FaceHidden()
	Armor head = PlayerRef.GetWornForm(SLOT_HEAD) as Armor
	If head && !IsWig(head)
		Return true
	EndIf
	Armor hair = PlayerRef.GetWornForm(SLOT_HAIR) as Armor
	If !hair || hair == head || IsWig(hair)
		Return false
	EndIf
	Keyword helmet = Game.GetFormFromFile(0x06C0EE, "Skyrim.esm") as Keyword    ; ArmorHelmet
	Keyword clothingHead = Game.GetFormFromFile(0x10CD11, "Skyrim.esm") as Keyword  ; ClothingHead
	Return (helmet && hair.HasKeyword(helmet)) || (clothingHead && hair.HasKeyword(clothingHead))
EndFunction

; A worn piece whose name has the word "wig" (wig, Wig or WIG; brackets and dashes count as spaces).
bool Function IsWig(Armor akPiece)
	string name = " " + akPiece.GetName() + " "
	name = MLWW_Util.Replace(MLWW_Util.Replace(MLWW_Util.Replace(MLWW_Util.Replace(name, "(", " "), ")", " "), "-", " "), ",", " ")
	Return StringUtil.Find(name, " wig ") >= 0 || StringUtil.Find(name, " Wig ") >= 0 || StringUtil.Find(name, " WIG ") >= 0
EndFunction

; Friends, lovers, family, followers and anyone the player has spent time with know the voice and the walk.
bool Function KnowsPersonally(Actor akNpc)
	; PlayerRef's rank to them: Hearthfire keeps the player's rank to an adopted child while the child's is 0.
	If akNpc.GetRelationshipRank(PlayerRef) >= 1 || PlayerRef.GetRelationshipRank(akNpc) >= 1 || akNpc.IsPlayerTeammate()
		Return true
	EndIf
	; Seen the player's face in a talk before; close to the player in Relationships (spouse, lover).
	If StorageUtil.GetIntValue(akNpc, KEY_MET) == 1 || StorageUtil.GetIntValue(akNpc, "MRB_Close") > 0
		Return true
	EndIf
	Faction follower = Game.GetFormFromFile(0x05C84E, "Skyrim.esm") as Faction
	Faction adopted = Game.GetFormFromFile(0x0042B0, "HearthFires.esm") as Faction  ; BYOHRelationshipAdoptionFaction
	Faction steward = Game.GetFormFromFile(0x00308E, "HearthFires.esm") as Faction  ; BYOHHouseStewardFaction
	Return (follower && akNpc.IsInFaction(follower)) || (adopted && akNpc.IsInFaction(adopted)) || (steward && akNpc.IsInFaction(steward))
EndFunction
