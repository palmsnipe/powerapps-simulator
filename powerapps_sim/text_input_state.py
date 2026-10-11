"""Instance and editing-contract identity for server-authoritative text events.

These stamps protect the simulator transport. They aren't Power Apps properties
and don't change the control's native output/callback publication contract.
"""
import hashlib
import json

EDITING_PROPERTIES = {
    'TextInput': ('MaxLength', 'TriggerOutput', 'Mode', 'Type'),
    'ModernTextInput': ('MaxLength', 'TriggerOutput', 'Mode', 'Type'),
    'Classic/TextInput': ('MaxLength', 'DelayOutput', 'Mode', 'Format'),
    'RichTextEditor': (),
}


def token(ref):
    from .runtime import serial
    r = ref.runtime
    ref.sync_default(r.input_property(ref))
    contract = [ref.control.kind, serial(r.input_baselines[ref.path]),
        *[serial(ref.property(name)) for name in EDITING_PROPERTIES[ref.family]]]
    signature = json.dumps(contract, sort_keys=True, ensure_ascii=False)
    epoch = r.text_resets.get(ref.path, 0)
    previous = r.text_contract_baselines.get(ref.path)
    # A changed contract followed by a return to its old value must not revive
    # an old queued draft. Reset/default changes may already advance the epoch.
    if previous is not None and previous[0] != signature and previous[1] == epoch:
        epoch += 1
        r.text_resets[ref.path] = epoch
    r.text_contract_baselines[ref.path] = (signature, epoch)
    digest = hashlib.sha256(signature.encode()).hexdigest()
    return f'{r.text_generation}:{ref.path}:{epoch}:{digest}'
