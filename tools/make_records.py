"""Writes the World module's plugin as Spriggit YAML (one quest per job, each with a player alias that re-registers
its events on every game load) and its Mantella action files. Run from the project root."""
import json, os

E = 'Mantella Living World - World.esp'
# form id, editor id, script, name, needs the State quest
QUESTS = [
    ('000800', 'MLWW_QuestState', 'MLWW_State', 'Mantella Living World - World state', False),
    ('000801', 'MLWW_QuestMeetings', 'MLWW_Meetings', 'Mantella Living World - World meetings', True),
    ('000802', 'MLWW_QuestRecognition', 'MLWW_Recognition', 'Mantella Living World - World recognition', True),
    ('000803', 'MLWW_QuestPairs', 'MLWW_Pairs', 'Mantella Living World - World pairs', True),
    ('000804', 'MLWW_QuestCrime', 'MLWW_Crime', 'Mantella Living World - World crime', True),
    ('000805', 'MLWW_QuestBanter', 'MLWW_Banter', 'Mantella Living World - World banter', False),
    ('000806', 'MLWW_QuestInitiative', 'MLWW_Initiative', 'Mantella Living World - World initiative', False),
]
# Settings (World page of the Integration Hub's MCM): form id, editor id, type, value, the script that uses it
GLOBALS = [('000810', 'MLWW_BanterOn', 'GlobalShort', 1, 'MLWW_Banter'),
           ('000811', 'MLWW_BanterChance', 'GlobalShort', 30, 'MLWW_Banter'),
           ('000812', 'MLWW_InitiativeOn', 'GlobalShort', 1, 'MLWW_Initiative')]
STATE = QUESTS[0][0]


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'w', encoding='utf-8', newline='\n').write(text)


for fid, eid, script, name, needs_state in QUESTS:
    props = '    - MutagenObjectType: ScriptObjectProperty\n      Name: PlayerRef\n      Object: 000014:Skyrim.esm\n'
    if needs_state:
        props += f'    - MutagenObjectType: ScriptObjectProperty\n      Name: World\n      Object: {STATE}:{E}\n'
    for gfid, gname, _, _, user in GLOBALS:
        if user == script:
            props += f'    - MutagenObjectType: ScriptObjectProperty\n      Name: {gname}\n      Object: {gfid}:{E}\n'
    write(f'esp/Quests/{eid} - {fid}_{E}.yaml',
          f"FormKey: {fid}:{E}\nEditorID: {eid}\nVirtualMachineAdapter:\n  Scripts:\n  - Name: {script}\n    Properties:\n{props}"
          f"  FileName: ''\n  Aliases:\n  - Property:\n      Name: ''\n      Object: {fid}:{E}\n      Alias: 0\n"
          f"    Scripts:\n    - Name: MLWW_PlayerAlias\n"
          f"Name:\n  TargetLanguage: English\n  Value: {name}\nFlags:\n- StartGameEnabled\nNextAliasID: 1\n"
          f"Aliases:\n- Name: PlayerAlias\n  Flags: []\n  ForcedReference: 000014:Skyrim.esm\n  VoiceTypes: Null\n")
for gfid, gname, typ, val, _ in GLOBALS:
    write(f'esp/Globals/{gname} - {gfid}_{E}.yaml', f'MutagenObjectType: {typ}\nFormKey: {gfid}:{E}\nEditorID: {gname}\nData: {val}\n')
write('esp/RecordData.yaml', f'ModKey: {E}\nGameRelease: SkyrimSE\nModHeader:\n  Flags:\n  - Small\n  Author: itsPigeon2000\n'
      '  Description: Mantella Living World - World. Fame, crime, war side, quest outcomes, since we last met, hiding, who knows whom, settle crime, banter, NPCs who come to talk.\n'
      '  MasterReferences:\n  - Master: Skyrim.esm\n    FileSize: 0\n')
write('esp/spriggit-meta.json', json.dumps({'PackageName': 'Spriggit.Yaml.Skyrim', 'Version': '0.40.0', 'Release': 'SkyrimSE', 'ModKey': E}, indent=2))

NOTE = "Needs Mantella Living World - World. Turn off Mantella's own AbsolveCrime and ReportCrime (separate actions from SettleCrime and ReportWitnessedCrime)."
ACTIONS = [
    {'identifier': 'mantella_mlww_settle_crime', 'name': 'SettleCrime',
     'description': "Settle the player's non-violent bounty in your hold: pay it, take a bribe, or let it go when persuaded.",
     'key': 'SettleCrime',
     'parameters': {'method': {'type': 'string', 'enum': ['pay', 'bribe', 'persuade'],
                               'description': 'pay: the player pays the bounty; bribe: the player pays you extra to forget it; persuade: you let a minor bounty go.'}},
     'required': ['method'],
     'prompt': "If you are a guard, steward or Jarl and agree to settle the player's bounty (paid, bribed or persuaded), begin your response with '{key}:'"},
    # Not "ReportCrime": Mantella's Disabled Actions matches by name, and its own ReportCrime is disabled by default.
    {'identifier': 'mantella_mlww_report_crime', 'name': 'ReportWitnessedCrime',
     'description': 'Add a bounty for a crime a witness in this conversation saw the player commit.',
     'key': 'ReportWitnessedCrime',
     'parameters': {'crime': {'type': 'string', 'enum': ['trespassing', 'lockpicking', 'pickpocketing', 'theft', 'assault', 'murder'],
                              'description': 'The crime the witness saw.'}},
     'required': ['crime'],
     'prompt': "If you are a guard, steward or Jarl and someone here tells you they saw the player commit a crime, begin your response with '{key}:'"},
]
for a in ACTIONS:
    data = {'identifier': a['identifier'], 'name': a['name'], 'description': a['description'], 'note': NOTE, 'key': a['key'],
            'enabled': True, 'lw_gate': 'guard', 'parameters': a['parameters'], 'required': a['required'], 'prompt': a['prompt'],
            'allowed_games': ['skyrim'], 'requires_response': True, 'is-interrupting': False, 'allow_repeat': False,
            'one-on-one': True, 'multi-npc': True, 'radiant': False}
    write(f"SKSE/Plugins/MantellaSoftware/data/actions/{a['identifier']}.json", json.dumps(data, indent=4) + '\n')
print('world records written:', len(QUESTS), 'quests,', len(ACTIONS), 'actions')
