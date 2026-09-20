"""Pure unit tests for the safety-first calibration policy."""
import sys
from calibrate import choose_threshold, validate_mix
failures = []
def check(label, value):
    print(f"[{'OK  ' if value else 'FAIL'}] {label}")
    if not value: failures.append(label)
rows = [
    {"threshold":.42,"precision":1.0,"recall":.70,"f1":.82,"false_positives":0},
    {"threshold":.47,"precision":1.0,"recall":.85,"f1":.92,"false_positives":0},
    {"threshold":.50,"precision":.98,"recall":.85,"f1":.91,"false_positives":0},
    {"threshold":.55,"precision":.97,"recall":.95,"f1":.96,"false_positives":1},
]
chosen = choose_threshold(rows)
check("unsafe high-recall row is rejected", chosen["threshold"] != .55)
check("highest safe recall wins", chosen["recall"] == .85)
check("tighter threshold breaks a recall tie", chosen["threshold"] == .47)
check("an explicit zero-FP cap is enforced", choose_threshold(rows,.90,.90,0) is None)
check("a policy with no passing row fails closed", choose_threshold(rows,1.0,.99) is None)
samples = [{"truth":"A"}]*30 + [{"truth":None}]*10
mix = validate_mix(samples,30,10)
check("a balanced held-out set passes", not mix["errors"])
check("enrolled samples are counted", mix["enrolled"] == 30)
check("strangers are counted", mix["unknown"] == 10)
check("too few strangers is refused", bool(validate_mix(samples[:35],30,10)["errors"]))
check("too few enrolled faces is refused", bool(validate_mix(samples[25:],30,10)["errors"]))
if failures:
    print(f"{len(failures)} calibration check(s) failed")
    sys.exit(1)
print("ALL CALIBRATION CHECKS PASSED")
