import manual
import steps
from fixtures import NOW, SPY, TODAY, good_manual, good_raw
from metrics import Metrics


def evaluate(raw=None, man=None, spy=None, peers=None, ticker="GOODCO"):
    raw = raw if raw is not None else good_raw()
    man = man if man is not None else good_manual()
    m = Metrics(raw, today=TODAY, now=NOW)
    return steps.evaluate(ticker, m, manual.Manual(ticker, man), SPY if spy is None else spy, peers or {})


def check(result, step_n, cid):
    st = result.steps[step_n - 1]
    for c in st.checks:
        if c.id == cid:
            return c
    raise KeyError(f"step {step_n} has no check {cid}: {[c.id for c in st.checks]}")


def set_row(raw, stmt, label, values):
    raw[stmt]["rows"][label] = list(values)
    return raw


def metrics(raw):
    return Metrics(raw, today=TODAY, now=NOW)
