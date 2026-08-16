import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'kindle_hid_passthrough'))

import button_mapper


def use_config(monkeypatch, tmp_path, text=None):
    cfg = tmp_path / 'config.ini'
    if text is not None:
        cfg.write_text(text)
    monkeypatch.setattr(button_mapper, 'MAPPER_CONFIG', str(cfg))
    monkeypatch.setattr(button_mapper, '_reload_mapper', lambda: None)
    return cfg


def test_no_mapper_installed(monkeypatch, tmp_path):
    use_config(monkeypatch, tmp_path)
    assert button_mapper.register_device('AA:BB:CC:DD:EE:FF', 'Pad') is False


def test_registers_a_new_device(monkeypatch, tmp_path):
    cfg = use_config(monkeypatch, tmp_path, '[settings]\nkeep_awake = true\n')
    assert button_mapper.register_device('AA:BB:CC:DD:EE:FF', 'My Pad 2') is True
    text = cfg.read_text()
    assert '[device.my_pad_2]' in text
    assert 'uniq = AA:BB:CC:DD:EE:FF' in text
    assert 'name = My Pad 2' in text


def test_existing_uniq_is_not_duplicated(monkeypatch, tmp_path):
    cfg = use_config(
        monkeypatch, tmp_path,
        '[device.pad]\nuniq = aa:bb:cc:dd:ee:ff/P\n',
    )
    assert button_mapper.register_device('AA:BB:CC:DD:EE:FF', 'Pad') is False
    assert cfg.read_text().count('uniq') == 1


def test_slug_collision_gets_a_suffix(monkeypatch, tmp_path):
    cfg = use_config(
        monkeypatch, tmp_path,
        '[device.pad]\nuniq = 11:22:33:44:55:66\n',
    )
    assert button_mapper.register_device('AA:BB:CC:DD:EE:FF', 'Pad') is True
    assert '[device.pad_2]' in cfg.read_text()


def test_nameless_device_uses_mac_tail(monkeypatch, tmp_path):
    cfg = use_config(monkeypatch, tmp_path, '')
    assert button_mapper.register_device('AA:BB:CC:DD:EE:FF') is True
    assert '[device.dev_eeff]' in cfg.read_text()


def test_register_all_skips_wildcard_and_reloads_once(monkeypatch, tmp_path):
    use_config(monkeypatch, tmp_path, '')
    calls = []
    monkeypatch.setattr(button_mapper, '_reload_mapper', lambda: calls.append(1))
    button_mapper.register_all([
        ('*', None, None),
        ('AA:BB:CC:DD:EE:FF', None, 'Pad'),
        ('11:22:33:44:55:66', None, None),
    ])
    assert len(calls) == 1


DEVICE_CONFIG = """[settings]
keep_awake = true

[device.pad]
name = Pad
uniq = AA:BB:CC:DD:EE:FF

[device.pad.buttons]
304 = /mnt/us/x.sh

[device.kbd]
name = Keeb
uniq = 11:22:33:44:55:66
"""


def test_unregister_drops_the_block_and_its_children(monkeypatch, tmp_path):
    cfg = use_config(monkeypatch, tmp_path, DEVICE_CONFIG)
    assert button_mapper.unregister_device('aa:bb:cc:dd:ee:ff/P') is True
    text = cfg.read_text()
    assert '[device.pad]' not in text
    assert '[device.pad.buttons]' not in text
    assert '304 = /mnt/us/x.sh' not in text
    # Everything else survives untouched.
    assert '[device.kbd]' in text
    assert 'keep_awake = true' in text


def test_unregister_unknown_address_changes_nothing(monkeypatch, tmp_path):
    cfg = use_config(monkeypatch, tmp_path, DEVICE_CONFIG)
    assert button_mapper.unregister_device('99:99:99:99:99:99') is False
    assert cfg.read_text() == DEVICE_CONFIG


def test_unregister_without_a_mapper_is_a_noop(monkeypatch, tmp_path):
    use_config(monkeypatch, tmp_path)
    assert button_mapper.unregister_device('AA:BB:CC:DD:EE:FF') is False


def fake_proc(tmp_path, procs):
    """procs: {pid: argv list}. Returns the fake /proc root."""
    root = tmp_path / 'proc'
    root.mkdir()
    for pid, argv in procs.items():
        d = root / str(pid)
        d.mkdir()
        (d / 'cmdline').write_bytes(b'\0'.join(a.encode() for a in argv) + b'\0')
    (root / 'uptime').write_text('1 1')  # a non-pid entry, must be skipped
    return str(root)


BIN = '/mnt/us/kindle-button-mapper/kindle-button-mapper'


def test_daemon_pid_skips_the_waf_helper(tmp_path):
    proc = fake_proc(tmp_path, {
        10: ['/bin/sh', '-c', 'something'],
        20: [BIN, '--waf-helper', '/mnt/us/kindle-button-mapper/config.ini'],
        30: [BIN, '/mnt/us/kindle-button-mapper/config.ini'],
    })
    assert button_mapper._daemon_pid(proc) == 30


def test_daemon_pid_is_zero_when_nothing_runs(tmp_path):
    proc = fake_proc(tmp_path, {10: ['/bin/sh']})
    assert button_mapper._daemon_pid(proc) == 0


def test_reload_without_a_daemon_does_nothing(monkeypatch):
    monkeypatch.setattr(button_mapper, '_daemon_pid', lambda: 0)
    killed = []
    monkeypatch.setattr(button_mapper.os, 'kill', lambda *a: killed.append(a))
    button_mapper._reload_mapper()
    assert killed == []


def test_reload_sighups_the_daemon(monkeypatch):
    monkeypatch.setattr(button_mapper, '_daemon_pid', lambda: 4242)
    killed = []
    monkeypatch.setattr(button_mapper.os, 'kill', lambda *a: killed.append(a))
    button_mapper._reload_mapper()
    assert killed == [(4242, button_mapper.signal.SIGHUP)]
