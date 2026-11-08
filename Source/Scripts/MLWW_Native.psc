Scriptname MLWW_Native Hidden
{Native functions from World's SKSE plugin (MLWW_Listener.dll).}

; Names of the items the player is wearing that belong to this NPC (stolen from them), comma separated; "" when none.
string Function WornStolenFrom(Actor akNpc) global native

; Followers set as teammates who are here now (loaded and close to the player, not told to wait), summons not included.
Actor[] Function Party() global native

; Gold in the merchant's vendor chest now; -1 when they have no vendor chest.
int Function ChestGold(Actor akMerchant) global native
