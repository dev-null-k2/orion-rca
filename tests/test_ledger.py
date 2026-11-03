from orion.harness import Ledger


def test_ledger_signs_and_detects_tampering():
    led = Ledger(key=b"k" * 32)
    ev = led.add("logs_search", {"q": "x"}, "logs", "1 hit", "ERROR boom")
    assert led.get(ev.id) is ev
    ev.content = "ERROR something else"
    assert led.get(ev.id) is None


def test_ids_are_sequential():
    led = Ledger()
    assert [led.add("t", {}, "s", "", "").id for _ in range(3)] == ["E1", "E2", "E3"]
