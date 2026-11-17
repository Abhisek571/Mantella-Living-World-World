Scriptname MLWW_Native Hidden
{Native functions from World's SKSE plugin (MLWW_Listener.dll).}

; Names of the items the player is wearing that belong to this NPC (stolen from them), comma separated; "" when none.
string Function WornStolenFrom(Actor akNpc) global native

; Followers set as teammates who are here now (loaded and close to the player, not told to wait), summons not included.
Actor[] Function Party() global native

; Gold in the merchant's vendor chest now; -1 when they have no vendor chest.
int Function ChestGold(Actor akMerchant) global native

; Reads the stage and state of every quest named (editor ids; unknown ones are left out) in one call and keeps them for
; QuestStagesJson / QuestStatesJson. Returns how many were found.
int Function ReadQuests(string[] akIds) global native

; Re-reads only the kept quests whose stage or run state changed since the last read (the plugin hears quest stage and
; start/stop events). Returns how many kept quests changed, or -1 when no quest at all changed.
int Function ReadChangedQuests() global native

; {"MQ101":20,...}: the kept quests' current stages, keyed by the ids as asked.
string Function QuestStagesJson() global native

; {"MQ101":1,...}: 0 not started, 1 running, 2 done.
string Function QuestStatesJson() global native

; The quests the outcome table names: a change to one of them makes OutcomeQuestsChanged true.
Function WatchOutcomeQuests(Quest[] akQuests) global native

; True (once) when a watched outcome quest changed since the last call.
bool Function OutcomeQuestsChanged() global native
