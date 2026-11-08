Scriptname MLWW_BanterAlias extends MLWW_PlayerAlias
{Player alias on the banter quest only: the base alias work plus hits on the player, which start the fight watch.}

Event OnHit(ObjectReference akAggressor, Form akSource, Projectile akProjectile, bool abPowerAttack, bool abSneakAttack, bool abBashAttack, bool abHitBlocked)
	MLWW_Banter banter = GetOwningQuest() as MLWW_Banter
	If !banter || banter.Watching()
		Return
	EndIf
	banter.PlayerHit()
EndEvent
